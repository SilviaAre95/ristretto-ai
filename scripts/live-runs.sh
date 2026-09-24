#!/usr/bin/env bash
# Report the coding runs that are alive right now, one `pid command` line
# each. Exits 0 if anything is live, 1 if nothing is.
#
# Asks the operating system, not the board. The board is precisely what is
# unreliable here: a run whose process died stays `running` and claimed, and
# reads as healthy from every surface — the reasoning is in `flow_is_running`
# in cuzam/dash/launch.py. Process truth means a stalled run does not
# block an install or an update, which is the behaviour we want.
#
# Two shapes count, and they are exposed to different things:
#
#   - The staged runner (`full`, `short`) is spawned detached
#     (`start_new_session=True`), so it survives a gateway restart. It does
#     not survive its own code being swapped: the install is editable and the
#     runtime update is a checkout, while later stages re-read those files —
#     the broker is respawned per stage and several imports are lazy.
#
#   - `run-loop.sh` (classic) deliberately stays in the FOREGROUND under the
#     Hermes worker that supervises it by pid, so it dies on any gateway
#     restart. The comment at the top of run-loop.sh explains why detaching
#     it is not the fix. It is pinned the same way, so it is equally exposed
#     to the runtime being rebuilt under it.
#
# Both patterns are matched here rather than at each call site, because the
# first guard written (install-runtime.sh) matched only the staged one and a
# live classic loop walked straight through it.
set -uo pipefail

# Snapshot first, filter second, and never `pgrep -f`. A pattern search matches
# the command line of whatever runs the search, so the filter reports itself as
# a live run — `running_flows` in cuzam/dash/data.py documents this and
# avoids pgrep for the same reason. Capturing `ps` before the filter process
# exists is what keeps the filter out of its own results.
listing="$(ps -eo pid=,command= 2>/dev/null || true)"

live="$(printf '%s\n' "$listing" | awk '
  # Classic: the script must be what is executing, not merely named on some
  # other command line. It is reached either through a shell or by its shebang,
  # so the script path is the first or the second field after the pid.
  $2 ~ /loop-runner\/scripts\/run-loop\.sh$/ || $3 ~ /loop-runner\/scripts\/run-loop\.sh$/ { print; next }

  # Staged: a shell that merely mentions the runner is not running it.
  index($0, "-m cuzam.runner") && index($0, "--task-id") {
    exe = $2
    sub(/.*\//, "", exe)
    if (exe == "sh" || exe == "bash" || exe == "zsh") next
    print
  }
')"

[ -n "$live" ] || exit 1
printf '%s\n' "$live"
