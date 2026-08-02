"""Identity lock: only explicitly allowlisted Telegram user IDs are obeyed."""
from __future__ import annotations

from collections.abc import Mapping


def allowed_user_ids(environ: Mapping[str, str]) -> set[int]:
    raw = environ.get("TELEGRAM_ALLOWED_USERS", "")
    ids: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            # Ignore non-numeric entries (e.g. an unfilled placeholder) rather
            # than crash; fail closed by simply not trusting them.
            continue
    return ids


def is_allowed(user_id: int, allowed: set[int]) -> bool:
    # Fail closed: an empty allowlist obeys no one.
    return user_id in allowed
