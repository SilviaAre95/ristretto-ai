#!/usr/bin/env bash
# Tests for reap.sh (Guard 4 / S-1). Self-contained; uses a temp HOME.
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/skills/loop-runner/scripts/reap.sh"
export HOME="$(mktemp -d)"
export HERMES_KANBAN_BOARD=testboard
PID_DIR="$HOME/.hermes/kanban/testboard/pids"
mkdir -p "$PID_DIR"

rec() { # rec <task> <pid> <lstart> <worktree> [runner]
  printf '{"pid": %d, "lstart": "%s", "worktree": "%s", "runner": "%s"}\n' \
    "$2" "$3" "$4" "${5:-claude}" > "$PID_DIR/$1.json"
}
lstart_of() { ps -p "$1" -o lstart= | sed 's/^ *//;s/ *$//'; }

# 1. No record → exit 0, no-op
"$SCRIPT" t-none; t "no record is a no-op (exit 0)" "[ $? -eq 0 ]"

# 2. Record with dead PID → record removed, nothing killed
rec t-dead 999999 "Wed Jan  1 00:00:00 2020" "/nope"
"$SCRIPT" t-dead
t "dead pid: record removed" "[ ! -f '$PID_DIR/t-dead.json' ]"

# 3. MISMATCH (S-1): record names a live but unrelated process → NOT killed
sleep 300 & SLEEP_PID=$!
rec t-mismatch "$SLEEP_PID" "$(lstart_of "$SLEEP_PID")" "$PWD"
"$SCRIPT" t-mismatch 2>/dev/null
t "mismatch: unrelated live process NOT killed" "kill -0 $SLEEP_PID 2>/dev/null"
t "mismatch: record removed" "[ ! -f '$PID_DIR/t-mismatch.json' ]"
kill "$SLEEP_PID" 2>/dev/null

# 4. MATCH: process named claude, in recorded cwd, matching lstart → killed
FAKEBIN="$(mktemp -d)"; WT="$(mktemp -d)"
printf '#!/usr/bin/env bash\nsleep 300\n' > "$FAKEBIN/claude"; chmod +x "$FAKEBIN/claude"
( cd "$WT"; "$FAKEBIN/claude" & echo $! > "$WT/.pid" )
CPID="$(cat "$WT/.pid")"; sleep 1
rec t-match "$CPID" "$(lstart_of "$CPID")" "$WT"
"$SCRIPT" t-match
sleep 1
t "match: claude orphan killed" "! kill -0 $CPID 2>/dev/null"
t "match: record removed" "[ ! -f '$PID_DIR/t-match.json' ]"

# 5. MATCH: a recorded Codex runner is also reaped under the same identity checks.
WT_CODEX="$(mktemp -d)"
printf '#!/usr/bin/env bash\nsleep 300\n' > "$FAKEBIN/codex"; chmod +x "$FAKEBIN/codex"
( cd "$WT_CODEX"; "$FAKEBIN/codex" exec & echo $! > "$WT_CODEX/.pid" )
CODEX_PID="$(cat "$WT_CODEX/.pid")"; sleep 1
rec t-codex "$CODEX_PID" "$(lstart_of "$CODEX_PID")" "$WT_CODEX" codex
"$SCRIPT" t-codex
sleep 1
t "match: codex orphan killed" "! kill -0 $CODEX_PID 2>/dev/null"
t "match: codex record removed" "[ ! -f '$PID_DIR/t-codex.json' ]"

# 6. Stale lstart (PID reuse simulation) → NOT killed
sleep 300 & SLEEP2=$!
rec t-reuse "$SLEEP2" "Wed Jan  1 00:00:00 2020" "$PWD"
"$SCRIPT" t-reuse 2>/dev/null
t "lstart mismatch (pid reuse): NOT killed" "kill -0 $SLEEP2 2>/dev/null"
kill "$SLEEP2" 2>/dev/null

# 7. A runner name appearing only as a substring must not pass Guard 4.
WT_LEGACY="$(mktemp -d)"
printf '#!/usr/bin/env bash\nsleep 300\n' > "$FAKEBIN/claude-legacy"; chmod +x "$FAKEBIN/claude-legacy"
( cd "$WT_LEGACY"; "$FAKEBIN/claude-legacy" & echo $! > "$WT_LEGACY/.pid" )
LEGACY_PID="$(cat "$WT_LEGACY/.pid")"; sleep 1
rec t-legacy "$LEGACY_PID" "$(lstart_of "$LEGACY_PID")" "$WT_LEGACY" claude
"$SCRIPT" t-legacy 2>/dev/null
t "runner substring mismatch: NOT killed" "kill -0 $LEGACY_PID 2>/dev/null"
kill "$LEGACY_PID" 2>/dev/null

# 8. Identifiers are validated before they are used in paths.
"$SCRIPT" '../../unsafe' >/dev/null 2>&1
t "unsafe task id is rejected" "[ $? -eq 2 ]"
HERMES_KANBAN_BOARD='../unsafe' "$SCRIPT" t-board >/dev/null 2>&1
t "unsafe board id is rejected" "[ $? -eq 2 ]"

echo; echo "reap.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
