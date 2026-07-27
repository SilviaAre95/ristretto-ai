"""Per-chat ops session state. You name the repo; the daemon never guesses."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class Session:
    repo: str
    path: str


def resolve_repo(message: str, repos: Mapping[str, str]) -> tuple[str, str] | None:
    wanted = message.strip().lower()
    for name, path in repos.items():
        if name.lower() == wanted:
            return name, str(path)
    return None


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[int, Session] = {}

    def get(self, chat_id: int) -> Session | None:
        return self._sessions.get(chat_id)

    def start(self, chat_id: int, name: str, path: str) -> Session:
        session = Session(repo=name, path=path)
        self._sessions[chat_id] = session
        return session

    def clear(self, chat_id: int) -> None:
        self._sessions.pop(chat_id, None)

    def active_chats(self) -> list[int]:
        return list(self._sessions)
