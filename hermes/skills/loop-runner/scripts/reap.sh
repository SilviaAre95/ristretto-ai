#!/usr/bin/env bash
# reap.sh <task_id> — Guard 4: verified orphan reaping (spec S-1).
# Kills a previously-recorded claude process ONLY if pid + start-time + cwd
# all match the record. On any mismatch: do NOT kill, log, remove the record.
# The record lives OUTSIDE the worktree so the policed process can never
# author its own reaping record. Always exits 0 (reaping is best-effort;
# Guard 1 in loop-dev is the backstop). Invalid identifiers exit 2.
set -u
TASK_ID="${1:?usage: reap.sh <task_id>}"
BOARD="${HERMES_KANBAN_BOARD:-default}"
if [[ ! "$TASK_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "reap: task id contains unsafe characters" >&2
  exit 2
fi
if [[ ! "$BOARD" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "reap: board id contains unsafe characters" >&2
  exit 2
fi
REC="$HOME/.hermes/kanban/$BOARD/pids/$TASK_ID.json"

[ -f "$REC" ] || exit 0

PID="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('pid',0))" "$REC")"
REC_LSTART="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('lstart',''))" "$REC")"
REC_WT="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('worktree',''))" "$REC")"
REC_RUNNER="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('runner','claude'))" "$REC")"

# Normalize path in case it's symlinked (macOS: /var → /private/var)
REC_WT="$(cd "$REC_WT" 2>/dev/null && pwd -P || echo "$REC_WT")"

if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$REC"; exit 0            # already gone — clean up
fi

LIVE_LSTART="$(ps -p "$PID" -o lstart= 2>/dev/null | sed 's/^ *//;s/ *$//')"
LIVE_CMD="$(ps -p "$PID" -o command= 2>/dev/null)"
LIVE_CWD="$(lsof -a -p "$PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"

CMD_FIRST="${LIVE_CMD%% *}"
CMD_REST="${LIVE_CMD#* }"
if [ "$CMD_REST" = "$LIVE_CMD" ]; then
  CMD_SECOND=""
else
  CMD_SECOND="${CMD_REST%% *}"
fi
CMD_FIRST="${CMD_FIRST##*/}"
CMD_SECOND="${CMD_SECOND##*/}"
case "$REC_RUNNER" in
  claude|codex|bash)
    if [ "$CMD_FIRST" = "$REC_RUNNER" ] || [ "$CMD_SECOND" = "$REC_RUNNER" ]; then
      CMD_OK=1
    else
      CMD_OK=0
    fi
    ;;
  *) CMD_OK=0 ;;
esac

if [ "$CMD_OK" -eq 1 ] && [ "$LIVE_LSTART" = "$REC_LSTART" ] && [ "$LIVE_CWD" = "$REC_WT" ]; then
  kill -TERM "$PID" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
  done
  kill -0 "$PID" 2>/dev/null && kill -KILL "$PID" 2>/dev/null
  echo "reap: killed verified orphan pid=$PID task=$TASK_ID" >&2
else
  echo "reap: identity MISMATCH for pid=$PID task=$TASK_ID (cmd_ok=$CMD_OK) — NOT killing (S-1)" >&2
fi
rm -f "$REC"
exit 0
