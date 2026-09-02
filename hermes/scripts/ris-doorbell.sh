#!/usr/bin/env bash
# Deliver any pipeline milestones that have happened since the last run.
#
# Run from cron rather than as a daemon. A missed tick delivers late; a
# crashed daemon delivers never, and nobody notices a silent notifier. The
# cursor makes catching up free, so lateness is the only cost.
set -u
# tailscale lives in /usr/local/bin. Without it on PATH the dashboard address
# cannot be resolved and every link in every notification silently became
# http://127.0.0.1:8787 — which on a phone points at the phone.
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
command -v ristretto >/dev/null 2>&1 || exit 0
ristretto doorbell --once 2>&1 | tail -1
