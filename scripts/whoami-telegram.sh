#!/usr/bin/env bash
# Print the numeric Telegram user ID(s) of whoever recently messaged your bot.
# Reads TELEGRAM_BOT_TOKEN from ~/.hermes/.env so the token never has to be typed.
# Usage: message your bot in Telegram first, then run this.
set -euo pipefail

env_file="${HOME}/.hermes/.env"
token="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$env_file" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' ' || true)"

if [ -z "${token:-}" ]; then
  echo "No TELEGRAM_BOT_TOKEN found in $env_file." >&2
  echo "Add a line 'TELEGRAM_BOT_TOKEN=<your token>' to that file, then re-run." >&2
  exit 1
fi

resp="$(curl -s "https://api.telegram.org/bot${token}/getUpdates")"

python3 - "$resp" <<'PY'
import json, sys
data = json.loads(sys.argv[1] or "{}")
if not data.get("ok"):
    print("Telegram API error:", data.get("description", "unknown"))
    print("(If it mentions a webhook, run: curl -s \"https://api.telegram.org/bot<TOKEN>/deleteWebhook\" — then retry.)")
    raise SystemExit(1)
seen = {}
for u in data.get("result", []):
    msg = u.get("message") or u.get("edited_message") or {}
    frm = msg.get("from")
    if frm:
        seen[frm["id"]] = frm
if not seen:
    print("No messages yet. Open your bot in Telegram, send it any message, then run this again.")
    raise SystemExit(0)
print("Who has messaged your bot:")
for uid, frm in seen.items():
    name = frm.get("first_name", "")
    uname = frm.get("username")
    print(f"  numeric id: {uid}   name: {name}" + (f"   @{uname}" if uname else ""))
print()
print("Put YOUR id in ~/.hermes/.env as:  TELEGRAM_ALLOWED_USERS=<that number>")
PY
