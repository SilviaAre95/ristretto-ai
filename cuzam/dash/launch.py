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
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from .. import events
from ..config import ConfigError, load_config, repository_path
from ..runtime import flow_interpreter, flow_script, pinned_env, runtime_identity

# Linear-style keys, which is what every configured project uses. Anything
# else is a typo, and a typo here starts an hour of work on nothing.
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{1,6}$")

# Where a run's worktree goes, matching what Hermes used to create so existing
# recovery habits (and `cuzam gc`) still find them.
WORKTREE_DIR = ".worktrees"
# How long the board holds our claim. Deliberately longer than any stage, and
# it is NOT the thing keeping a worker away — `hermes kanban heartbeat` calls
# heartbeat_worker only, which touches last_heartbeat_at and never
# claim_expires. Hermes documents the trap itself (tools/kanban_tools.py: "Without
# the heartbeat_claim half…"), and only the agent tool renews a claim. Since no
# agent runs here, the claim WILL lapse on a long run. What actually keeps a
# worker away is leaving the task unassigned — see the create call.
CLAIM_TTL_SECONDS = 14400
# The `--skill` hint written onto the card. It names the program that runs the
# task, not a Hermes skill: `loop-runner/SKILL.md` was deleted with the worker,
# and nothing reads this field — it is kept so a card created now describes
# itself the way every card before it did.
SKILL = "loop-runner"

# The model tiers a classic run may name. Mirrors run-loop.sh's own allowlist,
# including how it treats the retired `local` tier: accepted and DROPPED rather
# than rejected, because a task queued before 2026-09-23 still carries
# `model: local` in its body, and refusing it would block a relaunch rather than
# run it on the Claude default — which is the entire point of retiring the local
# coder. Drop the retired clause in 0.3.0, once no such task can be relaunched.
MODEL_TIERS = ("sonnet", "haiku", "opus")
RETIRED_TIERS = ("local",)

# Long enough for a slow build (the one measured run spent 51 minutes in a
# single stage), short enough that a wedged run does not hold a worktree
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


def classic_command(task_id: str, issue: str, flow: str, tier: str = "") -> tuple[list[str], str]:
    """(argv, unpinned warning) for the classic loop.

    The flow runs from the pinned runtime, not from whatever the launcher was
    invoked out of. The launcher is interactive and you are watching it; the flow
    is an hour of unattended work and should not execute a tree someone is
    editing. Falls back to the checkout with a warning rather than refusing, so
    an install that has not pinned a runtime yet can still dispatch — visibly
    unpinned rather than silently so.

    Its own function so the liveness contract test can build the real argv
    instead of a hand-written imitation of it. That mattered immediately: the
    test's classic fixture was written to match what the retired Hermes worker
    spawned, and it agreed with this launcher only by coincidence. Now a change
    here changes the fixture, and `cuzam/runs.py` and `scripts/live-runs.sh` are
    both asked about the result.

    Through `bash` rather than executing the script directly. Both matchers read
    the script at either argv[0] or argv[1], so this is not what makes them work
    — checked, not assumed. It matches what the retired worker spawned, and it
    survives the file arriving without its execute bit.

    What *is* load-bearing is the argument order, and the contract test fails on
    a change to it: the task id must be the first argument after the script,
    where run-loop.sh's own `shift 2` and `runs._classify` both read it, and
    `--model` must precede `--flow` because run-loop.sh enters flag parsing only
    when the first argument after that shift is one of the two.
    """
    script, unpinned = flow_script()
    command = ["bash", str(script), task_id, issue]
    if tier:
        command += ["--model", tier]
    # Named even though it is run-loop.sh's own default: the flow a surface
    # reports for a live run comes from this argv, read by `_run_loop_flow`.
    command += ["--flow", flow]
    return command, unpinned


def is_classic(config: Mapping[str, Any], flow: str) -> bool:
    """Whether this flow is the classic loop.

    Decided on the `builtin` key and never on the flow's name, so a flow called
    something unexpected cannot land on the wrong side of the two spawn shapes.

    Reads the raw mapping rather than `resolved_flow`, which resolves providers
    and credentials to answer a question about one key — and would therefore
    refuse to start a run because some unrelated provider was misconfigured.
    """
    return ((config.get("flows") or {}).get(flow) or {}).get("builtin") == "classic"


def model_tier(value: str) -> tuple[str, str]:
    """(tier, problem) for a classic run's optional model. Empty means default.

    The launcher validates it as well as run-loop.sh because an invalid tier
    makes the script exit 2 immediately, and through the launcher that is a run
    the board calls `running` with nothing running it — the caller is told the
    flow started. Refusing here costs nothing and says which tiers exist.
    """
    tier = str(value or "").strip()
    if not tier or tier in RETIRED_TIERS:
        return "", ""
    if tier not in MODEL_TIERS:
        return "", f"unknown model tier {tier!r} — expected one of: {', '.join(MODEL_TIERS)}"
    return tier, ""


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


def start_flow(
    repo: str,
    branch: str,
    task_id: str,
    issue: str,
    flow: str,
    model: str = "",
    *,
    config_path: Path | None = None,
) -> str:
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
    worker could not be relied on to.

    Every flow starts here now, `classic` included. It used to be the one
    exception: the multi-stage runner refuses it outright, so `launch` built
    `-m cuzam.runner --flow classic`, the child exited 2 a moment later, and
    because `Popen` had handed back a pid the caller was told the run started
    while the task sat claimed and `running` with nothing running it. `classic`
    reached a machine only through the dispatcher, under an agent turn. This
    finishes a migration that has been happening one function at a time.

    Two shapes, decided on the flow's `builtin` key and never on its name, so a
    flow called something unexpected cannot land on the wrong side of it.

    Claiming rather than leaving the task ready is load-bearing: an unclaimed
    task is one the dispatcher will pick up on its next pass, which would start
    a second runner on the same worktree.

    Returns a problem to report, or "" when the flow is running.
    """
    # Resolved before the claim: a flow that has since been removed from
    # cuzam.yaml is a relaunch that cannot work, and failing here leaves the
    # board untouched instead of claimed-and-dead.
    try:
        config, _ = load_config(config_path)
    except ConfigError as exc:
        return f"cannot start {flow}: {exc}"
    if flow not in (config.get("flows") or {}):
        known = ", ".join(sorted(config.get("flows") or {}))
        return f"unknown flow {flow!r} — configured flows are: {known}"
    classic = is_classic(config, flow)
    tier, bad_tier = model_tier(model)
    if bad_tier:
        return bad_tier
    if tier and not classic:
        return f"{flow} takes its models from its stages — drop --model"

    # The command too, and for the same reason: nothing may be claimed that
    # cannot be started. `bash` exists whatever happens, so spawning it at a
    # script that is not there would return a pid and report success — the exact
    # shape of the bug above, one layer down. It is reachable: the fallback is
    # this package's own directory, which holds no `hermes/` tree when the
    # package was installed rather than checked out.
    if classic:
        command, unpinned = classic_command(task_id, issue, flow, tier)
        script = Path(command[1])
        if not script.is_file():
            return (
                f"cannot start {flow}: no run-loop.sh at {script} — "
                "run `make install-runtime` to pin one"
            )
        flow_env = pinned_env()
    else:
        prefix, flow_env, unpinned = flow_interpreter()
        command = [
            *prefix, "-m", "cuzam.runner",
            "--task-id", task_id, "--issue", issue, "--flow", flow,
        ]
    if unpinned:
        print(f"launch: {unpinned}", file=sys.stderr)

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

    from .. import runs

    log_dir = runs.run_dir(worktree, task_id)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log = (log_dir / "flow.out").open("a", encoding="utf-8")
    except OSError as exc:
        return give_up(f"could not open the flow log: {exc}")

    try:
        # Its own session, so the flow outlives the CLI invocation or the Slack
        # request that started it. Nothing supervises it: a staged flow
        # heartbeats itself, a classic one does not, and the board's claim lapses
        # on a long run either way. What a surface reads is the process table.
        #
        # Detaching is right here and was wrong under the dispatcher, which is
        # the distinction the whole change rests on. Hermes supervises a task by
        # the liveness of the worker pid it spawned, and a worker that exits
        # while its task is still `running` trips the circuit breaker on the
        # FIRST occurrence — so detaching underneath it got every run marked
        # crashed about two minutes in. There is no worker now, so there is no
        # pid being counted. Taking the loop out of the dispatcher is the fix;
        # detaching under a supervisor that counts pids never was.
        process = subprocess.Popen(
            command, cwd=worktree, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
            # flow_env, not os.environ: a pinned interpreter that inherits
            # PYTHONPATH imports the development tree anyway, and PYTHONPATH is
            # exported by check.sh and run-loop.sh as a matter of course.
            # run-loop.sh exports its own from the script's location, so the
            # classic path is pinned by where the script came from.
            env={**flow_env, "PYTHONUNBUFFERED": "1"},
        )
    except OSError as exc:
        return give_up(f"could not start the flow: {exc}")
    finally:
        log.close()
    return "" if process.pid else give_up("the flow did not start")


TASK_ID = re.compile(r"^t_[0-9a-f]{6,}$")

# The contract lines `launch` writes into a task body, and the only lines
# `_task_body` reads back out of it.
BODY_KEY = re.compile(r"^\s*(issue|repo|branch|flow|model):\s*(\S+)\s*$")


def flow_is_running(task_id: str) -> bool:
    """Whether a flow process for this task is actually alive.

    Asks the operating system, not the board. The board is exactly what is
    unreliable in the situation this exists for: a run whose process died
    leaves the task `running` and claimed, which reads as healthy from every
    surface. On 2026-09-10 that state was shown as `blocked`, offered an
    `unblock` button, and restarted a run that had just passed its plan stage.

    Delegated to `cuzam.runs` rather than asking separately. This used to run
    `pgrep -f`, which matches the command line of whatever runs the search: a
    shell that merely mentions the runner reports itself as a live flow, and
    `stalled_runs` then reads a dead run as healthy — the exact inversion this
    function exists to prevent. One module now answers "what is a live run"
    for every surface, so the dashboard, the relaunch guard and `cuzam runs`
    cannot disagree about it.
    """
    if not TASK_ID.fullmatch(task_id):
        return False
    from .. import runs

    return task_id in runs.running_flows()


def stalled_runs() -> list[dict[str, str]]:
    """Runs the board still calls live but which have no process behind them.

    Broader than the `dead` health value, and deliberately so: that one is
    about `running` alone, while this answers "what could I restart", which
    includes `blocked` — the board's word for "failed and gave up".

    One snapshot for the whole fleet. This used to call `flow_is_running` per
    run, which meant a `ps` of the entire machine for every task on the
    board — tens of them, to answer a question one snapshot already had.
    """
    from .. import runs as run_data

    try:
        fleet = run_data.fleet()
    except Exception:  # noqa: BLE001 - a listing must not raise at the caller
        return []
    stalled = []
    for run in fleet:
        if run.status not in run_data.ACTIVE_STATES and run.status != "blocked":
            continue
        if run.flow_alive:
            continue
        stalled.append(
            {
                "task_id": run.task_id,
                "issue": run.issue_key or "",
                "status": run.status,
            }
        )
    return stalled


# The markers a run writes before it does anything else, one per shape.
# `run-loop.sh` writes `loop.json`; the staged runner writes `flow.json`. Both
# are read, because a run started by the launcher is only one of the two — and
# reading only `loop.json` made the pull-request check inert for every staged
# flow, including the shipped default. The docstring claimed both were read
# while the code read one, which is the kind of gap a docstring can hide.
RUN_MARKERS = ("loop.json", "flow.json")


def run_started_at(repo: str, task_id: str) -> int | None:
    """When this run began, from the marker it wrote itself, or None.

    Used to date a run against a pull request, which is the only way to tell a PR
    this run opened from one that was already on the branch.
    """
    from .. import runs

    directory = runs.run_dir(Path(repo) / WORKTREE_DIR / task_id, task_id)
    for name in RUN_MARKERS:
        marker = directory / name
        if not marker.is_file():
            continue
        try:
            started = json.loads(marker.read_text(encoding="utf-8")).get("started")
            # OverflowError, not just ValueError: a `started` of 1e400 parses as
            # float('inf') and `int()` on it raises OverflowError, which is not a
            # ValueError. An unreadable marker must return "I do not know" — this
            # is the recovery path and crashing is the one thing it must not do.
            if isinstance(started, (int, float)):
                return int(started)
        except (OSError, ValueError, OverflowError, TypeError):
            continue
    return None


def open_pull_request(repo: str, branch: str, since: int | None = None) -> str:
    """A pull request this run opened, or "".

    Inherited from the retired loop-runner skill, whose step 2 checked this
    before running anything: the loop opens its pull request as its final act, so
    a PR it opened means the work finished and the run died before reporting it.
    Restarting then pays for the whole flow again and lets a fresh `finish` stage
    push over work that is already up. The agent made this check; after the agent
    went away nothing did.

    `since` is what stops it over-reaching, and it matters because `branch_for`
    is deterministic per issue and `pin_branch_to_base` leaves an existing branch
    alone. A second run on the same issue therefore inherits the first run's
    branch — and its still-open pull request, since pull requests here are merged
    by hand and stay open for a while. Keyed on the branch alone, that second run
    could never be relaunched, and the refusal would tell the operator to
    complete a task that had done no work. So only a pull request newer than this
    run counts as this run's.

    Best effort in one direction only, and that is deliberate on both counts:
    `gh` missing, unauthenticated or offline returns "", and so does a run with
    no recorded start. Refusing to restart on an unanswered question is the worse
    of the two failures.
    """
    if not branch or since is None:
        return ""
    try:
        found = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "all",
             "--json", "url,createdAt,state"],
            cwd=repo, capture_output=True, text=True, check=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if found.returncode != 0:
        return ""
    try:
        listed = json.loads(found.stdout or "[]")
    except ValueError:
        return ""
    if not isinstance(listed, list):
        return ""
    for entry in listed:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "")
        if not url.startswith("http"):
            continue
        # A closed-unmerged pull request is work somebody rejected, so it must
        # not block a restart — and it would block it forever, because the branch
        # is deterministic per issue and stays the newest PR on that head. Open
        # and merged both mean the flow has nothing left to do; `--state all`
        # without this filter refused all three alike.
        if str(entry.get("state") or "").upper() not in ("OPEN", "MERGED"):
            continue
        try:
            # `gh` prints RFC 3339 in UTC; fromisoformat handles the Z from 3.11.
            opened = int(
                datetime.fromisoformat(
                    str(entry.get("createdAt") or "").replace("Z", "+00:00")
                ).timestamp()
            )
        except ValueError:
            continue
        if opened >= since:
            return url
    return ""


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

    Refuses outright when the branch already has a pull request — that means the
    run finished and died before reporting, and the flow has nothing left to do.
    The retired loop-runner skill made that check before running anything.

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

    # Checked again on the way back in, because `launch` validated these and this
    # path did not. Nothing here reaches a shell — every call is an argv list —
    # but `repo` becomes a subprocess working directory and the base of a path
    # that gets read, and `issue` reaches the model's prompt. The board is local
    # and ours, so this is depth rather than a hole; the asymmetry is the part
    # worth removing, since a reader would reasonably assume both paths validate.
    if not ISSUE_KEY.fullmatch(issue):
        return Outcome(False, f"{task_id}: {issue!r} in the task body is not an issue key", task_id)
    if not Path(repo).is_dir():
        return Outcome(False, f"{task_id}: {repo} is not there any more", task_id)

    already = open_pull_request(repo, branch, run_started_at(repo, task_id))
    if already:
        return Outcome(
            False,
            f"{issue} already has a pull request: {already} — the run finished and "
            "died before reporting it. Review the PR and complete the task with "
            f"`hermes kanban complete {task_id}`; relaunching would pay for the "
            "whole flow again and push over work that is already up",
            task_id,
        )

    # Return it to ready so the claim inside start_flow can take it cleanly.
    subprocess.run(
        ["hermes", "kanban", "reclaim", task_id, "--reason", "relaunch"],
        capture_output=True, text=True, check=False, timeout=120,
    )
    subprocess.run(
        ["hermes", "kanban", "unblock", task_id],
        capture_output=True, text=True, check=False, timeout=120,
    )
    problem = start_flow(
        repo, branch, task_id, issue, flow, body.get("model", ""), config_path=config_path
    )
    events.emit(
        task_id, "control.launch", issue_key=issue, stage="control",
        payload={"flow": flow, "branch": branch, "relaunch": True,
                 "model": body.get("model", ""), "dispatched": not problem},
    )
    if problem:
        return Outcome(False, f"{issue} did not restart: {problem}", task_id)
    return Outcome(True, f"{issue} restarted on {flow} (from plan)", task_id)


def _task_body(task_id: str) -> dict[str, str]:
    """The `key: value` lines `launch` wrote into the task body.

    Read from `--json`, where the body is its own field, rather than scraped out
    of the human listing. Two attempts at the latter were wrong in opposite
    directions: scanning every line also matched the header block, which repeats
    `branch:` (harmlessly, same value) and carries a `model:` line that is a
    provider model id rather than one of our tiers — enough to make an otherwise
    restartable run unrelaunchable. Skipping to a line spelled exactly `Body:`
    fixed that and created a worse failure: a heading that is ever absent,
    reworded or indented would yield nothing at all, and *every* relaunch would
    report "the task body does not say what to run". Nothing exercised it,
    because every test patches this function.

    The field has no header to collide with and no heading to find.
    `cuzam/runs.py` already reads it this way — `_body_field` — so this is the
    convention rather than a new idea.
    """
    shown = subprocess.run(
        ["hermes", "kanban", "show", "--json", task_id],
        capture_output=True, text=True, check=False, timeout=120,
    )
    try:
        payload = json.loads(shown.stdout or "")
    except ValueError:
        return {}
    task = payload.get("task", payload) if isinstance(payload, dict) else {}
    body = str((task or {}).get("body") or "")
    found: dict[str, str] = {}
    for line in body.splitlines():
        match = BODY_KEY.match(line)
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
    config: Mapping[str, Any], project: str, issue: str, flow: str, model: str = ""
) -> tuple[Path | None, str]:
    """Check the request before anything is spent. Returns (repo, error)."""
    if not ISSUE_KEY.fullmatch(issue or ""):
        return None, f"{issue!r} is not an issue key (expected something like {example_key(config)})"
    if flow not in (config.get("flows") or {}):
        known = ", ".join(sorted(config.get("flows") or {}))
        return None, f"unknown flow {flow!r} — configured flows are: {known}"
    tier, bad_tier = model_tier(model)
    if bad_tier:
        return None, bad_tier
    # A staged flow's models come from its stages. Accepting a tier and ignoring
    # it would read as honoured by whoever asked for it.
    if tier and not is_classic(config, flow):
        return None, f"{flow} takes its models from its stages — drop --model"
    try:
        repo = repository_path(config, project)
    except ConfigError as exc:
        return None, str(exc)
    if not repo.is_dir():
        return None, f"{project} is configured but {repo} is not there"
    return repo, ""


def unchecked_findings(repo: Path, base: str) -> list[str]:
    """What preflight declined to answer, as plain sentences.

    Reported, never blocking. The incident this exists for was a *launch*: a
    repo whose verify gate had been red for weeks looked ready, so a run would
    have spent every stage before dying at `verify` on a breakage that predated
    it. Running the gate here would cost minutes on every launch, so the launch
    says what it does not know and lets the operator decide.
    """
    from ..preflight import preflight

    return [f.message for f in preflight(repo, base, deep=False) if f.level == "UNKNOWN"]


def blocking_findings(repo: Path, base: str) -> list[str]:
    """Preflight problems that should stop a launch, as plain sentences."""
    from ..preflight import fast_findings

    # .message, not str(f): __str__ prefixes the level, which would read
    # "cannot run a loop yet: ERROR ...".
    return [f.message for f in fast_findings(repo, base) if f.level == "ERROR"]


def active_runs() -> list[str]:
    """Task ids the board considers live, newest first."""
    from .. import runs as run_data

    try:
        return [
            run.task_id
            for run in run_data.fleet()
            if run.status in run_data.ACTIVE_STATES
        ]
    except Exception:  # noqa: BLE001 - a busy check must not block a launch
        return []


def launch(
    project: str,
    issue: str,
    flow: str = "",
    model: str = "",
    *,
    actor: str = "dashboard",
    allow_busy: bool = False,
    unattended: bool = False,
    config_path: Path | None = None,
) -> Outcome:
    """Create the task and dispatch it. Returns what happened, plainly.

    An empty flow means "whatever is configured". Every caller — the CLI, the
    Slack plugin, the assistant, the launch form — used to carry its own
    default, which is how they came to disagree: the form offered tier1 while
    cuzam.yaml said classic, and nothing reported the difference.
    """
    try:
        config, _ = load_config(config_path)
    except ConfigError as exc:
        return Outcome(False, f"configuration is not loadable: {exc}")

    # str(... or "") rather than .strip(): the tool schema says "omit for the
    # configured default", which invites a model to send an explicit null.
    flow = str(flow or "").strip() or str(config.get("default_flow", ""))
    repo, error = validate(config, project, issue, flow, model)
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
    tier, _ = model_tier(model)
    if tier:
        # In the body, not only on the command line, so a relaunch runs what the
        # first attempt ran rather than quietly dropping to the Claude default.
        lines.append(f"model: {tier}")
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
    problem = start_flow(repo, branch, task_id, issue, flow, tier, config_path=config_path)
    events.emit(
        task_id or f"launch-{issue}",
        "control.launch",
        issue_key=issue,
        stage="control",
        payload={
            "project": project,
            "flow": flow,
            "model": tier,
            "branch": branch,
            "actor": actor,
            "unattended": unattended,
            "dispatched": not problem,
            # Which copy of Cuzam this flow runs, recorded where the
            # board can show it rather than only in the worktree artifact.
            "runtime": runtime_identity(),
        },
    )
    if problem:
        # The task exists and is claimed by us, but nothing is running it. Say
        # so plainly rather than leaving a card that looks queued: nothing will
        # pick this up, because claiming it is what keeps the dispatcher away.
        return Outcome(False, f"{issue} did not start: {problem}", task_id)
    started = f"{issue} started on {flow}"
    notes = []
    # The docs promise a launch "says so" when unpinned. On stderr that is a
    # service log nobody reads — the dashboard and the Slack plugin both show
    # Outcome.message and nothing else.
    #
    # Asked of whichever pin this run actually depends on. A classic run is
    # pinned by the script and never touches the pinned interpreter, so reporting
    # the interpreter's state would tell the operator their run is unpinned when
    # it is not — a runtime whose venv is broken but whose tree is intact is
    # exactly that case.
    if is_classic(config, flow):
        _, unpinned_note = flow_script()
    else:
        _, _, unpinned_note = flow_interpreter()
    if unpinned_note:
        notes.append(unpinned_note)
    notes.extend(unchecked_findings(repo, base)[:1])
    if notes:
        started += " — " + "; ".join(notes)
    return Outcome(True, started, task_id)


def _task_id(output: str) -> str:
    """Pull the task id out of whatever the board printed."""
    match = re.search(r"\bt_[0-9a-f]{6,}\b", output or "")
    return match.group(0) if match else ""


def options(config_path: Path | None = None) -> dict[str, Any]:
    """What the launch form offers. Read-only, so failures degrade to empty."""
    try:
        config, _ = load_config(config_path)
    except ConfigError:
        return {"projects": [], "flows": [], "default_flow": "full"}
    flows = config.get("flows") or {}
    return {
        "projects": sorted((config.get("repositories") or {})),
        "flows": [
            {"name": name, "description": str(value.get("description", ""))}
            for name, value in flows.items()
        ],
        # The configured default, not a hardcoded preference. This used to
        # name tier1 directly, on the reasoning that it was the flow with a
        # completed end-to-end run behind it — which meant the form and
        # cuzam.yaml could disagree and nothing would say so.
        "default_flow": str(config.get("default_flow", "")),
    }
