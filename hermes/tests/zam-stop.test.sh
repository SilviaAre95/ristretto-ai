#!/usr/bin/env bash
# Tests for zam-stop.sh (S-5 kill switch). Self-contained; uses a temp HOME
# and stubbed hermes/pkill/pgrep. A local Hermes installation is checked when
# present, but is not required for contributors or CI.
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/zam-stop.sh"

# 1. The reap.sh path hardcoded in the script must resolve on this machine
#    (catches drift between the script and the ~/.hermes symlink layout).
REAP_REF="$(sed -n 's/.*bash "\(\$HOME[^"]*reap\.sh\)".*/\1/p' "$SCRIPT")"
t "script references a reap.sh path" "[ -n '$REAP_REF' ]"
if [ -f "$(eval echo "$REAP_REF")" ]; then
  t "referenced reap.sh exists under real HOME" "true"
else
  echo "ok  - referenced reap.sh exists under real HOME # SKIP Hermes not installed"
  PASS=$((PASS+1))
fi

# Sandbox: temp HOME with a stub reap.sh at the same relative path, and
# stub hermes/pkill/pgrep ahead of the real ones in PATH.
REAL_HOME="$HOME"
export HOME="$(mktemp -d)"
FAKEBIN="$(mktemp -d)"
export PATH="$FAKEBIN:$PATH"

REAP_STUB="$HOME${REAP_REF#\$HOME}"
mkdir -p "$(dirname "$REAP_STUB")"
printf '#!/usr/bin/env bash\necho "$1" > "%s/reap-called"\n' "$HOME" > "$REAP_STUB"

cat > "$FAKEBIN/hermes" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-} ${2:-}" = "kanban show" ]; then
  printf '{"task": {"status": "%s"}}\n' "${ZAM_TEST_STATUS:-blocked}"
fi
exit 0
EOF
printf '#!/usr/bin/env bash\nexit 1\n' > "$FAKEBIN/pkill"
printf '#!/usr/bin/env bash\nexit 1\n' > "$FAKEBIN/pgrep"
chmod +x "$REAP_STUB" "$FAKEBIN/hermes" "$FAKEBIN/pkill" "$FAKEBIN/pgrep"

# 2. Missing task id → usage error, non-zero exit
bash "$SCRIPT" >/dev/null 2>&1
t "missing task id exits non-zero" "[ $? -ne 0 ]"

bash "$SCRIPT" '../../unsafe' >/dev/null 2>&1
t "unsafe task id is rejected" "[ $? -eq 2 ]"

# 3. Clean stop: task blocked, no workers left → exit 0, reap called with the id
bash "$SCRIPT" t-clean > "$HOME/out" 2>&1
RC=$?
t "clean stop exits 0" "[ $RC -eq 0 ]"
t "clean stop reports stopped" "grep -q '^stopped: task t-clean' '$HOME/out'"
t "reap.sh called with the task id (Guard 4 not silently skipped)" \
  "[ -f '$HOME/reap-called' ] && grep -qx t-clean '$HOME/reap-called'"

# 4. Verification pass: task still in_progress after the stop → NOT STOPPED, exit 1
rm -f "$HOME/reap-called"
ZAM_TEST_STATUS=in_progress bash "$SCRIPT" t-live > "$HOME/out" 2>&1
RC=$?
t "unblocked task exits non-zero" "[ $RC -ne 0 ]"
t "unblocked task reports NOT STOPPED" "grep -q 'NOT STOPPED: task t-live' '$HOME/out'"

# 5. Archived counts as stopped (dispatcher can't pick it up again)
ZAM_TEST_STATUS=archived bash "$SCRIPT" t-arch > "$HOME/out" 2>&1
t "archived task counts as stopped" "[ $? -eq 0 ]"

# 6. Every run shape has a signature — checked against real processes.
#
#    The cases above stub pkill and pgrep to "nothing matched", so they cannot
#    tell a signature that works from one that cannot match anything. That gap
#    is how a shape gets added to the launcher and never to the kill switch: the
#    stop then kills nothing, passes its own verification (the task is blocked
#    because stage 1 blocked it, and no pid matches a pattern that cannot match)
#    and reports success while the run carries on to `finish` and pushes.
#
#    So: spawn the real shape, run the real pkill, and require it to die. The
#    task ids carry $$ so the patterns cannot reach another run on this machine.
rm -f "$FAKEBIN/pkill" "$FAKEBIN/pgrep"

SHAPE_DIR="$(mktemp -d)"
mkdir -p "$SHAPE_DIR/loop-runner/scripts"
printf '#!/usr/bin/env bash\nsleep 120\n' > "$SHAPE_DIR/loop-runner/scripts/run-loop.sh"
printf '#!/usr/bin/env bash\nsleep 120\n' > "$SHAPE_DIR/stage-runner.sh"
chmod +x "$SHAPE_DIR/loop-runner/scripts/run-loop.sh" "$SHAPE_DIR/stage-runner.sh"

# The classic shape, exactly as cuzam/dash/launch.py spawns it.
CLASSIC_TID="t-classic-$$"
bash "$SHAPE_DIR/loop-runner/scripts/run-loop.sh" "$CLASSIC_TID" XARI-1 --flow classic &
CLASSIC_PID=$!
# The staged shape. The signature matches on the words `cuzam.runner
# --task-id <id>` appearing on the command line, so the stub carries them as
# real arguments rather than faking an argv[0], which `ps` does not report
# the same way on every platform.
STAGED_TID="t-staged-$$"
bash "$SHAPE_DIR/stage-runner.sh" -m cuzam.runner \
  --task-id "$STAGED_TID" --issue XARI-1 --flow full &
STAGED_PID=$!
sleep 1

t "a launched classic run is on the process table to begin with" \
  "kill -0 $CLASSIC_PID 2>/dev/null"
t "a launched staged run is on the process table to begin with" \
  "kill -0 $STAGED_PID 2>/dev/null"

bash "$SCRIPT" "$CLASSIC_TID" > "$HOME/out-classic" 2>&1
CLASSIC_RC=$?
bash "$SCRIPT" "$STAGED_TID" > "$HOME/out-staged" 2>&1
STAGED_RC=$?
sleep 1

t "stopping a classic run actually kills it" "! kill -0 $CLASSIC_PID 2>/dev/null"
t "stopping a staged run actually kills it" "! kill -0 $STAGED_PID 2>/dev/null"
t "a classic stop that worked reports stopped" \
  "[ $CLASSIC_RC -eq 0 ] && grep -q '^stopped: task $CLASSIC_TID' '$HOME/out-classic'"
t "a staged stop that worked reports stopped" \
  "[ $STAGED_RC -eq 0 ] && grep -q '^stopped: task $STAGED_TID' '$HOME/out-staged'"

kill -KILL "$CLASSIC_PID" "$STAGED_PID" 2>/dev/null
wait "$CLASSIC_PID" "$STAGED_PID" 2>/dev/null

# 7. A live shape the kill signatures do NOT know must not report success.
#
#    Every check in section 6 is built from patterns in zam-stop.sh itself, so it
#    cannot tell "no pid matched because the run is dead" from "no pid matched
#    because the pattern was wrong". The second reads exactly like success — and
#    it is what this file looked like for the staged runner, and again for the
#    classic loop once nothing was above it. So the verification also asks
#    live-runs.sh, the standalone answer to what a live run is.
#
#    The fixture is a shape live-runs.sh recognises: a console-script run, which
#    carries no `-m` and therefore matches none of zam-stop's three patterns.
# Path taken from the script rather than written out here, the same way the
# reap.sh stub is, so the test cannot drift from what zam-stop.sh actually reads.
LIVE_REF="$(sed -n 's/^LIVE_RUNS="\(\$HOME[^"]*\)"$/\1/p' "$SCRIPT")"
t "script references a live-runs.sh path" "[ -n '$LIVE_REF' ]"
LIVE_STUB="$HOME${LIVE_REF#\$HOME}"
mkdir -p "$(dirname "$LIVE_STUB")"
install -m 0755 "$(cd "$(dirname "$0")/../.." && pwd)/scripts/live-runs.sh" "$LIVE_STUB"

UNKNOWN_TID="t_unknown$$"
bash -c "exec -a 'cuzam-run-flow --task-id $UNKNOWN_TID --issue XARI-1 --flow full' \
         sleep 300" &
UNKNOWN_PID=$!
sleep 1

t "the unknown shape is live to live-runs.sh" \
  "bash '$LIVE_STUB' | grep -qF '$UNKNOWN_TID'"

bash "$SCRIPT" "$UNKNOWN_TID" > "$HOME/out-unknown" 2>&1
UNKNOWN_RC=$?

t "a live run no signature matches is NOT reported as stopped" \
  "[ $UNKNOWN_RC -ne 0 ] && grep -q 'NOT STOPPED' '$HOME/out-unknown'"
t "and it says which process it could not kill" \
  "grep -q 'still live and matched no kill signature' '$HOME/out-unknown'"

kill -KILL "$UNKNOWN_PID" 2>/dev/null
wait "$UNKNOWN_PID" 2>/dev/null
rm -f "$LIVE_STUB"

# An install predating live-runs.sh must still be able to report a clean stop.
bash "$SCRIPT" t-clean > "$HOME/out-nolive" 2>&1
t "without live-runs.sh the verification is unchanged" \
  "[ $? -eq 0 ] && grep -q '^stopped: task t-clean' '$HOME/out-nolive'"

rm -rf "$SHAPE_DIR"

rm -rf "$HOME" "$FAKEBIN"
HOME="$REAL_HOME"

echo; echo "zam-stop.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
