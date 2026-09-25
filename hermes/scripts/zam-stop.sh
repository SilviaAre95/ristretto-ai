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

# The same resolution install-hermes.sh uses to decide where it put these. Both
# the reap script and the liveness guard below were reached through a hardcoded
# ~/.hermes, which is wrong on any install that sets one of these — and the
# liveness guard failing that way is silent, which is the failure it exists to
# prevent.
HERMES_DIR="${CUZAM_HERMES_HOME:-${RISTRETTO_HERMES_HOME:-${HERMES_HOME:-$HOME/.hermes}}}"

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
#
#    The pid is read BEFORE the reap, because reap.sh removes the record whether
#    it killed or declined — so after it runs there is nothing left to check
#    against. That record is the only thing that knows which process Claude is:
#    `live-runs.sh` matches run-loop.sh and cuzam.runner, and the kill signatures
#    match those plus the retired worker. None of them match `claude`, and it is
#    the one process here that edits files and opens pull requests.
BOARD="${HERMES_KANBAN_BOARD:-default}"
CLAUDE_PID=""
if [[ "$BOARD" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  REC="$HERMES_DIR/kanban/$BOARD/pids/$TASK_ID.json"
  if [ -f "$REC" ]; then
    CLAUDE_PID="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('pid',''))" \
      "$REC" 2>/dev/null || true)"
  fi
fi

REAP="$HERMES_DIR/skills/software-development/loop-runner/scripts/reap.sh"
if [ -f "$REAP" ]; then
  bash "$REAP" "$TASK_ID"
else
  # Unchecked before, and `bash` exiting 127 looks like nothing happening. The
  # grandchild is the process that can still push, so a missing reaper is said
  # out loud rather than absorbed.
  echo "zam-stop: $REAP is missing — the Claude grandchild was not reaped;" \
       "run make update" >&2
fi

# 4. Verification pass — catches the race where the worker promotes the task
#    between stage 1 and stage 3, causing silent false-green in old versions.
#    Re-block in case the task was promoted during stages 2-3.
hermes kanban block "$TASK_ID" 2>/dev/null || true

# python's stderr is discarded too, not just hermes'. An unknown or archived id
# makes `kanban show` print nothing, `json.load` raise, and the traceback went to
# this script's stderr — which cuzam/dash/control.py captures and surfaces in the
# dashboard verbatim. So the Stop button showed a JSONDecodeError and an
# interpreter path above the real NOT STOPPED line, which is both a leak and the
# message that mattered pushed out of view. An empty state is already handled
# below as `state=unknown`, which is the honest answer.
TASK_STATE=$(hermes kanban show --json "$TASK_ID" 2>/dev/null \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('task',d).get('status',''))" \
    2>/dev/null)

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
# worked is its own kind of wrong answer. It says so on stderr rather than
# degrading quietly: a check that silently stops checking is how the false green
# came back the first time.
LIVE_RUNS="$HERMES_DIR/scripts/live-runs.sh"
STILL_LIVE=""
if [ -f "$LIVE_RUNS" ]; then
  # Matched as a whole argument, not as a substring. The kill signatures above
  # are anchored with `( |$)` for exactly this reason and this check was not:
  # task ids are variable length (`t_[0-9a-f]{6,}`), so one can be a strict
  # prefix of another, and stopping `t_abc123` while `t_abc1234` ran would have
  # reported NOT STOPPED with the other run's pid folded in — a stop that worked,
  # surfaced to the dashboard as a failure. Field comparison rather than a
  # pattern, so nothing in the id needs escaping.
  STILL_LIVE="$(bash "$LIVE_RUNS" 2>/dev/null \
    | awk -v want="$TASK_ID" '{ for (i = 2; i <= NF; i++) if ($i == want) { print; next } }' \
    || true)"
else
  echo "zam-stop: $LIVE_RUNS is missing — verifying by kill signature only;" \
       "run make update to install it" >&2
fi

case "$TASK_STATE" in
  blocked|archived|done) STATE_OK=1 ;;
  *) STATE_OK=0 ;;
esac

# reap.sh always exits 0 and, on an identity mismatch, declines to kill and
# deletes the record anyway — so "the reaper ran" says nothing about whether the
# grandchild died. A mismatch is reachable without anything being wrong: LIVE_CWD
# comes from `lsof`, and an absent or denied probe returns empty, which cannot
# equal the recorded worktree. Claude then keeps running under
# `--permission-mode acceptEdits` in the worktree with nothing above it, free to
# finish and open a pull request, while every other check here passes and the
# stop reports success. That is the false green this section exists to close,
# aimed at the only process that can still change the repository.
CLAUDE_ALIVE=""
if [ -n "${CLAUDE_PID:-}" ] && [[ "$CLAUDE_PID" =~ ^[0-9]+$ ]] && [ "$CLAUDE_PID" -gt 0 ]; then
  if kill -0 "$CLAUDE_PID" 2>/dev/null; then
    CLAUDE_ALIVE="$CLAUDE_PID"
  fi
fi

if [ -n "$CLAUDE_ALIVE" ]; then
  echo "zam-stop: the Claude grandchild pid=$CLAUDE_ALIVE survived the reap for" \
       "$TASK_ID — it can still edit and push. Guard 4 refuses to kill on an" \
       "identity mismatch, so check it by hand: ps -p $CLAUDE_ALIVE -o command=" >&2
  STATE_OK=0
  WORKER_PIDS="${WORKER_PIDS:+$WORKER_PIDS,}$CLAUDE_ALIVE (claude, unreaped)"
fi

if [ -n "$STILL_LIVE" ]; then
  echo "zam-stop: a process for $TASK_ID is still live and matched no kill signature:" >&2
  printf '%s\n' "$STILL_LIVE" >&2
  STATE_OK=0
  # Folded into the pid list, not only reported above. The summary line is what a
  # human skims and what the dashboard surfaces verbatim, and left alone it read
  # "worker pids=none" — "nothing was running" — while stderr said the opposite.
  LIVE_PIDS="$(printf '%s\n' "$STILL_LIVE" | awk '{printf "%s%s", sep, $1; sep=","}')"
  WORKER_PIDS="${WORKER_PIDS:+$WORKER_PIDS,}$LIVE_PIDS (unmatched)"
fi

if [ "$STATE_OK" = "1" ] && [ -z "$WORKER_PIDS" ]; then
  echo "stopped: task $TASK_ID (reclaimed + blocked; worker and verified grandchild killed)"
else
  echo "NOT STOPPED: task $TASK_ID state=${TASK_STATE:-unknown}, worker pids=${WORKER_PIDS:-none} — re-run zam-stop.sh" >&2
  exit 1
fi
