"""Ops-lane daemon: owns the single Telegram poller, launches Claude Code per
named repo, and relays approval prompts to/from the phone.

Holds NO permission policy. Identity lock decides "who"; Claude Code's settings
decide "what"; your tap decides "when"."""
from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

from .audit import audit
from .config import OpsConfig
from .identity import is_allowed
from .launcher import build_claude_argv, write_mcp_config
from .session import SessionStore, resolve_repo
from .spool import Spool


class OpsDaemon:
    def __init__(
        self,
        client,
        repos: Mapping[str, str],
        ops_config: OpsConfig,
        allowed: set[int],
        *,
        session_store: SessionStore | None = None,
        spawn=subprocess.Popen,
        slack_send=None,
    ) -> None:
        self.client = client
        self.repos = repos
        self.cfg = ops_config
        self.allowed = allowed
        self.sessions = session_store or SessionStore()
        self.spawn = spawn
        self.slack_send = slack_send
        self.spool = Spool(ops_config.spool_dir)
        self._rendered: set[str] = set()

    # --- messages -------------------------------------------------------
    def handle_message(self, message: dict) -> None:
        user_id = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if not is_allowed(user_id, self.allowed):
            return  # fail closed, silent
        session = self.sessions.get(chat_id)
        if session is None:
            resolved = resolve_repo(text, self.repos)
            if resolved is None:
                self.client.send_message(
                    chat_id,
                    "First, name a repo to work in. Known repos: "
                    + ", ".join(self.repos) + ".",
                )
                return
            name, path = resolved
            self.sessions.start(chat_id, name, path)
            self.client.send_message(chat_id, f"Session pinned to {name}. Send your task.")
            return
        self._launch(chat_id, session.path, text)

    def _launch(self, chat_id: int, workdir: str, prompt: str) -> None:
        mcp_config = write_mcp_config(self.spool.dir, self.cfg.broker_python)
        argv = build_claude_argv(prompt, mcp_config, claude_bin=self.cfg.claude_bin)
        audit(self.cfg.audit_path, {"event": "launch", "chat": chat_id, "cwd": workdir})
        self.spawn(argv, cwd=workdir)
        self.client.send_message(chat_id, f"Running in {Path(workdir).name}. I'll ask before gated actions.")

    # --- approvals ------------------------------------------------------
    def pump_spool(self, chat_id: int) -> None:
        for request_id, payload in self.spool.read_new_requests():
            if request_id in self._rendered:
                continue
            self._rendered.add(request_id)
            command = payload.get("tool_input", {}).get("command", "")
            tool = payload.get("tool_name", "tool")
            text = f"Approve {tool}?\n\n{command or payload.get('tool_input')}"
            self.client.send_message(
                chat_id,
                text,
                buttons=[("✅ Approve", f"a:{request_id}"), ("⛔ Deny", f"d:{request_id}")],
            )
            audit(self.cfg.audit_path, {"event": "prompt", "request": request_id, "tool": tool, "command": command})

    def decode_callback(self, data: str) -> tuple[str, str]:
        verb, _, request_id = data.partition(":")
        return verb, request_id

    def handle_callback(self, callback: dict) -> None:
        user_id = callback.get("from", {}).get("id")
        if not is_allowed(user_id, self.allowed):
            return
        verb, request_id = self.decode_callback(callback.get("data", ""))
        decision = "allow" if verb == "a" else "deny"
        self.spool.write_decision(
            request_id, {"permissionDecision": decision, "reason": "Telegram tap."}
        )
        audit(self.cfg.audit_path, {"event": "decision", "request": request_id, "decision": decision})
        self.client.answer_callback(callback.get("id", ""), text=decision)
        chat_id = callback.get("message", {}).get("chat", {}).get("id")
        if chat_id is not None:
            self.client.send_message(chat_id, f"{decision.upper()} — {request_id}")

    # --- main loop ------------------------------------------------------
    def run(self, poll=True) -> None:  # pragma: no cover - live loop
        offset = None
        while poll:
            for update in self.client.get_updates(offset, self.cfg.poll_timeout_s):
                offset = update["update_id"] + 1
                if "message" in update:
                    self.handle_message(update["message"])
                elif "callback_query" in update:
                    self.handle_callback(update["callback_query"])
            for chat_id in self.sessions.active_chats():
                self.pump_spool(chat_id)
