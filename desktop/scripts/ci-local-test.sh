#!/usr/bin/env bash
# Run the Desktop Release workflow's Linux build job locally, 1-1, inside a
# Docker container that mirrors the GitHub Actions runner.
#
# Uses `act` (https://github.com/nektos/act) — it executes the literal
# workflow YAML in a `catthehacker/ubuntu` image, so the steps run exactly
# as they would on GitHub's `ubuntu-22.04` runner.
#
# Only the Linux build leg is covered: the `windows-latest` / `macos-*`
# matrix legs cannot run in a Linux container and must be validated on a
# real runner. The `release` job is skipped — it needs the live GitHub API.
#
# Requires: Docker, and `act` on PATH
#   (install: curl -fsSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b ~/.local/bin)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORKFLOW=".github/workflows/desktop-release.yml"

command -v docker >/dev/null 2>&1 || { echo "error: Docker is required" >&2; exit 1; }
command -v act >/dev/null 2>&1 || {
  echo "error: act not found — install with:" >&2
  echo "  curl -fsSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b ~/.local/bin" >&2
  exit 1
}

cd "$REPO_ROOT"

# The workflow triggers on push-to-main; synthesize that event so the job is
# not filtered out when this script runs from another branch.
event_file="$(mktemp)"
artifact_dir="$(mktemp -d)"
trap 'rm -f "$event_file"' EXIT
printf '{ "ref": "refs/heads/main" }\n' >"$event_file"

echo "[ci-local-test] running the 'build' job (linux-x64) via act..."
echo "[ci-local-test] artifacts will land in: $artifact_dir"

act push \
  -W "$WORKFLOW" \
  -j build \
  --matrix label:linux-x64 \
  -P ubuntu-22.04=catthehacker/ubuntu:act-22.04 \
  --artifact-server-path "$artifact_dir" \
  --eventpath "$event_file"

echo "[ci-local-test] build job passed — installers under $artifact_dir"
