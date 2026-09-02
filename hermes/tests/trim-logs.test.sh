#!/usr/bin/env bash
# Guards for the log trimmer. The failure it prevents is silent (a log grows
# until the disk hurts), so the guards are about not making it worse.
set -u
pass=0; fail=0
t() { if eval "$2"; then echo "ok  - $1"; pass=$((pass+1)); else echo "FAIL - $1"; fail=$((fail+1)); fi; }

repo="$(cd "$(dirname "$0")/../.." && pwd)"
script="$repo/scripts/trim-logs.sh"
tmp="$(mktemp -d)"
logs="$tmp/logs"; mkdir -p "$logs"

python3 -c "
open('$logs/big.log','w').write('noise\n' * 200000)
open('$logs/small.log','w').write('keep me\n')
"
before_inode="$(ls -i "$logs/big.log" | awk '{print $1}')"
out="$(RISTRETTO_LOG_DIR=$logs RISTRETTO_LOG_MAX_BYTES=1048576 bash "$script" 2>&1)"

t "oversized log is trimmed"        "[ \$(wc -c < \"$logs/big.log\") -lt 1048576 ]"
t "trim is reported"                "echo '$out' | grep -q 'big.log'"
t "small log is left alone"         "[ \"\$(cat '$logs/small.log')\" = 'keep me' ]"
# A rename would leave the gateway writing to an unlinked inode nobody can see.
t "file is trimmed in place, not replaced" \
  "[ \"\$(ls -i '$logs/big.log' | awk '{print \$1}')\" = '$before_inode' ]"
t "the tail is what survives"       "tail -1 '$logs/big.log' | grep -q noise"
t "no leftover temp files"          "[ -z \"\$(ls '$logs' | grep -c '\.trim\.' | grep -v '^0$')\" ]"

# A missing directory is a no-op, not a crash: this runs from cron.
out2="$(RISTRETTO_LOG_DIR=$tmp/absent bash "$script" 2>&1)"; rc2=$?
t "missing log dir exits 0"         "[ $rc2 -eq 0 ]"
t "missing log dir says so"         "echo '$out2' | grep -qi 'no log directory'"

out3="$(RISTRETTO_LOG_DIR=$logs RISTRETTO_LOG_MAX_BYTES=999999999 bash "$script" 2>&1)"
t "nothing oversized is a no-op"    "echo '$out3' | grep -qi 'nothing over'"

rm -rf "$tmp"
printf '\ntrim-logs.test.sh: %d passed, %d failed\n' "$pass" "$fail"
test "$fail" -eq 0
