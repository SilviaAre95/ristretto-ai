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
#    Two signatures, because runs exist in both shapes. `cuzam launch` now
#    starts the flow itself as `python -m cuzam.runner --task-id <id>`; it
#    used to hand the task to an agent, whose spawn signature was
#    "work kanban task <id>". Matching only the worker meant stop silently did
#    nothing to a directly-launched run — and then reported success, because
#    the verification below asked only "is it blocked?" (it blocked it itself)
#    and "are there worker pids?" (there never were). The flow carried on to
#    `finish` and pushed.
#
#    TERM first so the runner's own handler commits what the stage wrote.
for SIGNATURE in "work kanban task $TASK_PATTERN\$" "cuzam\.runner --task-id $TASK_PATTERN( |\$)"; do
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

# Both signatures again: "no worker pids" was vacuously true for a run that
# never had a worker, which is what made the false-green possible.
WORKER_PIDS=$( { pgrep -f "work kanban task $TASK_PATTERN\$" 2>/dev/null; \
                 pgrep -f "cuzam\.runner --task-id $TASK_PATTERN( |\$)" 2>/dev/null; } \
               | tr '\n' ',' | sed 's/,$//')

case "$TASK_STATE" in
  blocked|archived|done) STATE_OK=1 ;;
  *) STATE_OK=0 ;;
esac

if [ "$STATE_OK" = "1" ] && [ -z "$WORKER_PIDS" ]; then
  echo "stopped: task $TASK_ID (reclaimed + blocked; worker and verified grandchild killed)"
else
  echo "NOT STOPPED: task $TASK_ID state=${TASK_STATE:-unknown}, worker pids=${WORKER_PIDS:-none} — re-run zam-stop.sh" >&2
  exit 1
fi
