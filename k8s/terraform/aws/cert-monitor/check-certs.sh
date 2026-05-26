#!/bin/sh
# =============================================================================
# Certificate health check — runs in a Kubernetes CronJob.
# =============================================================================
# Inspects all cert-manager Certificates across all namespaces and flags:
#   - certs whose notAfter is within $WARN_DAYS (default 14)
#   - certs whose Issuing=True transitioned more than $STUCK_HOURS ago (default 24)
#   - certs whose Ready=False with reason != Issuing  (renewal failure)
#
# Output is always emitted to stdout (kubectl logs of the job pod). If
# $WEBHOOK_URL is non-empty, the same findings are POSTed as a Slack-compatible
# JSON payload. Empty WEBHOOK_URL → log-only mode (still useful via kubectl).
# Exit code 0 on success (whether or not findings exist) so the CronJob is
# never marked failed for "ordinary" alerts; exit non-zero only on infra errors
# (kubectl unreachable, json parse failure).
#
# Written in POSIX sh + python3 (no bash-isms) so it runs on minimal images.
# =============================================================================
set -eu

: "${WARN_DAYS:=14}"
: "${STUCK_HOURS:=24}"
: "${CLUSTER_LABEL:=unknown}"
: "${WEBHOOK_URL:=}"

# Fetch all Certificates as JSON. If kubectl fails, exit non-zero so the
# Job is marked Failed and surfaced by the alerting that observes Job status.
TMPDIR_LOCAL=$(mktemp -d)
trap 'rm -rf "$TMPDIR_LOCAL"' EXIT

if ! kubectl get certificates.cert-manager.io -A -o json > "$TMPDIR_LOCAL/certs.json" 2> "$TMPDIR_LOCAL/err"; then
  echo "ERROR: kubectl failed: $(cat "$TMPDIR_LOCAL/err")" >&2
  exit 2
fi

# Parse each cert with python (more reliable than awk on multi-condition status).
FINDINGS=$(python3 - "$TMPDIR_LOCAL/certs.json" <<'PYEOF'
import json
import os
import sys
import time
from datetime import datetime

warn_secs = int(os.environ.get("WARN_DAYS", "14")) * 86400
stuck_secs = int(os.environ.get("STUCK_HOURS", "24")) * 3600
now = int(time.time())

def parse_iso(s):
    if not s:
        return None
    # cert-manager emits trailing Z; older python needs +00:00
    s2 = s.replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(s2).timestamp())
    except ValueError:
        return None

with open(sys.argv[1]) as f:
    certs = json.load(f).get("items", [])

findings = []
for c in certs:
    md = c.get("metadata", {})
    ns = md.get("namespace", "")
    name = md.get("name", "")
    st = c.get("status", {})
    conds = {x.get("type"): x for x in st.get("conditions", [])}

    not_after = parse_iso(st.get("notAfter"))
    if not_after is not None:
        delta = not_after - now
        if delta < 0:
            findings.append((
                "CRITICAL",
                "%s/%s" % (ns, name),
                "EXPIRED %dh ago" % ((-delta) // 3600),
            ))
        elif delta < warn_secs:
            findings.append((
                "WARN",
                "%s/%s" % (ns, name),
                "expires in %dd %dh" % (delta // 86400, (delta % 86400) // 3600),
            ))

    issuing = conds.get("Issuing")
    if issuing and issuing.get("status") == "True":
        t = parse_iso(issuing.get("lastTransitionTime"))
        if t is not None and (now - t) > stuck_secs:
            findings.append((
                "WARN",
                "%s/%s" % (ns, name),
                "renewal stuck for %dh (reason=%s)" % (
                    (now - t) // 3600,
                    issuing.get("reason", "?"),
                ),
            ))

    ready = conds.get("Ready")
    if ready and ready.get("status") == "False" and ready.get("reason") not in ("Issuing", None):
        t = parse_iso(ready.get("lastTransitionTime"))
        age_h = (now - t) // 3600 if t else 0
        if age_h > 1:
            findings.append((
                "WARN",
                "%s/%s" % (ns, name),
                "Ready=False for %dh (%s: %s)" % (
                    age_h,
                    ready.get("reason", "?"),
                    (ready.get("message") or "")[:120],
                ),
            ))

for level, cert, reason in findings:
    print("%s\t%s\t%s" % (level, cert, reason))
PYEOF
)

CERT_COUNT=$(python3 -c "import json; print(len(json.load(open('$TMPDIR_LOCAL/certs.json')).get('items', [])))")

if [ -z "$FINDINGS" ]; then
  echo "[$CLUSTER_LABEL] cert-monitor: all clear ($CERT_COUNT certificates checked)"
  exit 0
fi

echo "[$CLUSTER_LABEL] cert-monitor findings ($CERT_COUNT certificates checked):"
echo "$FINDINGS" | sed 's/^/  /'

if [ -n "$WEBHOOK_URL" ]; then
  # Slack-compatible payload — also accepted by Discord webhooks and most
  # generic webhook receivers. If you point this at Mattermost or Teams
  # they accept the same shape.
  echo "$FINDINGS" > "$TMPDIR_LOCAL/findings.txt"
  PAYLOAD=$(python3 - "$TMPDIR_LOCAL/findings.txt" "$CLUSTER_LABEL" <<'PYEOF'
import json, sys
findings = open(sys.argv[1]).read()
cluster = sys.argv[2]
text = ":rotating_light: *cert-monitor* on *%s*\n```\n%s\n```" % (cluster, findings)
print(json.dumps({"text": text}))
PYEOF
)
  HTTP_CODE=$(curl -sS -o "$TMPDIR_LOCAL/wh.out" -w '%{http_code}' \
    -X POST -H 'Content-Type: application/json' \
    --data "$PAYLOAD" "$WEBHOOK_URL" || echo "000")
  if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "204" ]; then
    echo "WARN: webhook delivery returned HTTP $HTTP_CODE: $(cat "$TMPDIR_LOCAL/wh.out" 2>/dev/null)" >&2
  fi
fi

# Always exit 0 — findings aren't a job failure, they're job output.
exit 0
