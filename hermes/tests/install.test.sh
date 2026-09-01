#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ristretto-install-test.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

config_dir="$tmp/config"
bin_dir="$tmp/bin"
export RISTRETTO_CONFIG_DIR="$config_dir"
export RISTRETTO_BIN_DIR="$bin_dir"
export RISTRETTO_SKIP_SETUP=1

pass=0
fail=0

assert() {
  local description="$1"
  shift
  if "$@"; then
    pass=$((pass + 1))
    printf 'ok %d - %s\n' "$pass" "$description"
  else
    fail=$((fail + 1))
    printf 'not ok - %s\n' "$description" >&2
  fi
}

bash "$repo/scripts/install.sh" >/dev/null
assert "installer creates a CLI symlink" test -L "$bin_dir/ristretto"
assert "installer creates user configuration" test -f "$config_dir/config.yaml"
assert "installed configuration validates" "$bin_dir/ristretto" --config "$config_dir/config.yaml" validate

# A second run validates and preserves the existing user configuration.
before="$(shasum -a 256 "$config_dir/config.yaml")"
bash "$repo/scripts/install.sh" >/dev/null
after="$(shasum -a 256 "$config_dir/config.yaml")"
assert "installer is idempotent" test "$before" = "$after"

bash "$repo/scripts/uninstall.sh" >/dev/null
assert "default uninstall removes only the managed CLI link" test ! -e "$bin_dir/ristretto"
assert "default uninstall preserves user configuration" test -f "$config_dir/config.yaml"

bash "$repo/scripts/install.sh" >/dev/null
bash "$repo/scripts/uninstall.sh" --purge-config >/dev/null
assert "purge removes managed configuration" test ! -e "$config_dir/config.yaml"

mkdir -p "$bin_dir"
printf 'unrelated\n' >"$bin_dir/ristretto"
if bash "$repo/scripts/install.sh" >/dev/null 2>&1; then
  fail=$((fail + 1))
  echo "not ok - installer refuses an unrelated existing path" >&2
else
  pass=$((pass + 1))
  printf 'ok %d - installer refuses an unrelated existing path\n' "$pass"
fi
assert "collision path remains untouched" test "$(cat "$bin_dir/ristretto")" = "unrelated"

# Hermes installer runs against fake commands and an isolated HERMES_HOME.
fakebin="$tmp/fakebin"
fake_home="$tmp/hermes-home"
mkdir -p "$fakebin"
cat >"$fakebin/ristretto" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "validate" ]; then exit 0; fi
if [ "$1 $2" = "instance get" ]; then
  case "$3" in
    linear_team) echo PROJ ;;
    slack_home_channel) echo CHOME ;;
    slack_prs_channel) echo CPRS ;;
    slack_alerts_channel) echo CALERTS ;;
    knowledge_vault) echo /tmp/notes ;;
    *) exit 2 ;;
  esac
  exit 0
fi
exit 2
EOF
cat >"$fakebin/hermes" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "profile" ] && [ "${2:-}" = "create" ]; then
  mkdir -p "$HERMES_HOME/profiles/ris-worker/skills"
  exit 0
fi
if [ "${1:-}" = "cron" ] && [ "${2:-}" = "list" ]; then
  [ -f "$HERMES_HOME/cron-created" ] && echo "Morning brief"
  exit 0
fi
if [ "${1:-}" = "cron" ] && [ "${2:-}" = "create" ]; then
  touch "$HERMES_HOME/cron-created"
  exit 0
fi
if [ "${1:-}" = "gateway" ] && [ "${2:-}" = "install" ]; then
  touch "$HERMES_HOME/service-installed"
  exit 0
fi
# The installer verifies the flow guard is really registered rather than
# trusting that writing a config file was enough, so the stub has to answer
# `hooks list` the way hermes does — from the profile config.
case " $* " in
  *" hooks list "*)
    cat "$HERMES_HOME/profiles/ris-worker/config.yaml" 2>/dev/null
    exit 0
    ;;
esac
exit 0
EOF
chmod +x "$fakebin/ristretto" "$fakebin/hermes"

PATH="$fakebin:$PATH" RISTRETTO_HERMES_HOME="$fake_home" \
  bash "$repo/scripts/install-hermes.sh" >/dev/null
assert "Hermes installer creates config without a service" test -f "$fake_home/config.yaml"
assert "Hermes installer creates public persona" test -f "$fake_home/SOUL.md"
assert "Hermes installer links durable-dev" test -L "$fake_home/skills/software-development/durable-dev"
assert "Hermes installer deploys the morning precheck" test -x "$fake_home/scripts/morning-brief-precheck.py"
assert "Hermes installer creates worker profile skills" test -L "$fake_home/profiles/ris-worker/skills/software-development/loop-runner"
assert "Hermes installer creates one morning brief" test -f "$fake_home/cron-created"
assert "Hermes installer leaves service unchanged by default" test ! -e "$fake_home/service-installed"

PATH="$fakebin:$PATH" RISTRETTO_HERMES_HOME="$fake_home" \
  bash "$repo/scripts/install-hermes.sh" >/dev/null
assert "Hermes installer is idempotent" test -L "$fake_home/skills/software-development/loop-runner"
# The guard must survive a reinstall: `config set` used to store it as a
# string, which loads as no hooks and silently disarmed it on every update.
assert "reinstall keeps exactly one flow-guard block" \
  test "$(grep -c 'ris:flow-guard begin' "$fake_home/profiles/ris-worker/config.yaml")" -eq 1
assert "flow guard is declared as a list, not a string" \
  grep -q '^    - matcher: "kanban_complete"' "$fake_home/profiles/ris-worker/config.yaml"

PATH="$fakebin:$PATH" RISTRETTO_HERMES_HOME="$fake_home" \
  bash "$repo/scripts/install-hermes.sh" --service >/dev/null
assert "explicit service option installs the service" test -f "$fake_home/service-installed"

# Regression: linking a plugin is not enabling it. A discovered-but-disabled
# plugin registers no commands, so !ris-approve silently does nothing — which
# is exactly how it shipped the first time.
assert "installer links the approvals plugin" \
  test -e "$fake_home/plugins/ris-approvals/plugin.yaml"
assert "installer enables the approvals plugin" \
  grep -q "plugins enable ris-approvals" "$repo/scripts/install-hermes.sh"

printf '%d passed, %d failed\n' "$pass" "$fail"
test "$fail" -eq 0
