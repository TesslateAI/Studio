#!/usr/bin/env bash
# scripts/notify.sh — Send notifications to Slack (extensible to other providers)
#
# Usage:
#   ./scripts/notify.sh "message text"
#   ./scripts/notify.sh --channel "#ops" "message text"
#   echo "multi-line output" | ./scripts/notify.sh --stdin
#   ./scripts/notify.sh --level error "Deploy failed"
#   ./scripts/notify.sh --title "Health Check" --level ok "All pods healthy"
#
# Environment:
#   SLACK_WEBHOOK_URL  — Required. Slack Incoming Webhook URL.
#   NOTIFY_CHANNEL     — Optional default channel override (if webhook supports it).
#
# Exit codes:
#   0 — sent successfully
#   1 — missing config / bad args
#   2 — send failed

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────
LEVEL=""
TITLE=""
CHANNEL="${NOTIFY_CHANNEL:-}"
USE_STDIN=false
MESSAGE=""

# ── Parse args ────────────────────────────────────────────────
usage() {
  echo "Usage: notify.sh [--level ok|warn|error] [--title TEXT] [--channel #CH] [--stdin] MESSAGE"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --level)   LEVEL="$2"; shift 2 ;;
    --title)   TITLE="$2"; shift 2 ;;
    --channel) CHANNEL="$2"; shift 2 ;;
    --stdin)   USE_STDIN=true; shift ;;
    --help|-h) usage ;;
    -*)        echo "Unknown flag: $1"; usage ;;
    *)         MESSAGE="$1"; shift ;;
  esac
done

if [[ "$USE_STDIN" == true ]]; then
  STDIN_CONTENT=$(cat)
  MESSAGE="${MESSAGE:+$MESSAGE\n}${STDIN_CONTENT}"
fi

if [[ -z "$MESSAGE" ]]; then
  echo "Error: No message provided." >&2
  usage
fi

# ── Validate config ──────────────────────────────────────────
if [[ -z "${SLACK_WEBHOOK_URL:-}" ]]; then
  echo "Error: SLACK_WEBHOOK_URL is not set." >&2
  echo "" >&2
  echo "Setup:" >&2
  echo "  1. Go to https://api.slack.com/apps → Create New App → From scratch" >&2
  echo "  2. Enable 'Incoming Webhooks' → Add New Webhook to Workspace" >&2
  echo "  3. Pick a channel → Copy the webhook URL" >&2
  echo "  4. Export it:  export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T.../B.../...'" >&2
  echo "     Or add to .env.local:  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..." >&2
  exit 1
fi

# ── Format ────────────────────────────────────────────────────
PREFIX=""
case "${LEVEL}" in
  ok|success) PREFIX="ok — " ;;
  warn*)      PREFIX="heads up — " ;;
  error|fail) PREFIX="ALERT — " ;;
  info)       PREFIX="" ;;
  *)          PREFIX="" ;;
esac

FORMATTED=""
if [[ -n "$TITLE" ]]; then
  FORMATTED="*${PREFIX}${TITLE}*"$'\n'"${MESSAGE}"
elif [[ -n "$PREFIX" ]]; then
  FORMATTED="*${PREFIX%— }*— ${MESSAGE}"
else
  FORMATTED="${MESSAGE}"
fi

# ── Build JSON payload ────────────────────────────────────────
# Use jq if available for proper escaping, otherwise python, otherwise manual
build_payload() {
  local text="$1"
  local channel="$2"

  if command -v jq &>/dev/null; then
    if [[ -n "$channel" ]]; then
      jq -n --arg t "$text" --arg c "$channel" '{text: $t, channel: $c}'
    else
      jq -n --arg t "$text" '{text: $t}'
    fi
  elif command -v python3 &>/dev/null; then
    python3 -c "
import json, sys
payload = {'text': sys.argv[1]}
if sys.argv[2]:
    payload['channel'] = sys.argv[2]
print(json.dumps(payload))
" "$text" "$channel"
  else
    # Manual escape — handles quotes and backslashes
    local escaped
    escaped=$(printf '%s' "$text" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')
    if [[ -n "$channel" ]]; then
      printf '{"text":"%s","channel":"%s"}' "$escaped" "$channel"
    else
      printf '{"text":"%s"}' "$escaped"
    fi
  fi
}

PAYLOAD=$(build_payload "$FORMATTED" "$CHANNEL")

# ── Send ──────────────────────────────────────────────────────
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$SLACK_WEBHOOK_URL" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD" \
  --max-time 10)

if [[ "$RESPONSE" == "200" ]]; then
  echo "Sent."
  exit 0
else
  echo "Error: Slack returned HTTP $RESPONSE" >&2
  exit 2
fi
