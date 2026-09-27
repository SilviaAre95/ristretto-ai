#!/usr/bin/env bash
# Remove only files managed by scripts/install.sh. User config is preserved
# unless --purge-config is explicitly passed.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Both RISTRETTO_* fallbacks are pre-rename names. They matter here for the
# same reason as in the installer: an uninstall that resolves the wrong
# directory reports success and removes nothing. Drop in 0.3.0.
config_dir="${CUZAM_CONFIG_DIR:-${RISTRETTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/cuzam}}"
bin_dir="${CUZAM_BIN_DIR:-${RISTRETTO_BIN_DIR:-$HOME/.local/bin}}"  # drop in 0.3.0
link="$bin_dir/cuzam"
target="$repo/.venv/bin/cuzam"

if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
  rm "$link"
  echo "Removed Cuzam CLI link: $link"
elif [ -e "$link" ] || [ -L "$link" ]; then
  echo "uninstall: left unrelated path untouched: $link" >&2
fi

if [ "${1:-}" = "--purge-config" ]; then
  config="$config_dir/config.yaml"
  if [ -f "$config" ]; then
    rm "$config"
    echo "Removed user configuration: $config"
  fi
  rmdir "$config_dir" 2>/dev/null || true
else
  echo "Preserved user configuration: $config_dir"
fi

echo "The repository, .venv, Hermes, credentials, and gateway were not changed."
