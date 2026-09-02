"""Assemble the fleet view from the kanban board and Ristretto's event log.

Hermes owns task lifecycle; Ristretto owns what happened inside a run. Neither
alone answers "what is this agent doing right now", so the two are joined here
on task id.

Hermes' CLI does not expose `last_heartbeat_at`, so the spec's heartbeat-age
rule cannot be implemented from a supported interface. Liveness is derived
instead from the age of the newest signal we do have — a Ristretto event, or
the run's start — and the view says which signal it used rather than implying
a heartbeat it never saw.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .. import events

# Same shape ris-stop.sh enforces before it will act on an id.
SAFE_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
# A run with no news for this long, still claiming to be active, is reported
# as stalled rather than healthy. Silence is the failure mode that cost two
# tasks a month apiece.
STALL_AFTER_SECONDS = 15 * 60
# Finished work older than this is history, not fleet status.
RECENT_WINDOW_SECONDS = 7 * 24 * 3600
ACTIVE_STATES = frozenset({"running", "ready", "review", "todo", "triage"})
LIVE_STATES = ACTIVE_STATES | {"blocked", "scheduled"}


@dataclass
class Run:
    task_id: str
    title: str
    status: str
    project: str
    issue_key: str | None = None
    branch: str | None = None
    started_at: int | None = None
    completed_at: int | None = None
    stage: str | None = None
    last_event: Mapping[str, Any] | None = None
    last_signal_at: int | None = None
    signal_source: str = "none"
    flow_alive: bool = False
    failure: str | None = None
    events: list[Mapping[str, Any]] = field(default_factory=list)

    @property
    def health(self) -> str:
        """running | stalled | blocked | failed | done | idle"""
        if self.status == "blocked":
            return "blocked"
        if self.status in {"done", "archived"}:
            return "failed" if self.failure else "done"
        if self.status not in ACTIVE_STATES:
            return "idle"
        # A quiet run with a live flow process is working, not stalled. Only
        # silence with nothing running behind it is a stall.
        if self.flow_alive:
            return "running"
        if self.age_of_signal is not None and self.age_of_signal > STALL_AFTER_SECONDS:
            return "stalled"
        return "running"

    @property
    def age_of_signal(self) -> int | None:
        if self.last_signal_at is None:
            return None
        return max(0, int(time.time()) - int(self.last_signal_at))

    @property
    def finished(self) -> bool:
        return self.status in {"done", "archived"}

    @property
    def elapsed(self) -> int | None:
        """How long the run took, or has been going.

        A finished task with no completion time has an unknowable duration —
        counting from its start would show a number that grows forever and
        reads as though the work were still in flight.
        """
        if not self.started_at:
            return None
        if self.finished:
            if not self.completed_at:
                return None
            return max(0, int(self.completed_at) - int(self.started_at))
        return max(0, int(time.time()) - int(self.started_at))


def ago(timestamp: int | None) -> str:
    """How long since something happened, so July cannot be mistaken for today."""
    if not timestamp:
        return "—"
    return f"{humanise(max(0, int(time.time()) - int(timestamp)))} ago"


def humanise(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d"


def running_flows(timeout: int = 10) -> set[str]:
    """Task ids with a live flow process on this machine.

    Event age alone is a poor liveness test: a build stage emits nothing
    between its start and its finish and legitimately runs for the better
    part of an hour, so a healthy run reads as stalled. The dashboard is on
    the same machine as the runner, so it can ask instead of inferring.
    """
    # Listing every process and filtering here, rather than pgrep -f: a
    # pattern search matches the command line of whatever runs the search,
    # so any shell mentioning "ristretto.runner --task-id" — including a
    # monitor watching for one — reports itself as a live flow.
    try:
        listing = subprocess.run(
            ["ps", "-eo", "command="],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    found = set()
    for line in listing.stdout.splitlines():
        if "-m ristretto.runner" not in line or "--task-id" not in line:
            continue
        # A shell that merely mentions the runner is not running it.
        if line.lstrip().startswith(("/bin/sh", "/bin/bash", "/bin/zsh", "sh ", "bash ", "zsh ")):
            continue
        found.add(line.split("--task-id", 1)[1].split()[0])
    return found


def board(timeout: int = 30) -> list[dict[str, Any]]:
    """Every task Hermes knows about, archived included. Empty if unreadable."""
    result = subprocess.run(
        ["hermes", "kanban", "list", "--json", "--archived"],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else payload.get("tasks", [])


def task_detail(task_id: str, timeout: int = 30) -> dict[str, Any]:
    """Hermes' own view of one task, including its run history.

    The id arrives from a URL and crosses a process boundary. There is no
    shell here — the command is a list — but unvalidated request data should
    not reach another program's argv on the strength of that alone, so the
    shape is checked first. It matches the guard `ris-stop.sh` already uses.
    """
    if not SAFE_TASK_ID.fullmatch(task_id):
        return {}
    result = subprocess.run(
        ["hermes", "kanban", "show", "--json", task_id],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _issue_key(task: Mapping[str, Any]) -> str | None:
    title = str(task.get("title") or "")
    head = title.split("·")[0].strip()
    return head or None


def _project(task: Mapping[str, Any]) -> str:
    path = task.get("workspace_path")
    if not path:
        return "unassigned"
    parts = Path(str(path)).parts
    # .../<project>/.worktrees/<task id>
    if ".worktrees" in parts:
        return parts[parts.index(".worktrees") - 1]
    return Path(str(path)).name


def build_run(task: Mapping[str, Any], task_events: list[Mapping[str, Any]]) -> Run:
    run = Run(
        task_id=str(task.get("id")),
        title=str(task.get("title") or task.get("id")),
        status=str(task.get("status") or "unknown").lower(),
        project=_project(task),
        issue_key=_issue_key(task),
        branch=task.get("branch_name"),
        started_at=task.get("started_at"),
        completed_at=task.get("completed_at"),
        events=task_events,
    )
    if task_events:
        newest = task_events[0]
        run.last_event = newest
        run.last_signal_at = newest.get("created_at")
        run.signal_source = "event"
        for item in task_events:
            if item.get("kind") == "stage.started":
                run.stage = item.get("stage")
                break
        for item in task_events:
            if item.get("kind") in {"stage.failed", "verify.red"}:
                payload = item.get("payload") or {}
                run.failure = payload.get("reason") or payload.get("detail")
                break
    elif run.started_at:
        run.last_signal_at = run.started_at
        run.signal_source = "start"
    return run


def fleet(limit_events: int = 200) -> list[Run]:
    """Every run the board knows about, newest activity first."""
    recorded: dict[str, list[Mapping[str, Any]]] = {}
    for item in events.read(limit=limit_events * 10):
        recorded.setdefault(str(item.get("task_id")), []).append(item)
    live = running_flows()
    runs = []
    for task in board():
        run = build_run(task, recorded.get(str(task.get("id")), []))
        run.flow_alive = run.task_id in live
        runs.append(run)
    runs.sort(key=lambda r: (r.last_signal_at or 0), reverse=True)
    return runs


def recent(runs: list[Run], window: int = RECENT_WINDOW_SECONDS) -> tuple[list[Run], int]:
    """What is worth looking at now, and how much was left out.

    A fleet view showing every task ever finished is a graveyard: the work
    that needs attention is buried under months of archived rows that all
    look alike. Anything live is always kept, however quiet it has been.
    """
    cutoff = int(time.time()) - window
    keep, hidden = [], 0
    for run in runs:
        if run.status in LIVE_STATES or (run.last_signal_at or 0) >= cutoff:
            keep.append(run)
        else:
            hidden += 1
    return keep, hidden


def grouped(runs: list[Run]) -> dict[str, list[Run]]:
    """Runs by project, projects with live work first."""
    buckets: dict[str, list[Run]] = {}
    for run in runs:
        buckets.setdefault(run.project, []).append(run)
    order = sorted(
        buckets,
        key=lambda name: (
            not any(r.status in LIVE_STATES for r in buckets[name]),
            name.lower(),
        ),
    )
    return {name: buckets[name] for name in order}


# When this process started and what it was built from. A long-running server
# quietly serving month-old code is its own kind of outage: the fleet view
# reported a live run as stalled for an hour because the process predated the
# fix. Stamped once at import — the answer cannot change without a restart,
# which is exactly the point.
STARTED_AT = int(time.time())


def _read_commit() -> tuple[str, bool]:
    """The checkout as it stands right now."""
    repo = Path(__file__).resolve().parents[2]
    commit, dirty = "unknown", False
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        if result.returncode == 0:
            commit = result.stdout.strip() or "unknown"
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        dirty = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return commit, dirty


# Stamped once, at import, alongside STARTED_AT. Read per request it was
# worse than useless: it reported whatever the checkout says *now*, so a
# process running three-hour-old code displayed the newest commit and looked
# current. The whole point of the stamp is to catch that, and it could not.
LOADED_COMMIT, LOADED_DIRTY = _read_commit()


def build_stamp() -> dict[str, str | bool]:
    """What this process is running — not what the checkout says today."""
    current, _ = _read_commit()
    return {
        "commit": LOADED_COMMIT,
        "dirty": LOADED_DIRTY,
        "uptime": humanise(int(time.time()) - STARTED_AT) or "0s",
        # A running process older than the checkout is the failure this
        # exists to surface, so it is stated rather than left to be inferred
        # from two hex strings.
        "stale": current != LOADED_COMMIT and current != "unknown",
        "current": current,
    }
