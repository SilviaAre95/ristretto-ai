#!/usr/bin/env bash
# One-command update for a running Ristretto install: pull the release,
# refresh managed assets (idempotent installers — user-owned persona, config,
# credentials, and jobs are never overwritten), surface template drift, and
# restart the gateway so the running service picks the release up.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

# Refuse the whole update while a run is live, before anything moves. Every
# step below is hostile to a run in flight, not just the restart at the end:
# install-hermes.sh repoints the `loop-runner` link, a runtime rebuild swaps
# the code a staged flow is executing out of, and `hermes gateway restart`
# kills any classic loop outright — Hermes' drain budget is 0 by design
# (hermes_cli/config.py, `restart_drain_timeout`), because a window large
# enough to save an hour-long run would have to outlast an unbounded task.
# So the drain is not the thing to fix; running this at all is.
if live="$(bash scripts/live-runs.sh)"; then
  echo "update: refusing while a run is live" >&2
  printf '  %s\n' "$live" >&2
  echo "  updating restarts the gateway and swaps code under it — stop it, or wait" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "update: checkout has local changes — commit or stash them first" >&2
  exit 1
fi

git pull --ff-only

bash scripts/install.sh
bash scripts/install-hermes.sh
bash scripts/template-drift.sh

if command -v hermes >/dev/null 2>&1; then
  if hermes gateway status >/dev/null 2>&1; then
    hermes gateway restart
  else
    echo "update: gateway service not installed/running — skipped restart"
  fi
fi

echo "update: done — Ristretto $(tr -d '[:space:]' < VERSION 2>/dev/null || echo unknown)"
