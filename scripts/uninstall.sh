#!/usr/bin/env bash
# Remove only files managed by scripts/install.sh. User config is preserved
# unless --purge-config is explicitly passed.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_dir="${RISTRETTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/ristretto}"
bin_dir="${RISTRETTO_BIN_DIR:-$HOME/.local/bin}"
link="$bin_dir/ristretto"
target="$repo/.venv/bin/ristretto"

if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
  rm "$link"
  echo "Removed Ristretto CLI link: $link"
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
