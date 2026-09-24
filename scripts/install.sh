#!/usr/bin/env bash
# Safe first-stage installer: CLI + public configuration only.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_dir="${CUZAM_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/cuzam}"
bin_dir="${CUZAM_BIN_DIR:-$HOME/.local/bin}"
config="$config_dir/config.yaml"
link="$bin_dir/cuzam"
target="$repo/.venv/bin/cuzam"

if [ "${CUZAM_SKIP_SETUP:-0}" != "1" ]; then
  bash "$repo/scripts/setup-dev.sh"
fi
if [ ! -x "$target" ]; then
  echo "install: CLI target is missing: $target" >&2
  echo "Run make setup, then retry." >&2
  exit 1
fi

mkdir -p "$config_dir" "$bin_dir"
if [ ! -e "$config" ]; then
  cp "$repo/cuzam.yaml" "$config"
  chmod 0600 "$config"
  echo "Created user configuration: $config"
else
  "$target" --config "$config" validate
  echo "Kept existing valid configuration: $config"
fi

if [ -L "$link" ]; then
  current="$(readlink "$link")"
  if [ "$current" != "$target" ]; then
    echo "install: refusing to replace unrelated symlink: $link -> $current" >&2
    exit 1
  fi
elif [ -e "$link" ]; then
  echo "install: refusing to replace existing path: $link" >&2
  exit 1
else
  ln -s "$target" "$link"
fi

"$target" --config "$config" validate
echo "Installed Cuzam CLI: $link"
echo "Next: edit $config, then run: cuzam doctor"
echo "Hermes skills and services were not changed."
