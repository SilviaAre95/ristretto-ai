#!/usr/bin/env bash
# ris-stop.sh <task_id> — S-5 kill switch: stop a running kanban task,
# its Hermes worker, and its Claude Code grandchild. Safe: grandchild is
# killed only via the verified reap (Guard 4); the worker is matched by
# its exact spawn signature.
# Exits non-zero with a "NOT STOPPED" message if the stop did not take
# (e.g. the task was promoted between stage 1 and stage 3 — re-run to retry).
set -u
TASK_ID="${1:?usage: ris-stop.sh <task_id>}"
if [[ ! "$TASK_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "ris-stop: task id contains unsafe characters" >&2
  exit 2
fi
TASK_PATTERN="${TASK_ID//./\\.}"
export PATH="$HOME/.local/bin:$PATH"

# 1. Release the claim so the dispatcher does NOT re-dispatch while we stop it.
hermes kanban reclaim "$TASK_ID" --reason "manual stop (ris-stop.sh)" || true
hermes kanban block "$TASK_ID" 2>/dev/null || true

# 2. Kill the Hermes worker for this task (spawn signature: hermes -p ris-worker … "work kanban task <id>")
pkill -TERM -f "work kanban task $TASK_PATTERN$" 2>/dev/null && sleep 3
pkill -KILL -f "work kanban task $TASK_PATTERN$" 2>/dev/null

# 3. Verified-kill the Claude Code grandchild (Guard 4 — mismatches are never killed).
bash "$HOME/.hermes/skills/software-development/loop-runner/scripts/reap.sh" "$TASK_ID"

# 4. Verification pass — catches the race where the worker promotes the task
#    between stage 1 and stage 3, causing silent false-green in old versions.
#    Re-block in case the task was promoted during stages 2-3.
hermes kanban block "$TASK_ID" 2>/dev/null || true

TASK_STATE=$(hermes kanban show --json "$TASK_ID" 2>/dev/null \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('task',d).get('status',''))")

WORKER_PIDS=$(pgrep -f "work kanban task $TASK_PATTERN$" 2>/dev/null | tr '\n' ',' | sed 's/,$//')

case "$TASK_STATE" in
  blocked|archived|done) STATE_OK=1 ;;
  *) STATE_OK=0 ;;
esac

if [ "$STATE_OK" = "1" ] && [ -z "$WORKER_PIDS" ]; then
  echo "stopped: task $TASK_ID (reclaimed + blocked; worker and verified grandchild killed)"
else
  echo "NOT STOPPED: task $TASK_ID state=${TASK_STATE:-unknown}, worker pids=${WORKER_PIDS:-none} — re-run ris-stop.sh" >&2
  exit 1
fi
