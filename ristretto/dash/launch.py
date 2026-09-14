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

import os
import re
import subprocess
import sys
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
# Where a run's worktree goes, matching what Hermes used to create so existing
# recovery habits (and `ristretto gc`) still find them.
WORKTREE_DIR = ".worktrees"
# How long the board holds our claim. Deliberately longer than any stage, and
# it is NOT the thing keeping a worker away — `hermes kanban heartbeat` calls
# heartbeat_worker only, which touches last_heartbeat_at and never
# claim_expires. Hermes documents the trap itself (tools/kanban_tools.py: "Without
# the heartbeat_claim half…"), and only the agent tool renews a claim. Since no
# agent runs here, the claim WILL lapse on a long run. What actually keeps a
# worker away is leaving the task unassigned — see the create call.
CLAIM_TTL_SECONDS = 14400
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


def pin_branch_to_base(repo: str, branch: str, base: str) -> str:
    """Create the run's branch at origin/<base> before the worktree exists.

    Hermes creates the worktree with `git worktree add`, and when the branch
    does not exist yet it cuts one from whatever the repo checkout has checked
    out. That is a landmine for anyone who leaves a feature branch selected: on
    2026-09-10 a kaffecard run branched off an unrelated permissions commit and
    its pull request would have carried both changes. `git reflog` recorded it
    flatly as "branch: Created from HEAD".

    The workaround was already written down — durable-dev's skill says to
    pre-create the branch from origin/main — but a manual step in one skill is
    not a guarantee, and the launcher is the one place that knows it is about
    to dispatch. Fetch first, because pinning to a stale origin/<base> just
    picks a different wrong commit.

    Returns a problem for the caller to report, or "" when the branch is ready.
    An existing branch is left alone: relaunching an issue must not silently
    discard the commits a previous attempt preserved.
    """
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, check=False, timeout=300,
        )

    if git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        return ""
    if git("fetch", "--quiet", "origin", base).returncode != 0:
        return f"could not fetch origin/{base}"
    target = git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{base}")
    if target.returncode != 0:
        return f"origin/{base} does not exist"
    created = git("branch", branch, (target.stdout or "").strip())
    if created.returncode != 0:
        detail = (created.stderr or "").strip().splitlines()
        return f"could not create {branch}: {detail[-1] if detail else 'git branch failed'}"
    return ""


def start_flow(repo: str, branch: str, task_id: str, issue: str, flow: str) -> str:
    """Claim the task, cut its worktree, and run the flow as a plain process.

    Why not hand it to a worker: a Hermes task is always assigned to an agent
    profile — `kanban create` takes `--assignee`, and there is no command task
    — so dispatching means a language model is the thing that runs the script
    and waits for it. That job needs no judgement, and on 2026-09-10 the
    judgement is exactly what went wrong: across four attempts on one issue the
    worker abandoned one run and killed two more, reading a silent stage as a
    hang, twice while quoting back the instruction telling it not to.

    Hermes' own supervision is fine — it leases a claim, watches a pid and
    expects a heartbeat, all of it deterministic. The mismatch was putting
    deterministic work inside an agent turn. So keep the board and take the
    claim ourselves: the runner already heartbeats (`Heartbeat`) and already
    reports its own outcome (`report_outcome`), both written because the
    worker could not be relied on to. This finishes a migration that has been
    happening one function at a time.

    Claiming rather than leaving the task ready is load-bearing: an unclaimed
    task is one the dispatcher will pick up on its next pass, which would start
    a second runner on the same worktree.

    Returns a problem to report, or "" when the flow is running.
    """
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, check=False, timeout=300,
        )

    claimed = subprocess.run(
        ["hermes", "kanban", "claim", task_id, "--ttl", str(CLAIM_TTL_SECONDS)],
        capture_output=True, text=True, check=False, timeout=120,
    )
    if claimed.returncode != 0:
        detail = (claimed.stderr or claimed.stdout or "").strip().splitlines()
        return f"could not claim the task: {detail[-1] if detail else 'no detail'}"

    def give_up(problem: str) -> str:
        """Release the claim before reporting, so the board is not left lying.

        Every exit after the claim used to leave the task `running` with
        nothing running it. `active_runs` counts `running`, so one failed
        launch refused every later launch until the TTL lapsed — and a
        dead-but-claimed task is also exactly what makes a run unrelaunchable.
        """
        subprocess.run(
            ["hermes", "kanban", "reclaim", task_id, "--reason", problem[:200]],
            capture_output=True, text=True, check=False, timeout=120,
        )
        return problem

    worktree = Path(repo) / WORKTREE_DIR / task_id
    if not worktree.exists():
        added = git("worktree", "add", "--quiet", str(worktree), branch)
        if added.returncode != 0:
            detail = (added.stderr or "").strip().splitlines()
            return give_up(
                f"could not create the worktree: {detail[-1] if detail else 'git failed'}"
            )

    log_dir = worktree / ".ristretto" / "runs" / task_id
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log = (log_dir / "flow.out").open("a", encoding="utf-8")
    except OSError as exc:
        return give_up(f"could not open the flow log: {exc}")

    # sys.executable for the same reason the broker uses it: whatever is first
    # on a PATH usually cannot import ristretto.
    command = [
        sys.executable, "-m", "ristretto.runner",
        "--task-id", task_id, "--issue", issue, "--flow", flow,
    ]
    try:
        # Its own session, so the flow outlives the CLI invocation or the Slack
        # request that started it. Nothing supervises it but the board's lease
        # and the heartbeat the runner sends itself.
        process = subprocess.Popen(
            command, cwd=worktree, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except OSError as exc:
        return give_up(f"could not start the flow: {exc}")
    finally:
        log.close()
    return "" if process.pid else give_up("the flow did not start")


TASK_ID = re.compile(r"^t_[0-9a-f]{6,}$")


def flow_is_running(task_id: str) -> bool:
    """Whether a flow process for this task is actually alive.

    Asks the operating system, not the board. The board is exactly what is
    unreliable in the situation this exists for: a run whose process died
    leaves the task `running` and claimed, which reads as healthy from every
    surface. On 2026-09-10 that state was shown as `blocked`, offered an
    `unblock` button, and restarted a run that had just passed its plan stage.
    """
    if not TASK_ID.fullmatch(task_id):
        return False
    found = subprocess.run(
        ["pgrep", "-f", f"ristretto.runner --task-id {task_id}"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    return found.returncode == 0


def stalled_runs() -> list[dict[str, str]]:
    """Runs the board still calls live but which have no process behind them."""
    from . import data

    try:
        fleet = data.fleet()
    except Exception:  # noqa: BLE001 - a listing must not raise at the caller
        return []
    stalled = []
    for run in fleet:
        if run.status not in data.ACTIVE_STATES and run.status != "blocked":
            continue
        if flow_is_running(run.task_id):
            continue
        stalled.append(
            {
                "task_id": run.task_id,
                "issue": getattr(run, "issue_key", "") or "",
                "status": run.status,
            }
        )
    return stalled


def relaunch(target: str = "", config_path: Path | None = None) -> Outcome:
    """Start a dead run again, in the worktree and branch it already has.

    A run that dies now stays dead: removing the worker removed Hermes'
    retry-on-crash with it. That is the right trade — the retries observed on
    2026-09-10 each burned a fresh Opus plan stage and were killed the same way
    — but only if restarting is actually possible, and it was not: the
    idempotency key is scoped to a day, so `launch` refuses the same issue and
    flow until midnight, and a dead-but-claimed task counts as active, so it
    refuses on that too.

    Resumes the flow, not the stage: it starts again at `plan`. Anything the
    dead run committed through `preserve_work` is still on the branch, so
    nothing is lost, but the earlier stages are paid for again.

    `target` may be a task id, an issue key, or nothing at all — the last is
    the common case, because the situation is nearly always "the thing I just
    started died".
    """
    stalled = stalled_runs()
    if not stalled:
        # "Nothing to relaunch" and "it is still running" are different
        # answers, and conflating them is how someone restarts a healthy run.
        running = [task for task in active_runs() if flow_is_running(task)]
        if running:
            return Outcome(
                False,
                f"nothing is stalled — {', '.join(running)} still running; "
                "stop it first if you want it restarted",
            )
        return Outcome(False, "no run to relaunch")

    if target:
        wanted = target.strip()
        matches = [
            run for run in stalled
            if run["task_id"] == wanted or run["issue"].upper() == wanted.upper()
        ]
        if not matches:
            names = ", ".join(f"{r['issue'] or '?'} ({r['task_id']})" for r in stalled)
            return Outcome(False, f"no stalled run matching {wanted} — found: {names}")
        chosen = matches[0]
    elif len(stalled) == 1:
        chosen = stalled[0]
    else:
        # Same rule the approvals CLI follows: acting without an id is only
        # safe when there is exactly one thing it could mean.
        names = ", ".join(f"{r['issue'] or '?'} ({r['task_id']})" for r in stalled)
        return Outcome(False, f"{len(stalled)} stalled runs — name one: {names}")

    task_id = chosen["task_id"]
    body = _task_body(task_id)
    repo, issue, flow, branch = body.get("repo"), body.get("issue"), body.get("flow"), body.get("branch")
    if not (repo and issue and flow and branch):
        return Outcome(False, f"{task_id}: the task body does not say what to run", task_id)

    # Return it to ready so the claim inside start_flow can take it cleanly.
    subprocess.run(
        ["hermes", "kanban", "reclaim", task_id, "--reason", "relaunch"],
        capture_output=True, text=True, check=False, timeout=120,
    )
    subprocess.run(
        ["hermes", "kanban", "unblock", task_id],
        capture_output=True, text=True, check=False, timeout=120,
    )
    problem = start_flow(repo, branch, task_id, issue, flow)
    events.emit(
        task_id, "control.launch", issue_key=issue, stage="control",
        payload={"flow": flow, "branch": branch, "relaunch": True,
                 "dispatched": not problem},
    )
    if problem:
        return Outcome(False, f"{issue} did not restart: {problem}", task_id)
    return Outcome(True, f"{issue} restarted on {flow} (from plan)", task_id)


def _task_body(task_id: str) -> dict[str, str]:
    """The `key: value` lines `launch` wrote into the task body."""
    shown = subprocess.run(
        ["hermes", "kanban", "show", task_id],
        capture_output=True, text=True, check=False, timeout=120,
    )
    found: dict[str, str] = {}
    for line in (shown.stdout or "").splitlines():
        match = re.match(r"^\s*(issue|repo|branch|flow):\s*(\S+)\s*$", line)
        if match:
            found.setdefault(match.group(1), match.group(2))
    return found


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
    # Before the board is told anything: a run that starts from the wrong
    # commit is worse than one that does not start, because its pull request
    # looks legitimate.
    misbased = pin_branch_to_base(repo, branch, base)
    if misbased:
        return Outcome(False, f"{project} cannot start a clean branch: {misbased}")
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
            # Deliberately unassigned. `_cmd_dispatch` only considers a task
            # where `status == "ready" and task.assignee`, so an unassigned
            # task cannot be handed to an agent — which is the whole point,
            # and the only barrier that holds for a run longer than the claim.
            # A claim alone would not: it lapses, the task returns to ready,
            # and a dispatcher tick would put a second runner in the live
            # worktree.
            #
            # One way this could silently come back: setting
            # `kanban.default_assignee`, which _cmd_dispatch honours as a
            # fallback for unassigned ready tasks. It is unset today.
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
    if not task_id:
        # The task exists but we cannot address it, so we can neither claim it
        # nor start it. It is unassigned, so nothing will pick it up either —
        # say so rather than leaving the caller to wonder.
        return Outcome(
            False,
            "the board created a task but did not name it — nothing will run it; "
            "find it with `hermes kanban list` and archive it",
        )
    problem = start_flow(repo, branch, task_id, issue, flow)
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
            "dispatched": not problem,
        },
    )
    if problem:
        # The task exists and is claimed by us, but nothing is running it. Say
        # so plainly rather than leaving a card that looks queued: nothing will
        # pick this up, because claiming it is what keeps the dispatcher away.
        return Outcome(False, f"{issue} did not start: {problem}", task_id)
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
