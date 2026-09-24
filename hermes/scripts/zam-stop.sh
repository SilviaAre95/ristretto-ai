#!/usr/bin/env bash
# zam-stop.sh <task_id> — S-5 kill switch: stop a running kanban task,
# its Hermes worker, and its Claude Code grandchild. Safe: grandchild is
# killed only via the verified reap (Guard 4); the worker is matched by
# its exact spawn signature.
# Exits non-zero with a "NOT STOPPED" message if the stop did not take
# (e.g. the task was promoted between stage 1 and stage 3 — re-run to retry).
set -u
TASK_ID="${1:?usage: zam-stop.sh <task_id>}"
if [[ ! "$TASK_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "zam-stop: task id contains unsafe characters" >&2
  exit 2
fi
TASK_PATTERN="${TASK_ID//./\\.}"
export PATH="$HOME/.local/bin:$PATH"

# 1. Release the claim so the dispatcher does NOT re-dispatch while we stop it.
hermes kanban reclaim "$TASK_ID" --reason "manual stop (zam-stop.sh)" || true
hermes kanban block "$TASK_ID" 2>/dev/null || true

# 2. Kill whatever is running this task.
#
#    One signature per run shape, and the count is load-bearing. A shape with no
#    signature here is a stop that kills nothing, passes its own verification
#    below — the task is blocked because stage 1 blocked it, and no pid matches a
#    pattern that cannot match — and then reports success while the run carries
#    on to `finish` and pushes. That has happened: matching only the worker meant
#    stop did nothing to a `cuzam launch`ed staged run, and signature 2 closed it.
#
#      1. the Hermes worker agent. Retired with the dispatcher decoupling, kept
#         for one release because a task queued before the change can still be
#         running under a worker. Drop in 0.3.0.
#      2. the staged runner, which `launch` spawns as `-m cuzam.runner`.
#      3. the classic loop, which `launch` spawns as `bash .../run-loop.sh <id>`.
#         It needed no pattern of its own until the decoupling, because killing
#         the worker in 1 killed run-loop.sh as its child. Nothing is above it
#         now, so without this a classic run could not be stopped at all.
#
#    Defined once. The kill below and the verification at step 4 used to carry
#    the list separately and the comment there said "both signatures again";
#    three is where keeping two copies in step stops being reliable.
SIGNATURES=(
  "work kanban task $TASK_PATTERN\$"
  "cuzam\.runner --task-id $TASK_PATTERN( |\$)"
  "run-loop\.sh $TASK_PATTERN( |\$)"
)

#    TERM first so the runner's own handler commits what the stage wrote.
for SIGNATURE in "${SIGNATURES[@]}"; do
  pkill -TERM -f "$SIGNATURE" 2>/dev/null && sleep 3
  pkill -KILL -f "$SIGNATURE" 2>/dev/null
done

# 3. Verified-kill the Claude Code grandchild (Guard 4 — mismatches are never killed).
bash "$HOME/.hermes/skills/software-development/loop-runner/scripts/reap.sh" "$TASK_ID"

# 4. Verification pass — catches the race where the worker promotes the task
#    between stage 1 and stage 3, causing silent false-green in old versions.
#    Re-block in case the task was promoted during stages 2-3.
hermes kanban block "$TASK_ID" 2>/dev/null || true

TASK_STATE=$(hermes kanban show --json "$TASK_ID" 2>/dev/null \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('task',d).get('status',''))")

# Every signature again: "no worker pids" was vacuously true for a run that
# never had a worker, which is what made the false-green possible. A shape
# missing from SIGNATURES reintroduces exactly that.
WORKER_PIDS=$( for SIGNATURE in "${SIGNATURES[@]}"; do
                 pgrep -f "$SIGNATURE" 2>/dev/null
               done | tr '\n' ',' | sed 's/,$//')

# And then the question the signatures cannot answer about themselves. Every
# check above is built from patterns written here, so "no pid matched" means
# either "the run is dead" or "the pattern was wrong" — indistinguishable, and
# the second reads exactly like success. That is not hypothetical: it is what
# this file looked like for the staged runner, and again for the classic loop
# once nothing was above it.
#
# `live-runs.sh` is the standalone answer to "what is a live run", pinned against
# `cuzam/runs.py` by a contract test that fails when a flow has no fixture. So a
# shape it knows about and this file does not now produces NOT STOPPED rather
# than a false green, and a shape added to the launcher inherits the check.
#
# Absent — an install predating it — leaves the verification as it was rather
# than failing the stop, because refusing to report on a kill that may well have
# worked is its own kind of wrong answer.
LIVE_RUNS="$HOME/.hermes/scripts/live-runs.sh"
STILL_LIVE=""
if [ -f "$LIVE_RUNS" ]; then
  STILL_LIVE="$(bash "$LIVE_RUNS" 2>/dev/null | grep -F -- "$TASK_ID" || true)"
fi

case "$TASK_STATE" in
  blocked|archived|done) STATE_OK=1 ;;
  *) STATE_OK=0 ;;
esac

if [ -n "$STILL_LIVE" ]; then
  echo "zam-stop: a process for $TASK_ID is still live and matched no kill signature:" >&2
  printf '%s\n' "$STILL_LIVE" >&2
  STATE_OK=0
fi

if [ "$STATE_OK" = "1" ] && [ -z "$WORKER_PIDS" ]; then
  echo "stopped: task $TASK_ID (reclaimed + blocked; worker and verified grandchild killed)"
else
  echo "NOT STOPPED: task $TASK_ID state=${TASK_STATE:-unknown}, worker pids=${WORKER_PIDS:-none} — re-run zam-stop.sh" >&2
  exit 1
fi
