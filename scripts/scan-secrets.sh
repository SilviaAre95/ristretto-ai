#!/usr/bin/env bash
# Fast tracked-file credential scan. This includes example files: templates
# must use empty values, never copied or synthetic token-shaped values.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

fail=0
scan() {
  local label="$1"
  local pattern="$2"
  local output
  output="$(git grep -nE "$pattern" -- . ':!scripts/scan-secrets.sh' 2>/dev/null || true)"
  if [ -n "$output" ]; then
    echo "SECRET SCAN BLOCKER: $label" >&2
    echo "$output" >&2
    fail=1
  fi
}

scan "Slack credential" 'xox[baprs]-[A-Za-z0-9-]{20,}'
scan "GitHub credential" 'gh[pousr]_[A-Za-z0-9_]{20,}'
scan "Anthropic credential" 'sk-ant-[A-Za-z0-9_-]{16,}'
scan "AWS access key" 'AKIA[0-9A-Z]{16}'
scan "private key block" '-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'

if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "secret-scan: ok"
