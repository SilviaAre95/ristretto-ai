"""Ops-lane daemon: owns the single Telegram poller and runs a persistent
Claude Code conversation rooted at a working directory, relaying replies and
gating tool calls.

Holds NO permission policy. Identity lock decides "who"; Claude Code's settings
decide "what"; your Telegram tap decides "when". Every message is a
conversational turn: `claude -p --resume <session>` under the configured root
(you roam and create repos by talking to Claude), its reply relayed back, its
tool calls surfaced as Approve/Deny. Conversation ids persist so a restart
resumes where you left off.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from .audit import audit
from .config import OpsConfig
from .identity import is_allowed
from .launcher import build_claude_argv, write_mcp_config
from .session import SessionStore
from .spool import Spool

_MAX_MSG = 3500  # Telegram hard-caps at 4096; leave headroom.


def _default_run_claude(argv: list[str], cwd: str) -> dict:
    # stdin=DEVNULL: claude -p otherwise waits ~3s for piped stdin each turn.
    proc = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        text = (proc.stdout or proc.stderr or "").strip()
        return {"session_id": None, "result": text or "(no output)", "is_error": True}
    return {
        "session_id": data.get("session_id"),
        "result": data.get("result", ""),
        "is_error": bool(data.get("is_error", False)),
    }


class OpsDaemon:
    def __init__(
        self,
        client,
        ops_config: OpsConfig,
        allowed: set[int],
        *,
        session_store: SessionStore | None = None,
        run_claude=_default_run_claude,
        background: bool = True,
    ) -> None:
        self.client = client
        self.cfg = ops_config
        self.allowed = allowed
        self.sessions = session_store or SessionStore(ops_config.sessions_path)
        self.run_claude = run_claude
        self.background = background
        self.root = str(Path(ops_config.root_dir))
        self.spool = Spool(ops_config.spool_dir)
        self._rendered: set[str] = set()
        self._decided: set[str] = set()
        self._busy: set[int] = set()

    # --- messages -------------------------------------------------------
    def handle_message(self, message: dict) -> None:
        user_id = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if not is_allowed(user_id, self.allowed):
            return  # fail closed, silent

        if text in ("/new", "/reset", "/end", "/stop"):
            self.sessions.clear(chat_id)
            self.client.send_message(chat_id, f"Fresh conversation. Rooted at {self.root}. Send a message.")
            return
        if text in ("/help", "/start"):
            self.client.send_message(
                chat_id,
                f"Chat with Claude, rooted at {self.root}. Ask it to work in a repo "
                f"or create one; I'll ask before it runs tools. /ls lists folders, "
                f"/new starts a fresh conversation.",
            )
            return
        if text in ("/ls", "/repos"):
            try:
                entries = sorted(
                    p.name for p in Path(self.root).iterdir()
                    if p.is_dir() and not p.name.startswith(".")
                )
            except OSError:
                entries = []
            listing = ", ".join(entries[:60]) if entries else "(nothing)"
            self.client.send_message(chat_id, f"Folders under {self.root}:\n{listing}")
            return

        # A conversational turn.
        if chat_id in self._busy:
            self.client.send_message(chat_id, "⏳ Still working on the previous message — one moment.")
            return
        session = self.sessions.ensure(chat_id)
        self._busy.add(chat_id)
        if self.background:
            threading.Thread(target=self._run_turn, args=(chat_id, session, text), daemon=True).start()
        else:
            self._run_turn(chat_id, session, text)

    def _run_turn(self, chat_id: int, session, prompt: str) -> None:
        try:
            mcp_config = write_mcp_config(
                self.spool.dir, self.cfg.broker_python, str(chat_id),
                self.spool.dir, self.cfg.approval_timeout_s,
            )
            argv = build_claude_argv(
                prompt, mcp_config,
                resume_session_id=session.claude_session_id,
                settings_path=self.cfg.strict_settings_path,
                setting_sources=self.cfg.setting_sources,
                strict_mcp=self.cfg.strict_mcp,
                claude_bin=self.cfg.claude_bin,
            )
            audit(self.cfg.audit_path, {"event": "turn", "chat": chat_id, "root": self.root, "resumed": bool(session.claude_session_id)})
            try:
                out = self.run_claude(argv, self.root)
            except Exception as exc:
                audit(self.cfg.audit_path, {"event": "turn_failed", "chat": chat_id, "error": str(exc)})
                self.client.send_message(chat_id, f"⚠️ Couldn't run: {exc}")
                return
            if out.get("session_id"):
                self.sessions.set_claude_id(chat_id, out["session_id"])  # persists
            reply = out.get("result") or "(no reply)"
            if out.get("is_error"):
                reply = "⚠️ " + reply
            self._send_long(chat_id, reply)
        finally:
            self._busy.discard(chat_id)

    def _send_long(self, chat_id: int, text: str) -> None:
        for i in range(0, max(len(text), 1), _MAX_MSG):
            self.client.send_message(chat_id, text[i:i + _MAX_MSG])

    # --- approvals ------------------------------------------------------
    def pump_spool(self) -> None:
        for request_id, payload in self.spool.read_new_requests():
            if request_id in self._rendered:
                continue
            session_stamp = str(payload.get("session", ""))
            if not session_stamp:
                continue  # unstamped request; can't route, let it time out (deny)
            chat_id = int(session_stamp)
            self._rendered.add(request_id)
            tool_input = payload.get("input", {})
            command = tool_input.get("command", "")
            tool = payload.get("tool_name", "tool")
            body = command or json.dumps(tool_input)
            self.client.send_message(
                chat_id,
                f"Approve {tool}?\n\n{body}",
                buttons=[("✅ Approve", f"a:{request_id}"), ("⛔ Deny", f"d:{request_id}")],
            )
            audit(self.cfg.audit_path, {"event": "prompt", "request": request_id, "chat": chat_id, "tool": tool, "command": command})

    def decode_callback(self, data: str) -> tuple[str, str]:
        verb, _, request_id = data.partition(":")
        return verb, request_id

    def handle_callback(self, callback: dict) -> None:
        user_id = callback.get("from", {}).get("id")
        if not is_allowed(user_id, self.allowed):
            return
        verb, request_id = self.decode_callback(callback.get("data", ""))
        cb_id = callback.get("id", "")
        if verb not in ("a", "d") or not request_id:
            self.client.answer_callback(cb_id, text="ignored")
            return
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        if request_id in self._decided:
            self.client.answer_callback(cb_id, text="already handled")
            return
        request = self.spool.read_request(request_id)
        if request is None:
            self.client.answer_callback(cb_id, text="expired")
            return
        if str(request.get("session", "")) != str(chat_id):
            self.client.answer_callback(cb_id, text="not your request")
            audit(self.cfg.audit_path, {"event": "decision_rejected", "request": request_id, "chat": chat_id})
            return
        decision = "allow" if verb == "a" else "deny"
        self.spool.write_decision(request_id, {"permissionDecision": decision, "reason": "Telegram tap."})
        self._decided.add(request_id)
        audit(self.cfg.audit_path, {"event": "decision", "request": request_id, "decision": decision})
        self.client.answer_callback(cb_id, text=decision)
        mark = "✅ Approved" if decision == "allow" else "⛔ Denied"
        command = (request.get("input") or {}).get("command", "") or request.get("tool_name", "tool")
        if chat_id is not None and message_id is not None:
            try:
                self.client.edit_message_text(chat_id, message_id, f"{mark}: {command}")
            except Exception:
                self.client.send_message(chat_id, mark)

    # --- main loop ------------------------------------------------------
    def run(self, poll=True) -> None:  # pragma: no cover - live loop
        offset = None
        while poll:
            try:
                updates = self.client.get_updates(offset, self.cfg.poll_timeout_s)
            except Exception:
                continue
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    if "message" in update:
                        self.handle_message(update["message"])
                    elif "callback_query" in update:
                        self.handle_callback(update["callback_query"])
                except Exception:
                    continue
            try:
                self.pump_spool()
            except Exception:
                continue
