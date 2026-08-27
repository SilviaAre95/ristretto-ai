#!/usr/bin/env bash
# Tests for loop-flow-guard.sh: a loop task may only be completed by a loop.
#
# The case that motivated this: a worker ignored the skill, edited files with
# its own tools, called kanban_complete, and opened a pull request that dropped
# a block of security headers. Nothing noticed.
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUARD="$ROOT/agent-hooks/loop-flow-guard.sh"

FAKEBIN="$(mktemp -d)"
BODY="$FAKEBIN/body.txt"
cat > "$FAKEBIN/hermes" <<EOF
#!/usr/bin/env bash
# Stub: 'kanban show <id>' prints the canned body, unknown ids fail.
[ "\$1" = "kanban" ] && [ "\$2" = "show" ] || exit 1
[ "\$3" = "t_known" ] || exit 1
cat "$BODY"
EOF
chmod +x "$FAKEBIN/hermes"
export PATH="$FAKEBIN:$PATH"

loop_body() {
  cat > "$BODY" <<EOF
Task t_known: XARI-1 · loop-dev
  status: running

Body:
issue: XARI-1
repo: /repos/example
branch: feature/x
flow: ${1:-classic}
EOF
}

run_guard() {  # $1 = task id, $2 = cwd
  printf '{"hook_event_name":"pre_tool_call","tool_name":"kanban_complete","tool_input":{"task_id":"%s"},"cwd":"%s","extra":{}}' "$1" "$2" | bash "$GUARD"
}

blocked() { printf '%s' "$1" | grep -q '"action": *"block"'; }

# --- a loop task with no marker is refused -----------------------------------
loop_body tier0
WT="$(mktemp -d)"
OUT="$(run_guard t_known "$WT")"
t "no run marker: completion is refused"      "blocked '$OUT'"
t "no run marker: names the flow that skipped" "printf '%s' '$OUT' | grep -q tier0"
t "no run marker: tells the worker what to run" "printf '%s' '$OUT' | grep -q run-loop.sh"
t "no run marker: says to revert its own edits" "printf '%s' '$OUT' | grep -q revert"

# --- the marker a real loop leaves behind is accepted -------------------------
mkdir -p "$WT/.ristretto/runs/t_known"
echo '{}' > "$WT/.ristretto/runs/t_known/loop.json"
OUT="$(run_guard t_known "$WT")"
t "run marker present: completion is allowed"  "! blocked '$OUT'"

# --- a marker for a different task does not count ----------------------------
WT2="$(mktemp -d)"; mkdir -p "$WT2/.ristretto/runs/t_other"
OUT="$(run_guard t_known "$WT2")"
t "another task's marker does not count"       "blocked '$OUT'"

# --- anything that is not a loop task is none of the guard's business --------
cat > "$BODY" <<'EOF'
Task t_known: write the quarterly summary
  status: running

Body:
Draft the summary and post it.
EOF
WT3="$(mktemp -d)"
OUT="$(run_guard t_known "$WT3")"
t "non-loop task is not gated"                 "! blocked '$OUT'"

# --- fail open, always -------------------------------------------------------
loop_body tier3
OUT="$(run_guard t_unknown "$WT3")"
t "unreadable board fails open"                "! blocked '$OUT'"
OUT="$(printf '{"tool_name":"kanban_complete","tool_input":{},"extra":{}}' | bash "$GUARD")"
t "missing task id fails open"                 "! blocked '$OUT'"
OUT="$(printf 'not json at all' | bash "$GUARD")"
t "malformed payload fails open"               "! blocked '$OUT'"

# --- a hostile id never reaches a subprocess ---------------------------------
CANARY="$FAKEBIN/pwned"
OUT="$(printf '{"tool_name":"kanban_complete","tool_input":{"task_id":"$(touch %s)"},"extra":{}}' "$CANARY" | bash "$GUARD")"
t "hostile task id has no side effect"         "[ ! -e '$CANARY' ]"
t "hostile task id fails open"                 "! blocked '$OUT'"

# --- the guard always emits valid JSON ---------------------------------------
loop_body tier0
OUT="$(run_guard t_known "$(mktemp -d)")"
t "block output is valid JSON"                 "printf '%s' '$OUT' | python3 -m json.tool >/dev/null"

echo
echo "flow-guard.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
