#!/usr/bin/env bash
# Refuse to complete a loop task whose loop never ran.
#
# The loop-runner skill tells the worker to run run-loop.sh and not to drive
# the coding tools itself. A worker ignored that: it edited files with its own
# terminal tool, called kanban_complete, and opened a pull request that deleted
# a block of security headers. No plan, review, repair, or verify stage ever
# ran, and Hermes recorded the task as done. Instructions alone do not hold, so
# completion is gated on evidence instead.
#
# Evidence is the run marker run-loop.sh and ristretto.runner write into the
# worktree before doing anything else. It is written directly, not through the
# best-effort event emitter, so telemetry failing cannot block a real run.
#
# Fails open on anything it cannot determine — an unreadable board or a task
# that is not a loop task must never wedge an otherwise healthy worker.
set -u

payload="$(cat -)"

allow() { printf '{}\n'; exit 0; }
block() {
  RIS_MSG="$1" python3 -c 'import json,os; print(json.dumps({"action":"block","message":os.environ["RIS_MSG"]}))'
  exit 0
}

field() {
  RIS_PAYLOAD="$payload" python3 - "$1" <<'PY' 2>/dev/null || true
import json, os, sys
try:
    data = json.loads(os.environ["RIS_PAYLOAD"])
except Exception:
    sys.exit(0)
node = data
for part in sys.argv[1].split("."):
    if not isinstance(node, dict):
        sys.exit(0)
    node = node.get(part)
print(node if isinstance(node, str) else "")
PY
}

task="$(field tool_input.task_id)"
[ -n "$task" ] || task="$(field extra.task_id)"
[ -n "$task" ] || allow
case "$task" in
  *[!A-Za-z0-9._-]*) allow ;;
esac

command -v hermes >/dev/null 2>&1 || allow
body="$(hermes kanban show "$task" 2>/dev/null)" || allow

# Only loop tasks are gated. A task without the loop contract in its body is
# somebody else's work and none of this hook's business.
printf '%s' "$body" | grep -q '^issue:' || allow
printf '%s' "$body" | grep -q '^repo:'  || allow

flow="$(printf '%s' "$body" | sed -n 's/^flow:[[:space:]]*//p' | head -1)"
[ -n "$flow" ] || flow=classic

cwd="$(field cwd)"
[ -n "$cwd" ] || cwd="$PWD"
marker="$cwd/.ristretto/runs/$task"

if [ -d "$marker" ]; then
  allow
fi

block "Refusing to complete ${task}: no run marker at ${marker}, so the ${flow} loop never ran.

The work must go through the loop, not through your own tools. From the worktree root:

  bash ~/.hermes/skills/software-development/loop-runner/scripts/run-loop.sh ${task} <ISSUE_KEY> --flow ${flow}

Wait for it to finish, then complete the task. If you already edited files yourself, revert them first — a loop that never ran has had no plan, no review, no repair, and no verification gate, and its output must not reach a pull request.

If the loop genuinely did run and this marker is missing, block the task and say so rather than completing it."
