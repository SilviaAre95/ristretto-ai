#!/usr/bin/env bash
# Tests for ris-stop.sh (S-5 kill switch). Self-contained; uses a temp HOME
# and stubbed hermes/pkill/pgrep. A local Hermes installation is checked when
# present, but is not required for contributors or CI.
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/ris-stop.sh"

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
  printf '{"task": {"status": "%s"}}\n' "${RIS_TEST_STATUS:-blocked}"
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
RIS_TEST_STATUS=in_progress bash "$SCRIPT" t-live > "$HOME/out" 2>&1
RC=$?
t "unblocked task exits non-zero" "[ $RC -ne 0 ]"
t "unblocked task reports NOT STOPPED" "grep -q 'NOT STOPPED: task t-live' '$HOME/out'"

# 5. Archived counts as stopped (dispatcher can't pick it up again)
RIS_TEST_STATUS=archived bash "$SCRIPT" t-arch > "$HOME/out" 2>&1
t "archived task counts as stopped" "[ $? -eq 0 ]"

rm -rf "$HOME" "$FAKEBIN"
HOME="$REAL_HOME"

echo; echo "ris-stop.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
