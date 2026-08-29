"""The two things the fleet view is allowed to change.

Read routes can afford to be relaxed about who is asking. Mutating ones
cannot: the dashboard has no login, so a page you happen to visit while on
the tailnet could otherwise post to it from your browser and stop your
agents. Every action here is same-origin only, addressed by a validated task
id, and recorded in the event log so the timeline shows it happened.

Deliberately not here: starting work. Stopping a run costs a restart;
launching one spends tokens and writes code, and it deserves its own design
rather than a third button added by analogy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import NamedTuple

from .. import events
from .data import SAFE_TASK_ID

STOP_SCRIPT = Path.home() / ".hermes" / "scripts" / "ris-stop.sh"


class Outcome(NamedTuple):
    ok: bool
    message: str


def _record(task_id: str, kind: str, outcome: Outcome, actor: str) -> None:
    events.emit(
        task_id,
        kind,
        stage="control",
        payload={"ok": outcome.ok, "detail": outcome.message[:400], "actor": actor},
    )


def stop(task_id: str, actor: str = "dashboard", timeout: int = 180) -> Outcome:
    """Stop a running task via the hardened kill switch.

    ris-stop.sh already reclaims the task, kills the worker by its exact
    spawn signature, verified-reaps the Claude Code grandchild, and re-checks
    for the promote race. Its non-zero exit and NOT STOPPED message are
    surfaced verbatim rather than translated into a cheerful failure.
    """
    if not SAFE_TASK_ID.fullmatch(task_id):
        return Outcome(False, "invalid task id")
    if not STOP_SCRIPT.is_file():
        return Outcome(False, f"kill switch not installed at {STOP_SCRIPT}")
    try:
        result = subprocess.run(
            ["bash", str(STOP_SCRIPT), task_id],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.SubprocessError as exc:
        outcome = Outcome(False, f"stop did not run: {exc}")
        _record(task_id, "control.stop", outcome, actor)
        return outcome
    detail = (result.stdout + result.stderr).strip().splitlines()
    tail = " / ".join(line.strip() for line in detail[-4:] if line.strip())
    outcome = Outcome(result.returncode == 0, tail or f"exit {result.returncode}")
    _record(task_id, "control.stop", outcome, actor)
    return outcome


def unblock(task_id: str, actor: str = "dashboard", timeout: int = 60) -> Outcome:
    """Return a blocked task to the queue so the dispatcher can pick it up."""
    if not SAFE_TASK_ID.fullmatch(task_id):
        return Outcome(False, "invalid task id")
    try:
        result = subprocess.run(
            ["hermes", "kanban", "unblock", task_id],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        outcome = Outcome(False, f"unblock did not run: {exc}")
        _record(task_id, "control.unblock", outcome, actor)
        return outcome
    detail = (result.stdout + result.stderr).strip().splitlines()
    tail = " / ".join(line.strip() for line in detail[-3:] if line.strip())
    outcome = Outcome(result.returncode == 0, tail or f"exit {result.returncode}")
    _record(task_id, "control.unblock", outcome, actor)
    return outcome
