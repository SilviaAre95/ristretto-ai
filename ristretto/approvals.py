"""Pending approvals, shared by every surface that can answer them.

A flow that needs permission stops and asks. The question has to reach you
wherever you are — Slack on a phone, the dashboard on the iPad — and both of
those can answer it, sometimes at once. So the question lives in one record
and the answer is written with a conditional update: the first decision wins
and the second is told it lost, rather than silently overwriting a decision
someone already acted on.

Two rules this module exists to keep:

*Fail closed.* A request that is never answered is a deny. An unreachable
store is a deny. A malformed decision is a deny. The failure mode of an
approval prompt must never be "proceeded anyway".

*Decide nothing.* This module records and relays. It has no policy, no
allowlist, and no opinion about which tool calls are safe — that judgement is
the whole reason a human is being asked.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

from . import events

# A decision is one of these and nothing else. Anything unrecognised is
# treated as a deny by `decision_of`, so a corrupt row cannot approve.
ALLOW = "allow"
DENY = "deny"

# How long a request waits before it parks itself as a deny. Long enough to
# reach a phone and answer; short enough that a flow does not hold a worktree
# and a Hermes claim overnight waiting for someone who has gone to bed.
DEFAULT_TIMEOUT_SECONDS = 30 * 60

# How often a blocked broker re-reads the row. The wait is a real person
# walking to a device, so a second of latency costs nothing and a tight poll
# would spin a CPU for half an hour.
POLL_SECONDS = 1.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
  id           TEXT    PRIMARY KEY,
  task_id      TEXT    NOT NULL,
  issue_key    TEXT,
  stage        TEXT,
  tool_name    TEXT    NOT NULL,
  tool_input   TEXT,
  requested_at INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL,
  decision     TEXT,
  reason       TEXT,
  decided_by   TEXT,
  decided_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(decision, expires_at);
CREATE INDEX IF NOT EXISTS idx_approvals_task    ON approvals(task_id, requested_at DESC);
"""


def store_path(environ: Mapping[str, str] | None = None) -> Path:
    return events.state_home(environ) / "approvals.db"


def connect(path: Path | None = None, environ: Mapping[str, str] | None = None) -> sqlite3.Connection:
    target = store_path(environ) if path is None else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    return connection


def decision_of(value: Any) -> str:
    """Map a stored value to a decision, treating anything odd as a deny."""
    return ALLOW if value == ALLOW else DENY


# How much of a tool call we keep. Big enough for a real command, small
# enough that one runaway request cannot bloat the store.
MAX_STORED_INPUT = 4000
# How much of any single value survives when the whole call is too big. The
# question a person answers is "what is this trying to do", and the opening
# lines of a command answer it; the body of a heredoc does not.
MAX_STORED_VALUE = 600


def stored_input(tool_input: Mapping[str, Any] | None) -> str:
    """Serialise a tool call for the store, keeping it readable and parseable.

    Clipping the serialised JSON — which is what this used to do — cuts the
    document mid-string, so it no longer parses. `_row` then swallows the
    error and renders an empty input, and the approval card shows a tool name
    and nothing else. That is the worst possible failure for a permission
    prompt: it asks a person to authorise something while showing them a blank
    cheque, and it fires precisely on the *large* calls most worth reading.

    Not hypothetical. Every approval a local coder raised on 2026-09-11 was
    unreadable this way — five in a row — because the model writes its files
    with long heredocs. The gate was effectively unusable in the flow it
    matters most for.

    So clip the values instead and let json.dumps produce a valid document
    either way, and say in the value itself that it was shortened, so nobody
    mistakes a clipped command for the whole command.
    """
    data = dict(tool_input or {})
    rendered = json.dumps(data, default=str)
    if len(rendered) <= MAX_STORED_INPUT:
        return rendered

    trimmed: dict[str, Any] = {}
    for key, value in data.items():
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        if len(text) > MAX_STORED_VALUE:
            dropped = len(text) - MAX_STORED_VALUE
            trimmed[key] = text[:MAX_STORED_VALUE] + f"… [{dropped} more characters]"
        else:
            trimmed[key] = value
    rendered = json.dumps(trimmed, default=str)
    if len(rendered) <= MAX_STORED_INPUT:
        return rendered

    # Still too big — a call with very many keys. Keep something true and
    # parseable rather than something detailed and broken.
    return json.dumps(
        {
            "_clipped": True,
            "_keys": sorted(data)[:40],
            "_bytes": len(json.dumps(data, default=str)),
        }
    )


def request(
    request_id: str,
    task_id: str,
    tool_name: str,
    tool_input: Mapping[str, Any] | None = None,
    *,
    issue_key: str | None = None,
    stage: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record a question and announce it. Returns the stored row."""
    now = int(time.time())
    expires = now + max(1, int(timeout_seconds))
    with connect(path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO approvals "
            "(id, task_id, issue_key, stage, tool_name, tool_input, requested_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                request_id,
                task_id,
                issue_key,
                stage,
                tool_name,
                stored_input(tool_input),
                now,
                expires,
            ),
        )
    # The doorbell turns this into a Slack ping and the fleet view into a
    # card. Emitting after the row is committed, so neither surface can show
    # a question that cannot yet be answered.
    events.emit(
        task_id,
        "awaiting.approval",
        issue_key=issue_key,
        stage=stage,
        payload={"id": request_id, "what": describe(tool_name, tool_input), "expires_at": expires},
    )
    return {"id": request_id, "expires_at": expires}


def describe(tool_name: str, tool_input: Mapping[str, Any] | None) -> str:
    """One line naming what is actually being asked for.

    A notification that says only "permission needed" forces you to open a
    laptop to find out what you are approving, which is the whole problem
    this is meant to remove. The first live request read "Waiting on you:
    AskUserQuestion" and nothing else, which is the same failure in a nicer
    font: the tool's name is not what you are being asked.
    """
    data = dict(tool_input or {})
    if data.get("_unreadable"):
        return f"{tool_name}: request unreadable — do not approve without checking the log"
    if data.get("_clipped"):
        # The wide-call fallback keeps no values, so without this it fell all
        # the way through to a bare tool name — the same blank cheque this
        # module exists to prevent, reintroduced by its own safety net.
        kept = ", ".join(str(key) for key in (data.get("_keys") or [])[:6])
        return (
            f"{tool_name}: too large to store ({data.get('_bytes', '?')} bytes)"
            + (f", fields: {kept}" if kept else "")
            + " — check the log before approving"
        )
    question = _first_question(data)
    if question:
        return _clip(question, 160)
    # The agent's own one-line description comes first when there is one.
    # Ordering the raw command ahead of it meant a phone showed
    #   Bash: find ~/vault -name "*.md" -path "*project*" | head -10
    # with a 25-minute clock and no statement of intent, while
    # "Search vault notes for XARI-31" sat in the same payload, unused.
    # The command still shows: it is what is actually being authorised, and a
    # description is the agent's account of itself, not proof.
    described = " ".join(str(data.get("description") or "").split())
    for key in ("command", "file_path", "path", "url", "pattern", "prompt"):
        value = data.get(key)
        if not value:
            continue
        detail = _clip(" ".join(str(value).split()), 120)
        if described:
            return f"{_clip(described, 80)} — {tool_name}: {detail}"
        return f"{tool_name}: {detail}"
    if described:
        return f"{_clip(described, 120)} — {tool_name}"
    return tool_name


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _first_question(data: Mapping[str, Any]) -> str:
    """The question text, for tools that ask rather than act."""
    questions = data.get("questions")
    if isinstance(questions, (list, tuple)) and questions:
        first = questions[0]
        if isinstance(first, Mapping):
            return str(first.get("question") or "")
    return ""


def detail(tool_name: str, tool_input: Mapping[str, Any] | None) -> dict[str, Any]:
    """Everything a person needs on screen to answer without a terminal.

    Deliberately structured rather than a blob: a question with options is
    not the same shape as a command, and rendering both as raw JSON is how
    you end up approving something you did not read.
    """
    data = dict(tool_input or {})
    questions = data.get("questions")
    if isinstance(questions, (list, tuple)) and questions:
        asked = []
        for item in questions:
            if not isinstance(item, Mapping):
                continue
            asked.append(
                {
                    "question": str(item.get("question") or ""),
                    "options": [
                        {
                            "label": str(option.get("label") or ""),
                            "description": _clip(str(option.get("description") or ""), 400),
                        }
                        for option in (item.get("options") or [])
                        if isinstance(option, Mapping)
                    ],
                }
            )
        return {"kind": "question", "tool": tool_name, "questions": asked}
    for key in ("command", "file_path", "path", "url", "pattern"):
        if data.get(key):
            return {"kind": "action", "tool": tool_name, "target": str(data[key])}
    # Unknown shape: show it rather than hiding it behind a tool name.
    try:
        rendered = json.dumps(data, indent=2, default=str)
    except (TypeError, ValueError):
        rendered = str(data)
    return {"kind": "raw", "tool": tool_name, "payload": _clip_lines(rendered, 40)}


def _clip_lines(text: str, limit: int) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit] + [f"… {len(lines) - limit} more lines"])


def decide(
    request_id: str,
    decision: str,
    *,
    actor: str,
    reason: str = "",
    path: Path | None = None,
) -> tuple[bool, str]:
    """Answer a pending request. Returns (this decision won, message).

    Conditional on the row still being undecided, so two surfaces answering
    at once resolve to one winner. Losing is not an error worth hiding: the
    caller is told what the standing decision is and who made it.
    """
    verdict = decision_of(decision)
    now = int(time.time())
    with connect(path) as connection:
        cursor = connection.execute(
            "UPDATE approvals SET decision = ?, reason = ?, decided_by = ?, decided_at = ? "
            "WHERE id = ? AND decision IS NULL",
            (verdict, reason[:400], actor[:80], now, request_id),
        )
        if cursor.rowcount == 1:
            return True, verdict
        row = connection.execute(
            "SELECT decision, decided_by FROM approvals WHERE id = ?", (request_id,)
        ).fetchone()
    if row is None:
        return False, "no such approval"
    return False, f"already {row['decision']} by {row['decided_by'] or 'someone'}"


def await_decision(
    request_id: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    path: Path | None = None,
    poll_seconds: float = POLL_SECONDS,
    now: Any = time.time,
    sleep: Any = time.sleep,
) -> tuple[str, str]:
    """Block until the request is answered or expires. Returns (decision, reason).

    Every exit from this function that is not an explicit allow is a deny.
    """
    deadline = now() + max(1, int(timeout_seconds))
    while True:
        try:
            with connect(path) as connection:
                row = connection.execute(
                    "SELECT decision, reason FROM approvals WHERE id = ?", (request_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            # A store we cannot read is not permission to proceed.
            return DENY, f"approval store unreadable: {exc}"
        if row is not None and row["decision"] is not None:
            return decision_of(row["decision"]), row["reason"] or ""
        if now() >= deadline:
            expire(request_id, path=path)
            return DENY, "no answer before timeout — parked as denied"
        sleep(poll_seconds)


def expire(request_id: str, path: Path | None = None) -> None:
    """Stamp an unanswered request as denied so both surfaces stop offering it."""
    try:
        with connect(path) as connection:
            connection.execute(
                "UPDATE approvals SET decision = ?, reason = ?, decided_by = ?, decided_at = ? "
                "WHERE id = ? AND decision IS NULL",
                (DENY, "timed out", "timeout", int(time.time()), request_id),
            )
    except sqlite3.Error:
        # The broker already returns a deny; failing to record it must not
        # turn into an exception on the flow's way out.
        pass


def blocked_seconds(
    task_id: str,
    since: float,
    *,
    until: float | None = None,
    path: Path | None = None,
) -> float:
    """Wall-clock seconds this task spent stopped, waiting for a person.

    The stage budget is meant to measure work. A stage at a permission prompt
    is not working, and charging it anyway makes the careful agent the one
    that fails: run 67 spent 3437 of its 3600 seconds here and died reporting
    "nothing written". This is the number that has to be handed back.

    Merged, not summed. Claude Code asks for several tool calls in one turn
    and each opens its own request, so two questions are often outstanding at
    once — run 67's Read and Bash overlapped by five and a half minutes, and
    adding its rows up gives 3766 seconds inside a 3600-second hour. What the
    stage actually lost is the union: the time during which it was stopped,
    however many questions were stopping it.

    Only requests opened at or after `since` count. Callers take `since`
    immediately before spawning the process whose clock this credits, so a
    request older than that belongs to a process that is already gone and
    cannot be blocking this one. That is not hypothetical: a stage killed at
    its deadline leaves its last request undecided with up to half an hour on
    it — run 67's is still NULL in the live store — and the fallback attempt
    that starts seconds later would otherwise watch that orphan accrue credit
    at one second per second while it worked uninterrupted, and never reach
    its own deadline. Clamping such a row's start to `since` is not enough:
    one answered just after the new attempt began leaks the same way.

    An undecided row counts only to its own `expires_at`, for the same reason
    in the other direction — nothing reaps these rows, and counting one to now
    forever would eventually excuse any deadline at all.

    An unreadable store is worth no credit. This decides how long a stage may
    keep running, so the failure has to be towards the shorter budget.
    """
    window_end = time.time() if until is None else until
    try:
        with connect(path) as connection:
            rows = connection.execute(
                "SELECT requested_at, decided_at, expires_at FROM approvals WHERE task_id = ?",
                (task_id,),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return 0.0

    spans: list[tuple[float, float]] = []
    for row in rows:
        start = float(row["requested_at"])
        if start < since:
            continue
        decided = row["decided_at"]
        stop = float(decided) if decided is not None else min(window_end, float(row["expires_at"]))
        stop = min(stop, window_end)
        if stop > start:
            spans.append((start, stop))
    if not spans:
        return 0.0

    spans.sort()
    total = 0.0
    open_start, open_stop = spans[0]
    for start, stop in spans[1:]:
        if start > open_stop:
            total += open_stop - open_start
            open_start, open_stop = start, stop
        else:
            open_stop = max(open_stop, stop)
    return total + (open_stop - open_start)


def pending(path: Path | None = None, task_id: str | None = None) -> list[dict[str, Any]]:
    """Unanswered, unexpired requests — newest first."""
    now = int(time.time())
    query = "SELECT * FROM approvals WHERE decision IS NULL AND expires_at > ?"
    args: list[Any] = [now]
    if task_id:
        query += " AND task_id = ?"
        args.append(task_id)
    query += " ORDER BY requested_at DESC"
    try:
        with connect(path) as connection:
            rows = connection.execute(query, args).fetchall()
    except sqlite3.Error:
        return []
    return [_row(row) for row in rows]


def get(request_id: str, path: Path | None = None) -> dict[str, Any] | None:
    try:
        with connect(path) as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE id = ?", (request_id,)
            ).fetchone()
    except sqlite3.Error:
        return None
    return _row(row) if row else None


def _row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["tool_input"] = json.loads(item.get("tool_input") or "{}")
    except (TypeError, ValueError):
        # An unparseable record is not an empty one, and rendering it as empty
        # is how a blank cheque reaches a person. Say it is unreadable so the
        # surfaces can show that instead of a bare tool name — and so rows
        # written before `stored_input` existed still fail loudly.
        item["tool_input"] = {"_unreadable": "stored input is not valid JSON"}
    item["what"] = describe(item.get("tool_name", ""), item["tool_input"])
    item["detail"] = detail(item.get("tool_name", ""), item["tool_input"])
    return item
