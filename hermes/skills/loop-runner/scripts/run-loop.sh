#!/usr/bin/env bash
# run-loop.sh <task_id> <issue_key> [--model tier] [--flow name]
# Legacy positional [model] [flow] arguments remain accepted for queued tasks.
# Owns Guard 4 (via reap.sh) and the S-3 permission pin.
#
# There was a local-model fallback here: when Claude was unavailable (session
# limit / OAuth), the loop re-ran ONCE on the local Ollama coder instead of
# failing. Removed 2026-09-23 with the premise behind it. A degraded run is
# worse than no run when the degradation is a local model writing production
# code unattended, and "unattended" is the whole point of this path. Claude
# being unavailable now fails the task, visibly, and it can be relaunched.
# Run from the task's worktree (the dispatcher sets cwd to the workspace).
set -u

# This script must not detach, and the reason changed on 2026-09-24 without the
# rule changing. Both reasons are worth keeping, because the old one is what
# makes the new arrangement correct.
#
# It used to run in the foreground of a Hermes worker. Detaching there was wrong
# for a reason that is not obvious: Hermes supervises a task by the liveness of
# the worker pid it spawned, and a worker that exits while its task is still
# `running` is recorded as a protocol violation that trips the circuit breaker on
# the FIRST occurrence. Detaching therefore got every run marked crashed about
# two minutes in, however well the flow was going. Heartbeats did not help —
# `heartbeat_worker` is explicitly "orthogonal to the PID check". The conclusion
# written here at the time was that taking the loop out of Hermes' dispatcher
# entirely was the fix, not detaching underneath a supervisor counting pids.
#
# That is what happened. `cuzam/dash/launch.py` spawns this script itself, in its
# own session, with the task claimed and deliberately unassigned so no worker can
# be given it. There is no worker pid being counted any more, so the old hazard
# is gone — and with it the cost the old comment accepted, that the loop died
# whenever the gateway restarted.
#
# It still must not detach, for a different reason: this process IS the run as
# far as every surface is concerned. `cuzam/runs.py` and `scripts/live-runs.sh`
# both identify a classic run by this script's command line and report this pid
# as its runner, and `zam-stop.sh` kills it by a signature built from the same
# argv. A version that forked and returned would leave all three watching a pid
# that had exited: the fleet view would call a working run dead and invite a
# relaunch, and stop would report success having killed a shell that was already
# gone. Staying in the foreground of the session the launcher made is what keeps
# the pid everything watches a pid that is doing the work.

# The loop needs claude, codex and the node toolchain, and it does not get to
# choose who launches it. A run started from the dashboard inherits launchd's
# PATH; one started from cron inherits cron's; one started from a terminal
# inherits a login shell's. Only the last has any of these tools.
#
# claude in particular is a node global installed through fnm, and fnm gives
# each shell a per-session bin directory that no daemon will ever have. The
# alias directory is the stable one. Resolving here rather than trusting the
# ambient PATH is the difference between "works when I run it" and "works".
#
# The first dashboard launch died on exactly this, with
# "[Errno 2] No such file or directory: 'claude'" one second in.
#
# Appended, never prepended: this repairs a PATH that is missing tools, and
# must not outrank one a caller chose deliberately. Prepending shadowed the
# test suite's stub claude with the real binary, which is the same mistake in
# miniature — silently overriding an environment someone set on purpose.
for _dir in \
  "${FNM_DIR:-$HOME/.local/share/fnm}/aliases/default/bin" \
  "$HOME/.local/bin" \
  /opt/homebrew/bin \
  /usr/local/bin
do
  [ -d "$_dir" ] || continue
  case ":$PATH:" in
    *":$_dir:"*) ;;
    *) PATH="$PATH:$_dir" ;;
  esac
done
export PATH
unset _dir

TASK_ID="${1:?usage: run-loop.sh <task_id> <issue_key> [--model tier] [--flow name]}"
ISSUE_KEY="${2:?usage: run-loop.sh <task_id> <issue_key> [--model tier] [--flow name]}"
shift 2
# Optional model tier (S-sized tasks run on a cheaper tier). Strict allowlist
# — anything else is silently dropped from legacy positional calls and
# rejected from explicit flags. `local` was a member and is not any more: it
# is accepted and DROPPED, on both paths, so the run continues on the Claude
# default. Rejecting it would be worse than useless — a task queued before
# 2026-09-23 still carries `model: local` in its body, SKILL.md passes that
# through as --model, and exiting 2 would block the task rather than run it
# on Claude, which is the entire point of retiring the local coder.
MODEL=""
FLOW="classic"
if [ "${1:-}" = "--model" ] || [ "${1:-}" = "--flow" ]; then
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --model)
        [ "$#" -ge 2 ] || { echo "run-loop: --model requires a value" >&2; exit 2; }
        MODEL="$2"
        shift 2
        ;;
      --flow)
        [ "$#" -ge 2 ] || { echo "run-loop: --flow requires a value" >&2; exit 2; }
        FLOW="$2"
        shift 2
        ;;
      *)
        echo "run-loop: unknown argument: $1" >&2
        exit 2
        ;;
    esac
  done
  if [ "$MODEL" = "local" ]; then
    echo "run-loop: the local tier was retired; running on the Claude default" >&2
    MODEL=""
  fi
  [[ "$MODEL" =~ ^(sonnet|haiku|opus)?$ ]] || {
    echo "run-loop: invalid model tier: $MODEL" >&2
    exit 2
  }
else
  MODEL="${1:-}"
  FLOW="${2:-classic}"
  [[ "$MODEL" =~ ^(sonnet|haiku|opus)$ ]] || MODEL=""
fi
# `classic` preserves the existing whole /loop-dev behavior. Other names are
# resolved and validated by the public Cuzam flow configuration.
[[ "$FLOW" =~ ^[a-z][a-z0-9-]*$ ]] || {
  echo "run-loop: invalid flow name: $FLOW" >&2
  exit 2
}

BOARD="${HERMES_KANBAN_BOARD:-default}"
if [[ ! "$TASK_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "run-loop: task id contains unsafe characters" >&2
  exit 2
fi
if [[ ! "$BOARD" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "run-loop: board id contains unsafe characters" >&2
  exit 2
fi
PID_DIR="$HOME/.hermes/kanban/$BOARD/pids"
REC="$PID_DIR/$TASK_ID.json"
# -P resolves the skill symlink. The installed skill lives at
# ~/.hermes/skills/software-development/loop-runner but is a link into this
# repository, and `cd ..` without -P walks the *logical* path, landing in
# ~/.hermes instead of the repo — where the cuzam package is not.
SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SESSION_FILE="$PWD/.cc-zam-session"
RESUME_FAILURE_WINDOW="${ZAM_RESUME_FAILURE_WINDOW:-30}"
[[ "$RESUME_FAILURE_WINDOW" =~ ^[0-9]+$ ]] || RESUME_FAILURE_WINDOW=30

# Guard 4: reap a verified orphan from a previous run (no-op otherwise).
bash "$SCRIPT_DIR/reap.sh" "$TASK_ID"

# Run marker. Written before anything else and directly, not through the
# best-effort event emitter: the completion guard reads this to tell a real
# loop from a worker that decided to do the work itself, and telemetry being
# unavailable must never look like a loop that never ran.
RUN_MARKER="$PWD/.cuzam/runs/$TASK_ID"
mkdir -p "$RUN_MARKER" 2>/dev/null && printf '{"task":"%s","issue":"%s","flow":"%s","started":%s}\n' \
  "$TASK_ID" "$ISSUE_KEY" "$FLOW" "$(date +%s)" > "$RUN_MARKER/loop.json" 2>/dev/null || true

CUZAM_ROOT="$(cd -P "$SCRIPT_DIR/../../../.." && pwd -P)"
export PYTHONPATH="$CUZAM_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Pick an interpreter that can actually import cuzam rather than trusting
# whatever `python3` resolves to. A detached worker's PATH is not a developer
# shell's: it finds /usr/bin/python3, which has no PyYAML, so the import fails
# for a missing *dependency* while the package itself is perfectly reachable.
zam_python() {
  local candidate
  # An explicit choice wins outright — no import probe, because overriding
  # is how you pin an interpreter the probe would reject.
  #
  # RIS_PYTHON is still read, for one release. Nothing in this repository
  # sets it — checked, because the rename handoff said launch.py did and it
  # does not; `flow_interpreter` returns an argv prefix, never this variable.
  # It is an operator's override, which means it lives in a shell profile, a
  # launchd plist or a cron entry that no installer can reach, and dropping
  # it on the release would silently stop honouring a pin someone chose.
  # Resolved once into a local, because `set -u` makes testing an unset
  # variable directly an error. Drop in 0.3.0.
  local chosen="${ZAM_PYTHON:-${RIS_PYTHON:-}}"
  if [ -n "$chosen" ] && [ -x "$chosen" ]; then
    printf '%s' "$chosen"
    return 0
  fi
  for candidate in \
    "$CUZAM_ROOT/.venv/bin/python3" \
    "$(command -v cuzam >/dev/null 2>&1 && head -1 "$(command -v cuzam)" | sed 's/^#!//')" \
    "$(command -v python3 || true)"
  do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    if "$candidate" -c "import cuzam.runner" >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

if [ "$FLOW" != "classic" ]; then
  # Fail with the cause rather than a Python traceback: a wrong root or a
  # dependency-less interpreter means every non-classic flow dies before its
  # first stage, and the traceback names the module, not what was wrong.
  ZAM_PY="$(zam_python)" || {
    echo "run-loop: no python3 can import cuzam from $CUZAM_ROOT — flow $FLOW cannot start" >&2
    echo "run-loop: tried the repo venv, the cuzam CLI's interpreter, and python3 on PATH" >&2
    exit 2
  }
  # Keep a copy of the runner's own output. The per-stage logs record what
  # each model said; this records what the harness did around them, which is
  # where the last several failures actually lived.
  LOOP_LOG="$PWD/.cuzam/runs/$TASK_ID/loop.log"
  mkdir -p "$(dirname "$LOOP_LOG")" 2>/dev/null || true
  "$ZAM_PY" -m cuzam.runner \
    --task-id "$TASK_ID" --issue "$ISSUE_KEY" --flow "$FLOW" 2>&1 \
    | tee -a "$LOOP_LOG"
  # tee's exit status is not the runner's, and reporting a failed flow as a
  # success is the one thing this script must never do.
  exit "${PIPESTATUS[0]}"
fi

mkdir -p "$PID_DIR"
OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT

new_session_id() {
  uuidgen | tr '[:upper:]' '[:lower:]'
}

ignore_session_file() {
  local exclude_file
  exclude_file="$(git rev-parse --git-path info/exclude 2>/dev/null)" || return 0
  [ -f "$exclude_file" ] || return 0
  grep -qxF '.cc-zam-session' "$exclude_file" 2>/dev/null || \
    printf '\n# Cuzam resumable Claude session (local runtime state)\n.cc-zam-session\n' >> "$exclude_file"
}

run_once() {  # $1 = fresh|resume — sets RC + RUN_ELAPSED
  local session_mode="${1:-fresh}"
  local flag="$MODEL"
  local -a args=(-p)

  if [ "$session_mode" = "resume" ]; then
    args+=(--resume "$SID")
  else
    args+=(--session-id "$SID")
  fi

  args+=(--permission-mode acceptEdits)
  [ -n "$flag" ] && args+=(--model "$flag")
  if [ "$session_mode" = "resume" ]; then
    args+=("continue: finish the armed dev loop for $ISSUE_KEY")
  else
    args+=("/harness:loop-dev $ISSUE_KEY")
  fi

  : > "$OUT"
  # S-3: permission mode is pinned here and only here. Never add
  # a permission-bypass flag to this invocation.
  # Namespaced form required: bare /loop-dev only resolves in interactive mode.
  local started_at=$SECONDS
  claude "${args[@]}" >"$OUT" 2>&1 &
  CLAUDE_PID=$!
  LSTART="$(ps -p "$CLAUDE_PID" -o lstart= | sed 's/^ *//;s/ *$//')"

  # If child exited before ps could capture lstart, retry once
  if [ -z "$LSTART" ]; then
    sleep 1
    LSTART="$(ps -p "$CLAUDE_PID" -o lstart= | sed 's/^ *//;s/ *$//')"
  fi

  # Guard: don't write a record with empty lstart
  if [ -z "$LSTART" ]; then
    echo "run-loop: child gone before record (pid=$CLAUDE_PID)" >&2
    wait "$CLAUDE_PID"; RC=$?
    RUN_ELAPSED=$((SECONDS - started_at))
    cat "$OUT"
    return 0
  fi

  printf '{"pid": %d, "lstart": "%s", "worktree": "%s", "runner": "claude"}\n' \
    "$CLAUDE_PID" "$LSTART" "$PWD" > "$REC"

  wait "$CLAUDE_PID"; RC=$?
  RUN_ELAPSED=$((SECONDS - started_at))
  rm -f "$REC"
  cat "$OUT"
}

# Pipeline telemetry. Never allowed to fail the loop it is describing: the
# emitter always exits 0, and `|| true` covers a missing interpreter too.
# The installed copy first, the repo copy second: both exist on a normal
# install and either is fine, but neither may break the loop.
ZAM_EVENT="$HOME/.hermes/scripts/zam-event.py"
[ -f "$ZAM_EVENT" ] || ZAM_EVENT="$SCRIPT_DIR/../../../scripts/zam-event.py"
zam_event() {
  [ -f "$ZAM_EVENT" ] || return 0
  # Same interpreter problem as the runner, but silent here: the emitter
  # imports cuzam, and `|| true` would hide a dependency-less python3
  # as an event that simply never appeared.
  [ -n "${ZAM_PY:-}" ] || ZAM_PY="$(zam_python || command -v python3)"
  "$ZAM_PY" "$ZAM_EVENT" "$TASK_ID" "$1" \
    --issue "$ISSUE_KEY" --project "$(basename "$PWD")" "${@:2}" >/dev/null 2>&1 || true
}

zam_event run.started --payload "{\"flow\":\"classic\",\"model\":\"${MODEL:-default}\"}"

finish() {  # $1 = outcome
  zam_event run.ended --payload "{\"outcome\":\"$1\",\"runtime\":\"$2\"}"
}

ignore_session_file
if [ -s "$SESSION_FILE" ]; then
  SID="$(tr -d '[:space:]' < "$SESSION_FILE")"
  run_once resume
  if [ "$RC" -ne 0 ] && [ "$RUN_ELAPSED" -le "$RESUME_FAILURE_WINDOW" ]; then
    echo "run-loop: resume failed quickly (rc=$RC, ${RUN_ELAPSED}s) — starting a fresh cloud session" >&2
    SID="$(new_session_id)"
    printf '%s\n' "$SID" > "$SESSION_FILE"
    run_once fresh
  fi
else
  SID="$(new_session_id)"
  printf '%s\n' "$SID" > "$SESSION_FILE"
  run_once fresh
fi

RUNTIME=cloud
# Claude being unavailable is reported as what it is. It used to re-run on a
# local coder here; see the header.
if [ "$RC" -ne 0 ] && \
   grep -qiE "session limit|oauth|failed to authenticate|credit balance" "$OUT"; then
  echo "run-loop: claude unavailable (rc=$RC) — the run failed; relaunch when it is back" >&2
  zam_event stage.failed --stage cloud \
    --payload "{\"reason\":\"claude unavailable (rc=$RC)\"}"
fi
[ "$RC" -eq 0 ] && rm -f "$SESSION_FILE"
[ "$RC" -eq 0 ] && finish completed "$RUNTIME" || finish failed "$RUNTIME"

# Tell the board how it went, here rather than from the worker. Reporting
# from the process that knows the outcome is what moves the task out of
# `running` before the worker exits, which is what stops Hermes recording a
# finished run as a protocol violation.
PR_URL="$(gh pr list --head "$(git branch --show-current 2>/dev/null)" \
  --json url --jq '.[0].url' 2>/dev/null)"
if [ "$RC" -eq 0 ] && [ -n "$PR_URL" ] && [ "$PR_URL" != "null" ]; then
  hermes kanban complete "$TASK_ID" --result "$ISSUE_KEY: PR ready" \
    --metadata "{\"pr\": \"$PR_URL\"}" >/dev/null 2>&1 || true
  zam_event pr.opened --payload "{\"url\":\"$PR_URL\"}"
elif [ "$RC" -eq 0 ]; then
  hermes kanban block "$TASK_ID" \
    "$ISSUE_KEY: loop exited 0 but opened no pull request" >/dev/null 2>&1 || true
else
  hermes kanban block "$TASK_ID" "$ISSUE_KEY: loop failed (rc=$RC)" >/dev/null 2>&1 || true
fi
exit "$RC"
