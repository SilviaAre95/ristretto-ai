"""Minimal Telegram Bot API client over stdlib urllib. Outbound only."""
from __future__ import annotations

import json
import urllib.request

_API = "https://api.telegram.org"


class TelegramClient:
    def __init__(self, token: str, *, urlopen=urllib.request.urlopen) -> None:
        self._token = token
        self._urlopen = urlopen

    def _call(self, method: str, payload: dict, timeout_s: int) -> dict:
        url = f"{_API}/bot{self._token}/{method}"
        data = json.dumps(payload).encode()
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with self._urlopen(request, timeout=timeout_s) as response:
            body = json.loads(response.read().decode())
        if not body.get("ok"):
            raise RuntimeError(f"telegram {method} failed: {body.get('description')}")
        return body["result"]

    def get_me(self) -> dict:
        return self._call("getMe", {}, timeout_s=10)

    def get_updates(self, offset: int | None, timeout_s: int = 25) -> list[dict]:
        payload = {"timeout": timeout_s, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        # Network read must outlast the long-poll timeout.
        return self._call("getUpdates", payload, timeout_s=timeout_s + 10)

    def send_message(
        self, chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None
    ) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": label, "callback_data": data} for label, data in buttons]
                ]
            }
        return self._call("sendMessage", payload, timeout_s=15)

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        self._call(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text},
            timeout_s=10,
        )
