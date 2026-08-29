#!/usr/bin/env bash
# Deliver any pipeline milestones that have happened since the last run.
#
# Run from cron rather than as a daemon. A missed tick delivers late; a
# crashed daemon delivers never, and nobody notices a silent notifier. The
# cursor makes catching up free, so lateness is the only cost.
set -u
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin"
command -v ristretto >/dev/null 2>&1 || exit 0
ristretto doorbell --once 2>&1 | tail -1
