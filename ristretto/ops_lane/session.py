"""Per-chat ops session state, persisted so a daemon restart resumes the same
Claude Code conversation instead of starting over.

A session is just the Claude conversation id for that chat; every session works
under the daemon's configured root directory (you roam and create repos there
by talking to Claude)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Session:
    # Claude Code conversation id; set after the first turn and reused via
    # --resume so the conversation remembers prior messages.
    claude_session_id: str | None = None


class SessionStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self._sessions: dict[int, Session] = {}
        self._path = Path(path) if path else None
        if self._path and self._path.exists():
            self.load()

    def get(self, chat_id: int) -> Session | None:
        return self._sessions.get(chat_id)

    def ensure(self, chat_id: int) -> Session:
        session = self._sessions.get(chat_id)
        if session is None:
            session = Session()
            self._sessions[chat_id] = session
        return session

    def set_claude_id(self, chat_id: int, claude_session_id: str | None) -> None:
        self.ensure(chat_id).claude_session_id = claude_session_id
        self.save()

    def clear(self, chat_id: int) -> None:
        self._sessions.pop(chat_id, None)
        self.save()

    def active_chats(self) -> list[int]:
        return list(self._sessions)

    def save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {str(c): s.claude_session_id for c, s in self._sessions.items()}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self._path)

    def load(self) -> None:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return
        self._sessions = {
            int(c): Session(claude_session_id=v) for c, v in data.items()
        }
