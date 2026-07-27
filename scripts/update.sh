#!/usr/bin/env bash
# One-command update for a running Ristretto install: pull the release,
# refresh managed assets (idempotent installers — user-owned persona, config,
# credentials, and jobs are never overwritten), surface template drift, and
# restart the gateway so the running service picks the release up.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

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
