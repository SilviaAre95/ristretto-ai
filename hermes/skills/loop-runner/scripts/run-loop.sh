#!/usr/bin/env bash
# run-loop.sh <task_id> <issue_key> [--model tier] [--flow name]
# Legacy positional [model] [flow] arguments remain accepted for queued tasks.
# Owns Guard 4 (via reap.sh), the S-3 permission pin, and the local-model
# fallback: when Claude itself is unavailable (session limit / OAuth), the
# loop re-runs ONCE on the local Ollama coder model instead of failing.
# Run from the task's worktree (the dispatcher sets cwd to the workspace).
set -u
TASK_ID="${1:?usage: run-loop.sh <task_id> <issue_key> [--model tier] [--flow name]}"
ISSUE_KEY="${2:?usage: run-loop.sh <task_id> <issue_key> [--model tier] [--flow name]}"
shift 2
# Optional model tier (S-sized tasks run on a cheaper tier; `local` runs the
# whole loop on Ollama). Strict allowlist — anything else is silently
# dropped from legacy positional calls and rejected from explicit flags.
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
  [[ "$MODEL" =~ ^(sonnet|haiku|opus|local)?$ ]] || {
    echo "run-loop: invalid model tier: $MODEL" >&2
    exit 2
  }
else
  MODEL="${1:-}"
  FLOW="${2:-classic}"
  [[ "$MODEL" =~ ^(sonnet|haiku|opus|local)$ ]] || MODEL=""
fi
# `classic` preserves the existing whole /loop-dev behavior. Other names are
# resolved and validated by the public Ristretto flow configuration.
[[ "$FLOW" =~ ^[a-z][a-z0-9-]*$ ]] || {
  echo "run-loop: invalid flow name: $FLOW" >&2
  exit 2
}

# Local brain: which Ollama model runs the loop for `model: local` AND for
# the claude-unavailable fallback. Configure per machine in ~/.hermes/.env
# (RIS_LOCAL_LOOP_MODEL). Requires Ollama >= 0.14 (Anthropic-compatible API)
# and a >= 64k context window.
LOCAL_MODEL="${RIS_LOCAL_LOOP_MODEL:-qwen3.6:27b-coding-nvfp4}"
# Auto-fallback to the local model on Claude auth/limit failures (default
# on). RIS_LOCAL_FALLBACK=0 disables — the task then just fails and blocks.
FALLBACK="${RIS_LOCAL_FALLBACK:-1}"

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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_FILE="$PWD/.cc-ris-session"
RESUME_FAILURE_WINDOW="${RIS_RESUME_FAILURE_WINDOW:-30}"
[[ "$RESUME_FAILURE_WINDOW" =~ ^[0-9]+$ ]] || RESUME_FAILURE_WINDOW=30

# Guard 4: reap a verified orphan from a previous run (no-op otherwise).
bash "$SCRIPT_DIR/reap.sh" "$TASK_ID"

if [ "$FLOW" != "classic" ]; then
  RISTRETTO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
  export PYTHONPATH="$RISTRETTO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
  exec python3 -m ristretto.runner \
    --task-id "$TASK_ID" --issue "$ISSUE_KEY" --flow "$FLOW"
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
  grep -qxF '.cc-ris-session' "$exclude_file" 2>/dev/null || \
    printf '\n# Ristretto resumable Claude session (local runtime state)\n.cc-ris-session\n' >> "$exclude_file"
}

run_once() {  # $1 = cloud|local, $2 = fresh|resume — sets RC + RUN_ELAPSED
  local runtime="$1"
  local session_mode="${2:-fresh}"
  local flag="$MODEL"
  local -a args=(-p)

  if [ "$runtime" = "local" ]; then
    export ANTHROPIC_BASE_URL="http://localhost:11434"
    export ANTHROPIC_AUTH_TOKEN="ollama"
    flag="$LOCAL_MODEL"
  elif [ "$session_mode" = "resume" ]; then
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

if [ "$MODEL" = "local" ]; then
  MODEL=""  # run_once local supplies LOCAL_MODEL as the flag
  run_once local fresh
  [ "$RC" -eq 0 ] && rm -f "$SESSION_FILE"
  exit "$RC"
fi

ignore_session_file
if [ -s "$SESSION_FILE" ]; then
  SID="$(tr -d '[:space:]' < "$SESSION_FILE")"
  run_once cloud resume
  if [ "$RC" -ne 0 ] && [ "$RUN_ELAPSED" -le "$RESUME_FAILURE_WINDOW" ]; then
    echo "run-loop: resume failed quickly (rc=$RC, ${RUN_ELAPSED}s) — starting a fresh cloud session" >&2
    SID="$(new_session_id)"
    printf '%s\n' "$SID" > "$SESSION_FILE"
    run_once cloud fresh
  fi
else
  SID="$(new_session_id)"
  printf '%s\n' "$SID" > "$SESSION_FILE"
  run_once cloud fresh
fi

if [ "$RC" -ne 0 ] && [ "$FALLBACK" = "1" ] && \
   grep -qiE "session limit|oauth|failed to authenticate|credit balance" "$OUT"; then
  echo "run-loop: claude unavailable (rc=$RC) — falling back to local model $LOCAL_MODEL" >&2
  run_once local fresh
fi
[ "$RC" -eq 0 ] && rm -f "$SESSION_FILE"
exit "$RC"
