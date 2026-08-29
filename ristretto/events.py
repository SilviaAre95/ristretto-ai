"""Ristretto's own pipeline event log.

Hermes' kanban records a task's lifecycle — claimed, spawned, blocked — but
has no concept of a stage, a grader, a verify gate, or a pull request. Those
are Ristretto's vocabulary, so Ristretto keeps its own append-only log rather
than writing into another project's private schema.

Emitting is best effort in the operational sense and strict in the
programming sense: an unreachable or corrupt store never fails a build, but
an event kind outside the closed vocabulary is a mistake in the caller and
raises immediately.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

# Closed vocabulary. The fleet view can only render states it was designed
# for, so a new kind is a deliberate change here and in the reader.
KINDS = frozenset(
    {
        "run.started",
        "run.ended",
        "stage.started",
        "stage.passed",
        "stage.failed",
        "grader.failed",
        "verify.green",
        "verify.red",
        "pr.opened",
        "awaiting.approval",
        "preflight.passed",
        "preflight.failed",
        # Actions taken from the fleet view. Recorded so a run that stops
        # has a reason in its timeline rather than just ending.
        "control.stop",
        "control.unblock",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id    TEXT    NOT NULL,
  issue_key  TEXT,
  project    TEXT,
  kind       TEXT    NOT NULL,
  stage      TEXT,
  payload    TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task   ON events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_events_recent ON events(created_at DESC);
"""


class UnknownEventKind(ValueError):
    """Raised when a caller emits a kind outside the closed vocabulary."""


def state_home(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("RISTRETTO_STATE_HOME", Path.home() / ".ristretto")).expanduser()


def store_path(environ: Mapping[str, str] | None = None) -> Path:
    return state_home(environ) / "events.db"


def connect(path: Path | None = None, environ: Mapping[str, str] | None = None) -> sqlite3.Connection:
    target = store_path(environ) if path is None else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    return connection


def emit(
    task_id: str,
    kind: str,
    *,
    issue_key: str | None = None,
    project: str | None = None,
    stage: str | None = None,
    payload: Mapping[str, Any] | None = None,
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    now: int | None = None,
) -> bool:
    """Append one event. Returns False if the store could not be written.

    Telemetry must never fail a build, so storage problems are reported on
    stderr and swallowed. A bad kind is a caller bug and raises.
    """
    if kind not in KINDS:
        raise UnknownEventKind(f"unknown event kind: {kind!r}; expected one of {sorted(KINDS)}")
    try:
        body = json.dumps(dict(payload), sort_keys=True) if payload else None
    except (TypeError, ValueError) as exc:
        print(f"ris-event: payload for {kind} is not serializable: {exc}", file=sys.stderr)
        body = None
    try:
        with connect(path, environ) as connection:
            connection.execute(
                "INSERT INTO events (task_id, issue_key, project, kind, stage, payload, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    issue_key,
                    project,
                    kind,
                    stage,
                    body,
                    int(time.time()) if now is None else now,
                ),
            )
    except (sqlite3.Error, OSError) as exc:
        print(f"ris-event: could not record {kind}: {exc}", file=sys.stderr)
        return False
    return True


def read(
    task_id: str | None = None,
    limit: int = 100,
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Most recent events first, newest-to-oldest."""
    query = "SELECT * FROM events"
    args: list[Any] = []
    if task_id:
        query += " WHERE task_id = ?"
        args.append(task_id)
    query += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    try:
        with connect(path, environ) as connection:
            rows: Iterable[sqlite3.Row] = connection.execute(query, args).fetchall()
    except (sqlite3.Error, OSError) as exc:
        print(f"ris-event: could not read events: {exc}", file=sys.stderr)
        return []
    result = []
    for row in rows:
        item = dict(row)
        if item.get("payload"):
            try:
                item["payload"] = json.loads(item["payload"])
            except json.JSONDecodeError:
                pass
        result.append(item)
    return result


def format_line(event: Mapping[str, Any]) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event["created_at"]))
    parts = [stamp, event["task_id"], event["kind"]]
    if event.get("stage"):
        parts.append(f"stage={event['stage']}")
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        parts.extend(f"{key}={value}" for key, value in sorted(payload.items()))
    elif payload:
        parts.append(str(payload))
    return "  ".join(str(part) for part in parts)
