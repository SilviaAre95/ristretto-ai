#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

fail=0

bash scripts/scan-secrets.sh || fail=1

report_matches() {
  local label="$1"
  local pattern="$2"
  shift 2
  local output
  output="$(git grep -nE "$pattern" -- "$@" 2>/dev/null || true)"
  if [ -n "$output" ]; then
    echo "PUBLICATION BLOCKER: $label" >&2
    echo "$output" >&2
    fail=1
  fi
}

report_matches "machine-specific absolute paths" '/(Users|home)/[^/[:space:]]+(/|$)' . ':!scripts/check-public.sh'
report_matches "hard-coded Slack object IDs" '(^|[^A-Z0-9])[CDGUTW][0-9][A-Z0-9]{7,}([^A-Z0-9]|$)' . ':!scripts/check-public.sh'
report_matches "private account or workspace identifiers" '(silviaxari|silviaar0816|xari-projects)' . ':!scripts/check-public.sh'
report_matches "personal vault paths" '~/(Documents|Library)/' . ':!scripts/check-public.sh'

for path in \
  STATE.md \
  hermes/cron/jobs.json \
  docs/linear-backfill-draft.md \
  docs/01-plan.md \
  docs/02-phase1-setup.md \
  docs/04-hermes-config-in-repo.md \
  docs/05-durable-work-runbook.md; do
  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    echo "PUBLICATION BLOCKER: tracked personal/runtime file: $path" >&2
    fail=1
  fi
done

if git ls-files 'docs/superpowers/**' 'docs/features/*.CHANGELOG.md' | grep -q .; then
  echo "PUBLICATION BLOCKER: private operational history is tracked" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "public-check: NOT READY — see docs/open-source-readiness.md" >&2
  exit 1
fi

echo "public-check: ready"
