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
# Run synchronously here. In production the loop detaches into its own session
# and returns immediately, which is the point of it — but a test that asserts
# on exit codes and captured argv has to see the run through.
export RIS_DETACHED=1
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
[ -s ".cc-ris-session" ] && cp ".cc-ris-session" "$FAKEBIN/session_during_run"
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
t "failed run keeps session id"     "[ -s '$WT/.cc-ris-session' ]"
t "no dangerous flag anywhere"      "! grep -rq 'dangerously-skip-permissions' '$ROOT/skills'"
t "no --model flag without arg"     "! grep -q -- '--model' '$FAKEBIN/argv'"

# Model tier: valid tier is passed through, junk is dropped (allowlist)
WT_M="$(mktemp -d)"; cd "$WT_M"
"$SCRIPT" t-model PROJ-02 sonnet >/dev/null 2>&1
t "valid model appended"            "grep -q -- '--model sonnet' '$FAKEBIN/argv'"
t "cloud tier: no base_url export"  "grep -q '^none$' '$FAKEBIN/baseurl'"
rm -f "$WT_M/.cc-ris-session"
"$SCRIPT" t-model2 PROJ-03 'opus; rm -rf /' >/dev/null 2>&1
t "junk model dropped (allowlist)"  "! grep -q -- '--model' '$FAKEBIN/argv'"

# Local tier: routes to Ollama's Anthropic endpoint with the local coder model
"$SCRIPT" t-local PROJ-04 local >/dev/null 2>&1
t "local tier: ollama model passed" "grep -q -- '--model qwen3.6:27b-coding-nvfp4' '$FAKEBIN/argv'"
t "local tier: base_url exported"   "grep -q 'http://localhost:11434' '$FAKEBIN/baseurl'"
t "local tier: no session flags"    "! grep -qE -- '--session-id|--resume' '$FAKEBIN/argv'"
RIS_LOCAL_LOOP_MODEL="qwen3-coder-next:q4_K_M" "$SCRIPT" t-local2 PROJ-05 local >/dev/null 2>&1
t "local tier: model override env"  "grep -q -- '--model qwen3-coder-next:q4_K_M' '$FAKEBIN/argv'"

# Resume-first cloud path: reuse the worktree session and clear it on success.
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/argv"
exit 0
EOF
chmod +x "$FAKEBIN/claude"
WT_R="$(mktemp -d)"; cd "$WT_R"
printf '%s\n' '11111111-1111-1111-1111-111111111111' > .cc-ris-session
"$SCRIPT" t-resume PROJ-09 >/dev/null 2>&1; RC=$?
t "resume: succeeds"                 "[ $RC -eq 0 ]"
t "resume: existing id reused"       "grep -q -- '--resume 11111111-1111-1111-1111-111111111111' '$FAKEBIN/argv'"
t "resume: continuation prompt"      "grep -q 'continue: finish the armed dev loop for PROJ-09' '$FAKEBIN/argv'"
t "resume: does not re-invoke skill" "! grep -q '/harness:loop-dev' '$FAKEBIN/argv'"
t "success removes session file"     "[ ! -e '$WT_R/.cc-ris-session' ]"

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
printf '%s\n' '22222222-2222-2222-2222-222222222222' > .cc-ris-session
RIS_RESUME_FAILURE_WINDOW=30 "$SCRIPT" t-resume-fallback PROJ-10 >/dev/null 2>"$FAKEBIN/resume_stderr"; RC=$?
t "resume fallback: fresh succeeds"  "[ $RC -eq 0 ]"
t "resume fallback: two cloud calls" "[ \$(wc -l < '$FAKEBIN/argv_log' | tr -d ' ') -eq 2 ]"
t "resume fallback: resume first"     "sed -n '1p' '$FAKEBIN/argv_log' | grep -q -- '--resume 22222222-2222-2222-2222-222222222222'"
t "resume fallback: fresh second"    "sed -n '2p' '$FAKEBIN/argv_log' | grep -q -- '--session-id'"
t "resume fallback: new id used"     "! sed -n '2p' '$FAKEBIN/argv_log' | grep -q '22222222-2222-2222-2222-222222222222'"
t "resume fallback: announced"       "grep -q 'resume failed quickly' '$FAKEBIN/resume_stderr'"
t "resume fallback: success cleans"  "[ ! -e '$WT_RF/.cc-ris-session' ]"

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
t "session file is git-excluded"     "git check-ignore -q --no-index .cc-ris-session"

# Auto-fallback: claude unavailable (auth/limit) -> re-run once on the local model
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/argv"
echo "\${ANTHROPIC_BASE_URL:-none}" > "$FAKEBIN/baseurl"
if [ -z "\${ANTHROPIC_BASE_URL:-}" ]; then echo "You've hit your session limit"; exit 1; fi
exit 0
EOF
chmod +x "$FAKEBIN/claude"
"$SCRIPT" t-fb PROJ-06 >/dev/null 2>"$FB_STDERR"; RC=$?
t "fallback: local run succeeds"    "[ $RC -eq 0 ]"
t "fallback: local model used"      "grep -q -- '--model qwen3.6:27b-coding-nvfp4' '$FAKEBIN/argv'"
t "fallback: announced on stderr"   "grep -q 'falling back to local model' '$FB_STDERR'"

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

# RIS_LOCAL_FALLBACK=0 disables the fallback even on auth failures
cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
echo "\$@" > "$FAKEBIN/argv"
echo "OAuth session expired"; exit 1
EOF
chmod +x "$FAKEBIN/claude"
RIS_LOCAL_FALLBACK=0 "$SCRIPT" t-fboff PROJ-08 >/dev/null 2>&1; RC=$?
t "fallback disabled: fails through" "[ $RC -eq 1 ]"
t "fallback disabled: stays cloud"   "! grep -q -- '--model' '$FAKEBIN/argv'"

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
t "symlinked skill resolves the repo root" "[ -f '$LINKED_ROOT/ristretto/runner.py' ]"
t "symlinked skill does not resolve to HERMES_HOME" "[ '$LINKED_ROOT' != \"$HOME/.hermes\" ]"

# Regression: a detached worker's PATH finds /usr/bin/python3, which has no
# PyYAML, so `import ristretto` failed for a missing dependency while the
# package itself was reachable. The runner must pick an interpreter that
# works rather than trusting whatever python3 resolves to.
REPO_PY="$REPO_ROOT/.venv/bin/python3"
if [ -x "$REPO_PY" ]; then
  t "repo venv interpreter can import ristretto" \
    "PYTHONPATH='$REPO_ROOT' '$REPO_PY' -c 'import ristretto.runner' 2>/dev/null"
  t "run-loop does not hardcode a bare python3 for the runner" \
    "! grep -qE '^\\s*exec python3 -m ristretto.runner' '$SCRIPT'"
  t "run-loop selects an interpreter that can import" \
    "grep -q 'ris_python' '$SCRIPT'"
  t "an explicit RIS_PYTHON override is honoured" \
    "grep -q 'RIS_PYTHON' '$SCRIPT'"
fi

# Regression: the loop must lead its own session. An agent that launches it
# ends its turn, Hermes tears down the terminal environment, and anything
# still in that session dies mid-stage. setsid fails with EPERM for a process
# that already leads its group, so the fork must come first — swallowing that
# error looks like detaching and is not.
t "run-loop detaches before doing anything" "grep -q 'RIS_DETACHED' '$SCRIPT'"
t "detach forks before setsid" \
  "grep -A3 'os.fork' '$SCRIPT' | grep -q 'os.setsid'"
t "detach does not swallow a failed setsid" \
  "! grep -B2 -A2 'os.setsid' '$SCRIPT' | grep -q 'except OSError'"

RIS_PYTHON="$FAKEBIN/python3" "$SCRIPT" t-flow PROJ-12 --flow tier1 >/dev/null 2>&1; RC=$?
t "custom flow: succeeds"             "[ $RC -eq 0 ]"
t "custom flow: runner module"        "grep -q -- '-m ristretto.runner' '$FAKEBIN/python_argv'"
t "custom flow: passes selection"     "grep -q -- '--flow tier1' '$FAKEBIN/python_argv'"
t "custom flow: passes task and issue" "grep -q -- '--task-id t-flow --issue PROJ-12' '$FAKEBIN/python_argv'"
t "custom flow: repo on PYTHONPATH"    "grep -Fq '$REPO_ROOT' '$FAKEBIN/pythonpath'"
t "custom flow: no session state"     "[ ! -e '$WT_FLOW/.cc-ris-session' ]"
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

echo; echo "run-loop.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
