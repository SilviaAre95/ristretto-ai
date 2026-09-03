"""Start a supervised run from a surface that is not a terminal.

Deliberately the last control to be built, and the most guarded. Stopping a
run costs a restart; starting one spends tokens, writes code to a branch, and
holds a worktree for an hour. The dashboard has no login, so every guard here
assumes the caller is entitled to launch and asks instead whether launching
is a good idea right now.

Four checks, each because something already went wrong without it:

*Preflight.* A repository that cannot run a loop fails fifty minutes into a
build with an error that reads like a model failure. `fast_findings` already
knows how to spot that in milliseconds.

*Idempotency.* A tap that does not visibly do anything gets tapped again. Two
runs on one branch is the worst outcome this module can produce, so the key
is derived from the request rather than the click.

*Busy.* Queueing work you will forget you asked for is how a fleet view stops
being trustworthy. If something is already live, say so and let the person
decide.

*Same-origin.* Enforced by the caller, like every other mutating route.

The CLI and the dashboard both call `launch()`, so the guards cannot drift
between the surface that is tested and the surface that is used.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from .. import events
from ..config import ConfigError, load_config, repository_path

# Linear-style keys, which is what every configured project uses. Anything
# else is a typo, and a typo here starts an hour of work on nothing.
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{1,6}$")

# The worker profile the dispatcher hands loop tasks to.
ASSIGNEE = "ris-worker"
SKILL = "loop-runner"

# Long enough for a slow tier1 build (the one measured run spent 51 minutes
# in a single stage), short enough that a wedged run does not hold a worktree
# overnight.
MAX_RUNTIME_SECONDS = 5400
# One retry. A loop that failed for a real reason fails the same way twice,
# and the second run costs another hour of tokens to learn nothing.
MAX_RETRIES = 1


class Outcome(NamedTuple):
    ok: bool
    message: str
    task_id: str = ""


def example_key(config: Mapping[str, Any] | None = None) -> str:
    """An example issue key for messages — the user's own prefix, or neutral.

    Hardcoding one prefix into a tool other people download both confuses a
    user whose team is ABC and leaks the original owner's team key. The real
    prefix already lives in config.
    """
    if config is not None:
        team = str((config.get("instance") or {}).get("linear_team") or "").strip()
        if team:
            return f"{team}-42"
    return "ABC-42"


def branch_for(issue: str) -> str:
    """The feature branch a run will push.

    Deterministic from the issue key alone. A slug would read better, but it
    needs the issue title, and a guessed slug is worse than none: it is the
    part a human later greps for.
    """
    return f"xariprojects/{issue.lower()}"


def idempotency_key(issue: str, flow: str, now: float | None = None) -> str:
    """Stable for the same request on the same day.

    Scoped to a day rather than forever: relaunching a failed run tomorrow is
    normal, and double-tapping a button today is not.
    """
    stamp = time.strftime("%Y%m%d", time.localtime(now if now is not None else time.time()))
    return f"{issue}-{flow}-{stamp}"


def validate(
    config: Mapping[str, Any], project: str, issue: str, flow: str
) -> tuple[Path | None, str]:
    """Check the request before anything is spent. Returns (repo, error)."""
    if not ISSUE_KEY.fullmatch(issue or ""):
        return None, f"{issue!r} is not an issue key (expected something like {example_key(config)})"
    if flow not in (config.get("flows") or {}):
        known = ", ".join(sorted(config.get("flows") or {}))
        return None, f"unknown flow {flow!r} — configured flows are: {known}"
    try:
        repo = repository_path(config, project)
    except ConfigError as exc:
        return None, str(exc)
    if not repo.is_dir():
        return None, f"{project} is configured but {repo} is not there"
    return repo, ""


def blocking_findings(repo: Path, base: str) -> list[str]:
    """Preflight problems that should stop a launch, as plain sentences."""
    from ..preflight import fast_findings

    # .message, not str(f): __str__ prefixes the level, which would read
    # "cannot run a loop yet: ERROR ...".
    return [f.message for f in fast_findings(repo, base) if f.level == "ERROR"]


def active_runs() -> list[str]:
    """Task ids the board considers live, newest first."""
    from . import data

    try:
        return [run.task_id for run in data.fleet() if run.status in data.ACTIVE_STATES]
    except Exception:  # noqa: BLE001 - a busy check must not block a launch
        return []


def launch(
    project: str,
    issue: str,
    flow: str = "tier1",
    *,
    actor: str = "dashboard",
    allow_busy: bool = False,
    unattended: bool = False,
    config_path: Path | None = None,
) -> Outcome:
    """Create the task and dispatch it. Returns what happened, plainly."""
    try:
        config, _ = load_config(config_path)
    except ConfigError as exc:
        return Outcome(False, f"configuration is not loadable: {exc}")

    repo, error = validate(config, project, issue, flow)
    if repo is None:
        return Outcome(False, error)

    base = str(config.get("base_branch", "main"))
    problems = blocking_findings(repo, base)
    if problems:
        # Refusing here costs a second. Not refusing costs an hour and looks
        # like the model failed.
        return Outcome(False, f"{project} cannot run a loop yet: {'; '.join(problems[:2])}")

    if not allow_busy:
        live = active_runs()
        if live:
            return Outcome(
                False,
                f"{len(live)} run(s) already active ({', '.join(live[:3])}) — "
                "finish or stop them first, or launch anyway",
            )

    branch = branch_for(issue)
    lines = [f"issue: {issue}", f"repo: {repo}", f"branch: {branch}", f"flow: {flow}"]
    if unattended:
        # The runner reads this from the task body rather than from a flag
        # threaded through the worker, because the worker is a model and a
        # flag that must survive a model rewriting a command line will not.
        lines.append("unattended: true")
    body = "\n".join(lines)
    created = subprocess.run(
        [
            "hermes", "kanban", "create", f"{issue} · loop-dev",
            "--body", body,
            "--workspace", f"worktree:{repo}",
            "--branch", branch,
            "--idempotency-key", idempotency_key(issue, flow),
            "--max-retries", str(MAX_RETRIES),
            "--max-runtime", str(MAX_RUNTIME_SECONDS),
            "--assignee", ASSIGNEE,
            "--skill", SKILL,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if created.returncode != 0:
        detail = (created.stderr or created.stdout or "").strip().splitlines()
        return Outcome(False, f"board refused the task: {' / '.join(detail[-2:]) or 'no detail'}")

    task_id = _task_id(created.stdout)
    dispatched = subprocess.run(
        ["hermes", "kanban", "dispatch", "--max", "1"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    events.emit(
        task_id or f"launch-{issue}",
        "control.launch",
        issue_key=issue,
        stage="control",
        payload={
            "project": project,
            "flow": flow,
            "branch": branch,
            "actor": actor,
            "unattended": unattended,
            "dispatched": dispatched.returncode == 0,
        },
    )
    if dispatched.returncode != 0:
        # The task exists and the dispatcher will pick it up on its next
        # pass, so this is a delay rather than a failure.
        return Outcome(
            True,
            f"{issue} queued on {flow} — the dispatcher will start it shortly",
            task_id,
        )
    return Outcome(True, f"{issue} started on {flow}", task_id)


def _task_id(output: str) -> str:
    """Pull the task id out of whatever the board printed."""
    match = re.search(r"\bt_[0-9a-f]{6,}\b", output or "")
    return match.group(0) if match else ""


def options(config_path: Path | None = None) -> dict[str, Any]:
    """What the launch form offers. Read-only, so failures degrade to empty."""
    try:
        config, _ = load_config(config_path)
    except ConfigError:
        return {"projects": [], "flows": [], "default_flow": "tier1"}
    flows = config.get("flows") or {}
    return {
        "projects": sorted((config.get("repositories") or {})),
        "flows": [
            {"name": name, "description": str(value.get("description", ""))}
            for name, value in flows.items()
        ],
        # tier1 is the flow with a completed end-to-end run behind it, so it
        # is the one to offer by default rather than whatever is configured
        # as the global default.
        "default_flow": "tier1" if "tier1" in flows else str(config.get("default_flow", "")),
    }
