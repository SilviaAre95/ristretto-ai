#!/usr/bin/env bash
# Keep the fleet view running without anyone remembering to start it.
#
# The dashboard spent a day serving code from the previous morning because it
# was a bare background process nobody restarted: it reported a live run as
# stalled, then rendered without the approval banner, and each time the fix
# was a manual restart, which is not a fix. launchd restarts it on crash and
# on login, and the footer stamps the commit so a stale process is visible
# rather than silently wrong.
#
# The plist is generated here rather than committed: it embeds absolute paths
# and this machine's layout, neither of which belongs in the repository.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
label="com.ristretto.dash"
plist="$HOME/Library/LaunchAgents/$label.plist"
port="${RISTRETTO_DASH_PORT:-8787}"
logs="$HOME/Library/Logs"

python_bin="$repo/.venv/bin/python3"
if [ ! -x "$python_bin" ]; then
  echo "install-dash-service: no interpreter at $python_bin — run 'make setup' first" >&2
  exit 1
fi
if ! "$python_bin" -c "import ristretto.dash.app" >/dev/null 2>&1; then
  echo "install-dash-service: that interpreter cannot import the dashboard" >&2
  echo "install-dash-service: run 'make setup' (the [dash] extra is required)" >&2
  exit 1
fi

case "${1:-install}" in
  uninstall)
    launchctl bootout "gui/$UID/$label" 2>/dev/null || true
    rm -f "$plist"
    echo "dash service removed. The dashboard is no longer supervised."
    exit 0
    ;;
  install) ;;
  *)
    echo "usage: install-dash-service.sh [install|uninstall]" >&2
    exit 2
    ;;
esac

mkdir -p "$HOME/Library/LaunchAgents" "$logs"

# PATH matters: the bind address and the link hostname both come from the
# tailscale binary, and launchd starts with a PATH that does not include it.
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$python_bin</string>
    <string>-m</string>
    <string>ristretto.cli</string>
    <string>dash</string>
    <string>--port</string>
    <string>$port</string>
  </array>
  <key>WorkingDirectory</key><string>$repo</string>
  <key>EnvironmentVariables</key>
  <dict>
    <!-- hermes lives in ~/.local/bin and the board query shells it; launchd
         starts with a PATH that has neither it nor tailscale, so the fleet
         page dies with FileNotFoundError: 'hermes'. -->
    <key>PATH</key>
    <string>$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <!-- Without this a crash-looping server restarts as fast as it can fail. -->
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$logs/ristretto-dash.log</string>
  <key>StandardErrorPath</key><string>$logs/ristretto-dash.log</string>
</dict>
</plist>
PLIST

# Any hand-started copy owns the port and would make the service crash-loop
# on bind. Take it down before handing over.
pkill -f "ristretto.cli dash" 2>/dev/null || true
sleep 1
# Verify rather than assume: a survivor keeps the port and the new service
# crash-loops behind it, still serving whatever the old one was built from.
for _ in 1 2 3; do
  survivors="$(pgrep -f "ristretto.cli dash" || true)"
  [ -z "$survivors" ] && break
  # shellcheck disable=SC2086
  kill -9 $survivors 2>/dev/null || true
  sleep 1
done
if pgrep -f "ristretto.cli dash" >/dev/null 2>&1; then
  echo "install-dash-service: a dashboard process survived and holds port $port" >&2
  echo "install-dash-service: kill it before installing, or the service crash-loops" >&2
  exit 1
fi

launchctl bootout "gui/$UID/$label" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$plist"
launchctl kickstart -k "gui/$UID/$label" 2>/dev/null || true

# Tell Nemo where to find this dashboard. The address is a fact about this
# machine, so it is written here rather than compiled into the app.
link_host="$("$python_bin" -c "
import sys; sys.path.insert(0, '$repo')
from ristretto.dash.serve import link_host
print(link_host())" 2>/dev/null || echo 127.0.0.1)"
mkdir -p "$HOME/.ristretto"
printf 'http://%s:%s\n' "$link_host" "$port" > "$HOME/.ristretto/dash-url"

echo "dash service installed: $plist"
echo "  logs:    $logs/ristretto-dash.log"
echo "  restart: launchctl kickstart -k gui/$UID/$label"
echo "  remove:  scripts/install-dash-service.sh uninstall"
