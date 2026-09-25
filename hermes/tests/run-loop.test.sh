#!/usr/bin/env bash
# Tests for run-loop.sh: pid record lifecycle, permission pin, exit code.
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
SCRIPT="$ROOT/skills/loop-runner/scripts/run-loop.sh"
export HOME="$(mktemp -d)"
export HERMES_KANBAN_BOARD=testboard
# The loop runs in the foreground in production too, so these tests exercise
# it exactly as Hermes does: launch it, wait, read the exit status.
PID_DIR="$HOME/.hermes/kanban/testboard/pids"

# Stub claude: records its argv, proves the record exists while running, exits 7
FAKEBIN="$(mktemp -d)"
FB_STDERR="$FAKEBIN/fb-stderr.txt"
RUN_LOOP_STDERR="$FAKEBIN/run-loop-stderr.txt"
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/argv"
echo "\${ANTHROPIC_BASE_URL:-none}" > "$FAKEBIN/baseurl"
sleep 2
[ -f "$PID_DIR/t-run.json" ] && echo yes > "$FAKEBIN/record_existed"
[ -s ".cc-zam-session" ] && cp ".cc-zam-session" "$FAKEBIN/session_during_run"
exit 7
EOF
chmod +x "$FAKEBIN/claude"
export PATH="$FAKEBIN:$PATH"

WT="$(mktemp -d)"; cd "$WT"
"$SCRIPT" t-run PROJ-00; RC=$?

t "exit code propagated (7)"        "[ $RC -eq 7 ]"
t "record existed during run"       "[ -f '$FAKEBIN/record_existed' ]"
t "record removed after exit"       "[ ! -f '$PID_DIR/t-run.json' ]"
t "permission mode pinned"          "grep -q -- '--permission-mode acceptEdits' '$FAKEBIN/argv'"
t "issue key passed to /loop-dev"   "grep -q '/harness:loop-dev PROJ-00' '$FAKEBIN/argv'"
t "fresh run gets a session id"     "grep -q -- '--session-id' '$FAKEBIN/argv'"
t "session file exists during run"  "[ -s '$FAKEBIN/session_during_run' ]"
t "failed run keeps session id"     "[ -s '$WT/.cc-zam-session' ]"
t "no dangerous flag anywhere"      "! grep -rq 'dangerously-skip-permissions' '$ROOT/skills'"
t "no --model flag without arg"     "! grep -q -- '--model' '$FAKEBIN/argv'"

# Model tier: valid tier is passed through, junk is dropped (allowlist)
WT_M="$(mktemp -d)"; cd "$WT_M"
"$SCRIPT" t-model PROJ-02 sonnet >/dev/null 2>&1
t "valid model appended"            "grep -q -- '--model sonnet' '$FAKEBIN/argv'"
t "cloud tier: no base_url export"  "grep -q '^none$' '$FAKEBIN/baseurl'"
rm -f "$WT_M/.cc-zam-session"
"$SCRIPT" t-model2 PROJ-03 'opus; rm -rf /' >/dev/null 2>&1
t "junk model dropped (allowlist)"  "! grep -q -- '--model' '$FAKEBIN/argv'"

# The `local` tier is gone. A queued task still carrying it must drop to the
# default rather than route a build to a local coder.
"$SCRIPT" t-local PROJ-04 local >/dev/null 2>&1
t "local tier: dropped, not honoured" "! grep -q -- '--model' '$FAKEBIN/argv'"
t "local tier: no ollama base_url"    "grep -q '^none$' '$FAKEBIN/baseurl'"
t "local tier: still a cloud session" "grep -qE -- '--session-id|--resume' '$FAKEBIN/argv'"
RIS_LOCAL_LOOP_MODEL="qwen3-coder-next:q4_K_M" "$SCRIPT" t-local2 PROJ-05 >/dev/null 2>&1
t "loop model env is inert"           "! grep -q -- '--model' '$FAKEBIN/argv'"
# A task queued before the tiers were retired still carries `model: local`,
# and SKILL.md passes it through as --model. Blocking it would strand the
# task; it must run on the Claude default instead.
"$SCRIPT" t-local3 PROJ-05 --model local >/dev/null 2>"$FAKEBIN/local_stderr"; RC=$?
# Not exit 2: that is the allowlist rejection, which would strand the task.
# The fake claude in this section fails on purpose, so 0 is not the check.
t "queued --model local: not rejected" "[ $RC -ne 2 ]"
t "queued --model local: dropped"      "! grep -q -- '--model' '$FAKEBIN/argv'"
t "queued --model local: says so"      "grep -q 'local tier was retired' '$FAKEBIN/local_stderr'"
t "queued --model local: stays cloud"  "grep -q '^none$' '$FAKEBIN/baseurl'"

# Resume-first cloud path: reuse the worktree session and clear it on success.
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/argv"
exit 0
EOF
chmod +x "$FAKEBIN/claude"
WT_R="$(mktemp -d)"; cd "$WT_R"
printf '%s\n' '11111111-1111-1111-1111-111111111111' > .cc-zam-session
"$SCRIPT" t-resume PROJ-09 >/dev/null 2>&1; RC=$?
t "resume: succeeds"                 "[ $RC -eq 0 ]"
t "resume: existing id reused"       "grep -q -- '--resume 11111111-1111-1111-1111-111111111111' '$FAKEBIN/argv'"
t "resume: continuation prompt"      "grep -q 'continue: finish the armed dev loop for PROJ-09' '$FAKEBIN/argv'"
t "resume: does not re-invoke skill" "! grep -q '/harness:loop-dev' '$FAKEBIN/argv'"
t "success removes session file"     "[ ! -e '$WT_R/.cc-zam-session' ]"

# A quick resume rejection gets one fresh cloud session with a new id.
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" >> "$FAKEBIN/argv_log"
if [[ " \$* " == *" --resume "* ]]; then exit 1; fi
exit 0
EOF
chmod +x "$FAKEBIN/claude"
rm -f "$FAKEBIN/argv_log"
WT_RF="$(mktemp -d)"; cd "$WT_RF"
printf '%s\n' '22222222-2222-2222-2222-222222222222' > .cc-zam-session
ZAM_RESUME_FAILURE_WINDOW=30 "$SCRIPT" t-resume-fallback PROJ-10 >/dev/null 2>"$FAKEBIN/resume_stderr"; RC=$?
t "resume fallback: fresh succeeds"  "[ $RC -eq 0 ]"
t "resume fallback: two cloud calls" "[ \$(wc -l < '$FAKEBIN/argv_log' | tr -d ' ') -eq 2 ]"
t "resume fallback: resume first"     "sed -n '1p' '$FAKEBIN/argv_log' | grep -q -- '--resume 22222222-2222-2222-2222-222222222222'"
t "resume fallback: fresh second"    "sed -n '2p' '$FAKEBIN/argv_log' | grep -q -- '--session-id'"
t "resume fallback: new id used"     "! sed -n '2p' '$FAKEBIN/argv_log' | grep -q '22222222-2222-2222-2222-222222222222'"
t "resume fallback: announced"       "grep -q 'resume failed quickly' '$FAKEBIN/resume_stderr'"
t "resume fallback: success cleans"  "[ ! -e '$WT_RF/.cc-zam-session' ]"

# Session state is local runtime data and must never be staged into a task PR.
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$FAKEBIN/claude"
WT_G="$(mktemp -d)"
git -C "$WT_G" init -q
cd "$WT_G"
"$SCRIPT" t-ignore PROJ-11 >/dev/null 2>&1
t "session file is git-excluded"     "git check-ignore -q --no-index .cc-zam-session"

# Claude unavailable (auth/limit): the run fails. It used to re-run once on a
# local coder; that fallback was removed 2026-09-23 and its absence is pinned
# here, because a silent local build is exactly what nobody would notice.
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/argv"
echo "\${ANTHROPIC_BASE_URL:-none}" > "$FAKEBIN/baseurl"
if [ -z "\${ANTHROPIC_BASE_URL:-}" ]; then echo "You've hit your session limit"; exit 1; fi
exit 0
EOF
chmod +x "$FAKEBIN/claude"
"$SCRIPT" t-fb PROJ-06 >/dev/null 2>"$FB_STDERR"; RC=$?
t "unavailable: fails, no fallback" "[ $RC -ne 0 ]"
t "unavailable: never goes local"   "grep -q '^none$' '$FAKEBIN/baseurl'"
t "unavailable: no local model"     "! grep -q -- '--model qwen3' '$FAKEBIN/argv'"
t "unavailable: announced on stderr" "grep -q 'claude unavailable' '$FB_STDERR'"

# Non-auth failure must NOT fall back
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/argv"
echo "tests failed"; exit 3
EOF
chmod +x "$FAKEBIN/claude"
"$SCRIPT" t-nofb PROJ-07 >/dev/null 2>&1; RC=$?
t "no fallback on real failure"     "[ $RC -eq 3 ]"
t "no local model on real failure"  "! grep -q -- '--model' '$FAKEBIN/argv'"

# The old opt-out is inert: an auth failure fails through either way.
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/argv"
echo "OAuth session expired"; exit 1
EOF
chmod +x "$FAKEBIN/claude"
RIS_LOCAL_FALLBACK=0 "$SCRIPT" t-fboff PROJ-08 >/dev/null 2>&1; RC=$?
t "auth failure: fails through"      "[ $RC -eq 1 ]"
t "auth failure: stays cloud"        "! grep -q -- '--model' '$FAKEBIN/argv'"

# Non-classic flow: dispatches the validated multi-stage runner and does not
# create legacy Claude session state.
cat > "$FAKEBIN/python3" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/python_argv"
echo "\${PYTHONPATH:-}" > "$FAKEBIN/pythonpath"
exit 0
EOF
chmod +x "$FAKEBIN/python3"
WT_FLOW="$(mktemp -d)"; cd "$WT_FLOW"
# Regression: the installed skill is a symlink into the repo, and resolving
# SCRIPT_DIR logically walked out to HERMES_HOME instead of the repo root, so
# every non-classic flow died with ModuleNotFoundError before its first stage.
LINKDIR="$(mktemp -d)/skills/software-development"
mkdir -p "$LINKDIR"
ln -s "$(cd -P "$(dirname "$SCRIPT")/.." && pwd -P)" "$LINKDIR/loop-runner"
LINKED_ROOT="$(cd -P "$LINKDIR/loop-runner/scripts/../../../.." && pwd -P)"
t "symlinked skill resolves the repo root" "[ -f '$LINKED_ROOT/cuzam/runner.py' ]"
t "symlinked skill does not resolve to HERMES_HOME" "[ '$LINKED_ROOT' != \"$HOME/.hermes\" ]"

# Regression: a detached worker's PATH finds /usr/bin/python3, which has no
# PyYAML, so `import cuzam` failed for a missing dependency while the
# package itself was reachable. The runner must pick an interpreter that
# works rather than trusting whatever python3 resolves to.
REPO_PY="$REPO_ROOT/.venv/bin/python3"
if [ -x "$REPO_PY" ]; then
  t "repo venv interpreter can import cuzam" \
    "PYTHONPATH='$REPO_ROOT' '$REPO_PY' -c 'import cuzam.runner' 2>/dev/null"
  t "run-loop does not hardcode a bare python3 for the runner" \
    "! grep -qE '^\\s*exec python3 -m cuzam.runner' '$SCRIPT'"
  t "run-loop selects an interpreter that can import" \
    "grep -q 'zam_python' '$SCRIPT'"
  t "an explicit ZAM_PYTHON override is honoured" \
    "grep -q 'ZAM_PYTHON' '$SCRIPT'"
fi

# Regression: the loop must NOT detach. Hermes supervises a task by the
# liveness of the worker pid it spawned and records a worker that exits while
# its task is still running as a protocol violation, tripping the breaker on
# the first occurrence — so a detached loop got every run marked crashed
# minutes in, no matter how well it was going. The worker holds the script.
t "run-loop does not fork itself into the background" \
  "! grep -q 'os.fork' '$SCRIPT'"
t "run-loop does not start a new session" \
  "! grep -q 'os.setsid\|[^a-z]setsid ' '$SCRIPT'"
t "no re-exec guard is left behind" "! grep -q 'ZAM_DETACHED' '$SCRIPT'"

# The runner's exit status must survive the tee. Reporting a failed flow as a
# success is the one outcome this script may never produce.
t "runner status is taken from the pipeline head" \
  "grep -q 'PIPESTATUS\[0\]' '$SCRIPT'"

# Regression: the loop must find its own tools. The first dashboard launch
# died one second in with "No such file or directory: 'claude'" because the
# dashboard runs under launchd, whose PATH has no node toolchain — and claude
# is a node global installed through fnm, whose per-shell bin directory no
# daemon will ever have.
t "loop resolves tools rather than trusting the caller's PATH" \
  "grep -q 'aliases/default/bin' '$SCRIPT'"
# Appended, not prepended: repairing a broken PATH must not outrank one the
# caller set on purpose. Prepending shadowed this suite's own stub claude.
t "the repair appends, so a caller's PATH still wins" \
  "grep -q 'PATH=\"\$PATH:\$_dir\"' '$SCRIPT'"
t "an entry already present is not duplicated" \
  "grep -q 'case \":\$PATH:\" in' '$SCRIPT'"
# Ordering: the repair is useless after something has already tried to run.
PATH_LINE="$(grep -n 'export PATH' "$SCRIPT" | head -1 | cut -d: -f1)"
# The invocation, not the comment that mentions it on line 4.
REAP_LINE="$(grep -n 'bash "$SCRIPT_DIR/reap.sh"' "$SCRIPT" | head -1 | cut -d: -f1)"
t "PATH is repaired before any tool is invoked" \
  "[ -n '$PATH_LINE' ] && [ -n '$REAP_LINE' ] && [ '$PATH_LINE' -lt '$REAP_LINE' ]"


ZAM_PYTHON="$FAKEBIN/python3" "$SCRIPT" t-flow PROJ-12 --flow full >/dev/null 2>&1; RC=$?
t "custom flow: succeeds"             "[ $RC -eq 0 ]"
t "custom flow: runner module"        "grep -q -- '-m cuzam.runner' '$FAKEBIN/python_argv'"
t "custom flow: passes selection"     "grep -q -- '--flow full' '$FAKEBIN/python_argv'"
t "custom flow: passes task and issue" "grep -q -- '--task-id t-flow --issue PROJ-12' '$FAKEBIN/python_argv'"
t "custom flow: repo on PYTHONPATH"    "grep -Fq '$REPO_ROOT' '$FAKEBIN/pythonpath'"
t "custom flow: no session state"     "[ ! -e '$WT_FLOW/.cc-zam-session' ]"
rm -f "$FAKEBIN/python3"

# Test: child exits immediately (before ps can capture lstart)
# Mock ps to simulate the race condition: ps finds the pid but it has no lstart
rm -f "$FAKEBIN/claude" "$FAKEBIN/ps"
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
exit 9
EOF
chmod +x "$FAKEBIN/claude"

# Mock ps: when called for the instant-exit case, return empty lstart
cat > "$FAKEBIN/ps" <<'PSEOF'
#!/usr/bin/env bash
# Real ps path
REALPS="/bin/ps"
if [ "$1" = "-p" ]; then
  # This is the lstart capture call in run-loop.sh
  # Return empty to simulate the child exiting too fast
  echo ""
  exit 0
else
  # Pass through other ps calls
  exec "$REALPS" "$@"
fi
PSEOF
chmod +x "$FAKEBIN/ps"

WT2="$(mktemp -d)"; cd "$WT2"
"$SCRIPT" t-instant PROJ-01 2>"$RUN_LOOP_STDERR"; RC=$?

t "instant-exit: exit code 9 propagated"  "[ $RC -eq 9 ]"
t "instant-exit: no record written"       "[ ! -f '$PID_DIR/t-instant.json' ]"
t "instant-exit: stderr has guard log"    "grep -q 'run-loop: child gone before record' '$RUN_LOOP_STDERR'"

# What Claude said must survive a stop, and a run must be exactly one process.
#
# The first half: the output is buffered into a mktemp file and written out when
# the run ends, so a stop that killed the loop before that point lost it and
# leaked the file. TERM is trapped now, which is why zam-stop.sh sends TERM
# before KILL.
#
# The second half is the regression test for the fix that was tried first.
# Streaming the output with `> >(tee "$OUT")` forks a shell that does not exec,
# so `ps` shows it carrying this script's argv and task id — and both liveness
# implementations would have counted one run as two, with the fork outliving the
# loop. Asserting the count here is what catches that immediately.
PATH="$(echo "$PATH" | sed "s|$FAKEBIN:||")"
STREAMBIN="$(mktemp -d)"
cat > "$STREAMBIN/claude" <<'STREAMEOF'
#!/usr/bin/env bash
echo "STAGE-ONE-OUTPUT"
sleep 20
STREAMEOF
chmod +x "$STREAMBIN/claude"
export PATH="$STREAMBIN:$PATH"
LIVE_RUNS_SH="$REPO_ROOT/scripts/live-runs.sh"

WT3="$(mktemp -d)"; cd "$WT3"
STREAM_LOG="$STREAMBIN/flow.out"
"$SCRIPT" t-stream PROJ-02 > "$STREAM_LOG" 2>&1 &
LOOP_PID=$!
sleep 2

t "a running classic loop is exactly one live run, not two" \
  "[ \"\$(bash '$LIVE_RUNS_SH' | grep -c 't-stream')\" -eq 1 ]"

kill -TERM $LOOP_PID 2>/dev/null
wait $LOOP_PID 2>/dev/null; STREAM_RC=$?
sleep 1

t "a stopped run exits non-zero"        "[ $STREAM_RC -ne 0 ]"
t "what Claude had said survives the stop" \
  "grep -q STAGE-ONE-OUTPUT '$STREAM_LOG'"
t "and the stopped run leaves nothing behind that reads as live" \
  "! bash '$LIVE_RUNS_SH' | grep -q 't-stream'"

pkill -f "$STREAMBIN/claude" 2>/dev/null || true

# Duplication is checked on a run that finishes, because the stop above exits
# from the trap before the end of run_once.
cat > "$STREAMBIN/claude" <<'DONEEOF'
#!/usr/bin/env bash
echo "COMPLETED-OUTPUT"
exit 0
DONEEOF
chmod +x "$STREAMBIN/claude"
WT4="$(mktemp -d)"; cd "$WT4"
DONE_LOG="$STREAMBIN/done.out"
"$SCRIPT" t-done PROJ-03 > "$DONE_LOG" 2>&1
t "a completed run logs Claude's output exactly once" \
  "[ \"\$(grep -c COMPLETED-OUTPUT '$DONE_LOG')\" -eq 1 ]"

# A TERM arriving *after* the run finished must not print the output a second
# time. run_once flushes on the clean path and the trap flushes too, and several
# seconds of network calls sit between them — the grep over $OUT, the event emit,
# `gh pr list`, `kanban complete`. The stub sleeps there so the window is real.
cat > "$STREAMBIN/claude" <<'LATEEOF'
#!/usr/bin/env bash
echo "LATE-OUTPUT"
exit 0
LATEEOF
chmod +x "$STREAMBIN/claude"
cat > "$STREAMBIN/gh" <<'GHEOF'
#!/usr/bin/env bash
sleep 5
GHEOF
chmod +x "$STREAMBIN/gh"
WT5="$(mktemp -d)"; cd "$WT5"
LATE_LOG="$STREAMBIN/late.out"
"$SCRIPT" t-late PROJ-04 > "$LATE_LOG" 2>&1 &
LATE_PID=$!
# Wait until the flow is past run_once and into the reporting tail.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  grep -q LATE-OUTPUT "$LATE_LOG" 2>/dev/null && break
  sleep 0.5
done
kill -TERM $LATE_PID 2>/dev/null
wait $LATE_PID 2>/dev/null
t "a TERM after the run finished does not reprint the output" \
  "[ \"\$(grep -c LATE-OUTPUT '$LATE_LOG')\" -eq 1 ]"

cd "$REPO_ROOT"
rm -rf "$STREAMBIN" "$WT3" "$WT4" "$WT5"

echo; echo "run-loop.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
