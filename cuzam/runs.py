"""What a run is: alive or dead, where it lives, and which pids are its own.

One module, because there used to be three and they disagreed. `live-runs.sh`
asked the process table, `dash/data.py` asked it differently, and
`launch.flow_is_running` ran `pgrep -f` and matched itself. None of the three
could see a classic loop at all, so a healthy `run-loop.sh` read as dead from
every Python surface while a staged run whose process had died read as healthy
for fifteen minutes.

The bash one stays, deliberately. `install-runtime.sh` consults it while
rebuilding the Python environment, and a guard that imports the package to
decide whether it may replace the package is the circularity it exists to
prevent. `live_runs_contract_test.py` pins the two against each other instead.

**Nothing here assumes a web framework, a request, a template or a session.**
The fleet view and `cuzam runs` are renderers over this; a third renderer —
a tab in Hermes' dashboard, or something later — should be a rendering job
rather than a re-implementation. If a surface needs to compute a fact about a
run, the fact belongs here.

**Nothing here writes anything.** Not to the board, not to a process. Showing
that a run is dead is the whole of what this does about it: on 2026-09-10 a
surface that could not tell alive from dead restarted a run that had just
passed its plan stage, and a surface that *can* tell must still not be the
thing that acts.

Liveness derives from the age of the newest signal we actually have — a Cuzam
event, or the run's start — plus the process table. Hermes' CLI does not
expose `last_heartbeat_at`, so the heartbeat rule the original spec wanted
cannot be implemented from a supported interface, and every surface says which
signal it used rather than implying one it never saw.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import events

# Same shape zam-stop.sh enforces before it will act on an id.
SAFE_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
# A run with no news for this long, still claiming to be active, is reported
# as stalled rather than healthy. Silence is the failure mode that cost two
# tasks a month apiece.
STALL_AFTER_SECONDS = 15 * 60
# Finished work older than this is history, not fleet status.
RECENT_WINDOW_SECONDS = 7 * 24 * 3600
ACTIVE_STATES = frozenset({"running", "ready", "review", "todo", "triage"})
LIVE_STATES = ACTIVE_STATES | {"blocked", "scheduled"}

# Cuzam's own run artifacts are not the flow's work product. Declared here
# rather than in the runner because this module is the cheap import and the
# runner is not — and because .gitignore moves in lockstep with this name,
# which is what a second copy of it would break. That divergence was XARI-130,
# run artifacts committed into pull requests.
#
# Not to be confused with `~/.cuzam`, which is the state home. The two share a
# spelling and nothing else: one is per-worktree and gitignored, the other is
# per-machine and holds the event log and the approvals store.
ARTIFACT_DIR_NAME = ".cuzam"

# The log a run writes, most authoritative first. `launch` opens `flow.out`;
# `run-loop.sh` tees a staged flow into `loop.log`. A classic loop keeps
# Claude's output in a mktemp file that is gone by the time anyone looks, so
# it has neither — and a path that does not exist is not reported.
LOG_NAMES = ("flow.out", "loop.log")

# The two process shapes, which cover three flows. Keying on shape rather than
# on the flow's name is what makes `classic`, `full` and `short` two cases
# instead of three, and what stops a fourth flow falling outside this
# silently — a staged flow is a staged flow whatever it is called.
CLASSIC_SCRIPT = "loop-runner/scripts/run-loop.sh"
# Both module names, for one release, matching what live-runs.sh already does.
# A flow started before the rename is executing `-m ristretto.runner` and keeps
# that command line for its whole hour; seeing only the new name would report
# a live run as dead, which is the exact inversion this module exists to stop.
# Drop the old name in 0.3.0, once no run can predate the rename.
RUNNER_MODULES = ("cuzam.runner", "ristretto.runner")
# The same program reached by its console script rather than by `-m`.
# `pyproject.toml` ships it, `runner.py` sets `prog` to it, so it is a
# supported way to start a run — and it carries no `-m` on its command line.
# Missing it did not merely hide the run: the board still called it `running`,
# so it rendered as dead with an invitation to relaunch, while
# `install-runtime.sh` rebuilt the runtime underneath it.
RUNNER_SCRIPTS = ("cuzam-run-flow",)
_SHELLS = {"sh", "bash", "zsh"}


@dataclass(frozen=True)
class Process:
    """A live run as the operating system describes it."""

    task_id: str
    pid: int
    shape: str  # "classic" | "staged"
    flow: str | None
    command: str


@dataclass
class Run:
    """Everything a surface needs about one run. The documented return shape.

    A surface renders these fields. It does not go back to `kanban show
    --json`, to `ps`, or to the pid records for anything not here; if
    something is missing, add it here so every surface gains it at once.
    """

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
    failure: str | None = None
    events: list[Mapping[str, Any]] = field(default_factory=list)

    # Locators. Every one of these comes from something that recorded it, not
    # from a rule about what it ought to be.
    worktree: Path | None = None
    flow: str | None = None
    shape: str | None = None
    runner_pid: int | None = None
    claude_pid: int | None = None
    # Whether the process table could be read at all. A missing answer is not
    # the answer "no": with this False, `dead` is never claimed, because the
    # evidence for it is exactly the evidence that is missing.
    liveness_known: bool = True

    @property
    def flow_alive(self) -> bool:
        """Whether a process for this run exists right now.

        A property rather than a field so there is no way to set it to
        something the process table does not agree with.
        """
        return self.runner_pid is not None

    @property
    def _artifact_path(self) -> Path | None:
        """Where this run's artifacts would go. Not a locator — see below."""
        if not self.worktree:
            return None
        return run_dir(self.worktree, self.task_id)

    @property
    def artifact_dir(self) -> Path | None:
        """This run's artifact directory, when there is one on disk.

        A path is offered only once something is at the end of it. The rule
        was written for the log file and then broken one line below it for the
        directory: `cuzam gc` reclaims a finished worktree, so a run whose
        card is still on the board routinely has neither, and both surfaces
        were printing a directory to go and look in that had never existed.
        """
        directory = self._artifact_path
        try:
            return directory if directory and directory.is_dir() else None
        except OSError:
            return None

    @property
    def worktree_gone(self) -> bool:
        """The board remembers a worktree that is no longer on disk.

        Kept rather than blanked: where a run *was* is still the useful answer
        after `cuzam gc` has reclaimed it, as long as nothing pretends it is
        still there to be `cd`'d into.
        """
        if not self.worktree:
            return False
        try:
            return not self.worktree.is_dir()
        except OSError:
            return False

    @property
    def log(self) -> Path | None:
        """The log file that exists, or nothing.

        Reporting `<worktree>/.cuzam/runs/<task>/flow.out` because that is
        where a log *would* be is the derivation this module refuses: it reads
        as an instruction to tail a file, and a classic run never writes one.
        """
        directory = self._artifact_path
        if not directory:
            return None
        for name in LOG_NAMES:
            candidate = directory / name
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    @property
    def health(self) -> str:
        """running | dead | stalled | blocked | failed | done | idle"""
        if self.status == "blocked":
            return "blocked"
        if self.status in {"done", "archived"}:
            return "failed" if self.failure else "done"
        if self.status not in ACTIVE_STATES:
            return "idle"
        # A quiet run with a live process is working, not stalled. A build
        # stage emits nothing between its start and its finish and can
        # legitimately run the better part of an hour.
        if self.flow_alive:
            return "running"
        # Claimed and started, with nothing behind it. This is a fact, not the
        # guess that `stalled` is, and it is reported immediately rather than
        # after fifteen minutes of reading as healthy — but only when the
        # process table was actually read. Unread, this falls through to the
        # signal-age guess below, which is what the surfaces did before there
        # was a `dead` at all.
        if self.status == "running" and self.liveness_known:
            return "dead"
        # Every other active state is a task that never started a process, so
        # its absence proves nothing. Only silence is left to go on.
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

    def as_dict(self) -> dict[str, Any]:
        """The shape a machine reads. Paths as strings, nothing derived."""
        return {
            "task_id": self.task_id,
            "issue_key": self.issue_key,
            "title": self.title,
            "project": self.project,
            "status": self.status,
            "health": self.health,
            "alive": self.flow_alive,
            "liveness_known": self.liveness_known,
            "flow": self.flow,
            "shape": self.shape,
            "stage": self.stage,
            "branch": self.branch,
            "worktree": str(self.worktree) if self.worktree else None,
            "worktree_gone": self.worktree_gone,
            "artifact_dir": str(self.artifact_dir) if self.artifact_dir else None,
            "log": str(self.log) if self.log else None,
            "runner_pid": self.runner_pid,
            "claude_pid": self.claude_pid,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed": self.elapsed,
            "last_signal_at": self.last_signal_at,
            "signal_source": self.signal_source,
            "age_of_signal": self.age_of_signal,
            "failure": self.failure,
        }


def run_dir(worktree: Path, task_id: str) -> Path:
    """Where one run's artifacts live inside its worktree.

    One builder, because there were three: the runner spelled the path out by
    hand beside its own `ARTIFACT_DIR_NAME` constant, `launch` spelled it out
    again to open the flow log, and a reader had to spell it a third time to
    find either. Three copies of a path are three chances for a surface to
    point at a directory nothing writes to.
    """
    return Path(worktree) / ARTIFACT_DIR_NAME / "runs" / task_id


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


def _ps(timeout: int) -> list[tuple[int, str]] | None:
    """One snapshot of every process, as (pid, command). `None` if unreadable.

    Snapshot first and filter here, rather than `pgrep -f`: a pattern search
    matches the command line of whatever runs the search, so any shell
    mentioning `cuzam.runner --task-id` — including a monitor watching for
    one — reports itself as a live flow. Capturing the listing before the
    filter exists is what keeps the filter out of its own results.

    `None` rather than an empty list, and the distinction is the whole point.
    This used to swallow every failure into `[]`, which downstream is
    indistinguishable from a quiet machine — so one `ps` that timed out under
    load made `health` call every claimed run `dead`, and both surfaces told
    the operator to relaunch a fleet that was working. An absent answer is not
    the answer "no".
    """
    try:
        listing = subprocess.run(
            ["ps", "-eo", "pid=,command="],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if listing.returncode != 0:
        return None
    rows = []
    for line in listing.stdout.splitlines():
        head, _, command = line.strip().partition(" ")
        if not head.isdigit() or not command:
            continue
        rows.append((int(head), command.strip()))
    return rows


def _flag(argv: list[str], name: str) -> str | None:
    """The value after `--name`, or nothing."""
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return None


def _run_loop_flow(rest: list[str]) -> str:
    """The flow a classic invocation names, read the way run-loop.sh reads it.

    Mirrors its own parser rather than looking for `--flow`, because it also
    accepts the flow positionally — `run-loop.sh TASK ISSUE sonnet full` is a
    `full` run with no flag on its command line, and guessing `classic` from
    the flag's absence labelled it wrongly on every surface, overriding the
    task body that said otherwise.
    """
    if rest and rest[0] in ("--model", "--flow"):
        return _flag(rest, "--flow") or "classic"
    return rest[1] if len(rest) > 1 else "classic"


def _classify(pid: int, command: str) -> Process | None:
    """Which run, if any, this process is."""
    argv = command.split()
    if not argv:
        return None

    # Classic. The script must be what is executing, not merely named on some
    # other command line: it is reached either through a shell or by its
    # shebang, so it is the first or the second word. Its task id is the first
    # argument after it, which is where run-loop.sh reads it from.
    for position in (0, 1):
        if position < len(argv) and argv[position].endswith(CLASSIC_SCRIPT):
            task_id = argv[position + 1] if position + 1 < len(argv) else ""
            if not SAFE_TASK_ID.fullmatch(task_id or ""):
                return None
            return Process(
                task_id=task_id,
                pid=pid,
                shape="classic",
                flow=_run_loop_flow(argv[position + 3:]),
                command=command,
            )

    # Staged, reached by its console script: no `-m`, nothing to scan for.
    if Path(argv[0]).name in RUNNER_SCRIPTS and "--task-id" in argv:
        task_id = _flag(argv, "--task-id") or ""
        if SAFE_TASK_ID.fullmatch(task_id):
            return Process(
                task_id=task_id, pid=pid, shape="staged",
                flow=_flag(argv, "--flow"), command=command,
            )
        return None

    # Staged. Mentioning the runner is not running it, and the mention can
    # come from something that is not a shell: a `python -c` whose source text
    # names the module splits into an argv containing `-m cuzam.runner
    # --task-id` and reads as a live run. That is the pgrep failure in another
    # costume, so the interpreter must genuinely have been handed the module —
    # `-m` as its own argument, the module immediately after it, and no `-c`
    # ahead of it, because a real run has neither.
    if "-m" not in argv or "--task-id" not in argv:
        return None
    if Path(argv[0]).name in _SHELLS:
        return None
    # Every `-m` before the first `-c`, not only the first `-m`: the awk in
    # live-runs.sh scans them all, and an implementation that stopped at the
    # first would answer differently from the guard the installer trusts.
    handed_the_module = False
    for index, word in enumerate(argv):
        if word == "-c":
            break
        if word == "-m" and index + 1 < len(argv) and argv[index + 1] in RUNNER_MODULES:
            handed_the_module = True
            break
    if not handed_the_module:
        return None
    task_id = _flag(argv, "--task-id") or ""
    if not SAFE_TASK_ID.fullmatch(task_id):
        return None
    return Process(
        task_id=task_id,
        pid=pid,
        shape="staged",
        flow=_flag(argv, "--flow"),
        command=command,
    )


def live_processes(timeout: int = 10) -> list[Process]:
    """Every coding run alive on this machine, by process shape.

    The single answer to "what is a live run" on the Python side. `live-runs.sh`
    answers the same question in bash for the installer, and the contract test
    is what keeps the two saying the same thing.
    """
    return [
        process
        for process in (_classify(pid, command) for pid, command in (_ps(timeout) or []))
        if process
    ]


def running_flows(timeout: int = 10) -> set[str]:
    """Task ids with a live run process on this machine.

    Event age alone is a poor liveness test: a build stage emits nothing
    between its start and its finish and legitimately runs for the better part
    of an hour, so a healthy run reads as stalled. Every surface is on the same
    machine as the runner, so it can ask instead of inferring.
    """
    return {process.task_id for process in live_processes(timeout)}


def _pid_record(task_id: str) -> dict[str, Any]:
    """What `run-loop.sh` wrote about the Claude child it spawned.

    Ours, not Hermes': `run-loop.sh` writes it and `reap.sh` reads and removes
    it. It lives under `~/.hermes/` because that is where the board's own
    per-task state lives, and deliberately outside the worktree so the policed
    process cannot author its own reaping record.
    """
    board = os.environ.get("HERMES_KANBAN_BOARD", "default")
    if not SAFE_TASK_ID.fullmatch(task_id) or not SAFE_TASK_ID.fullmatch(board):
        return {}
    record = Path.home() / ".hermes" / "kanban" / board / "pids" / f"{task_id}.json"
    try:
        loaded = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def claude_child(task_id: str, commands: Mapping[int, str] | None = None) -> int | None:
    """The Claude process a classic run is waiting on, if it is still that one.

    A recorded pid outlives its process and the number is reused, so showing
    the record unverified is how a surface points at somebody else's work.
    Checked the way `reap.sh` checks it, minus the cwd comparison: that one
    costs an `lsof` per run, and reap.sh needs it because it is about to send
    a signal. This only prints a number, so pid plus start time plus command
    is the right amount of certainty to buy.
    """
    record = _pid_record(task_id)
    try:
        pid = int(record.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    runner = str(record.get("runner") or "claude")

    if commands is None:
        commands = dict(_ps(10) or [])
    command = commands.get(pid)
    if not command:
        return None
    argv = command.split()
    names = {Path(word).name for word in argv[:2]}
    if runner not in names:
        return None

    recorded_start = str(record.get("lstart") or "").strip()
    if recorded_start:
        try:
            live = subprocess.run(
                ["ps", "-p", str(pid), "-o", "lstart="],
                capture_output=True, text=True, check=False, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if live.stdout.strip() != recorded_start:
            return None
    return pid


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

    The id may arrive from a URL and crosses a process boundary. There is no
    shell here — the command is a list — but unvalidated request data should
    not reach another program's argv on the strength of that alone, so the
    shape is checked first. It matches the guard `zam-stop.sh` already uses.
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


def _body_field(task: Mapping[str, Any], name: str) -> str | None:
    """A `key: value` line `launch` wrote into the task body."""
    pattern = re.compile(rf"^\s*{name}:\s*(\S+)\s*$", re.MULTILINE)
    match = pattern.search(str(task.get("body") or ""))
    return match.group(1) if match else None


def build_run(
    task: Mapping[str, Any],
    task_events: list[Mapping[str, Any]],
    process: Process | None = None,
    claude_pid: int | None = None,
) -> Run:
    workspace = task.get("workspace_path")
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
        worktree=Path(str(workspace)) if workspace else None,
        # The live process's own argv first: it is what is actually executing.
        # The body is what was asked for, which is the next best thing and the
        # only thing left once the process is gone.
        flow=(process.flow if process else None) or _body_field(task, "flow"),
        shape=process.shape if process else None,
        runner_pid=process.pid if process else None,
        claude_pid=claude_pid,
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
    """Every run the board knows about, newest activity first.

    One board read, one `ps` snapshot and one pass over the event log for the
    whole fleet. The Claude child is looked up only for a live classic run,
    because it is the only shape that has one and a dead run's record has
    already been removed by `reap.sh`.
    """
    recorded: dict[str, list[Mapping[str, Any]]] = {}
    for item in events.read(limit=limit_events * 10):
        recorded.setdefault(str(item.get("task_id")), []).append(item)
    # The board first, the process table second, and the order is load-bearing:
    # reading `ps` first leaves a window in which `launch` claims a task and
    # spawns its flow, so the run is `running` on a board read afterwards and
    # missing from a snapshot taken before it existed — reported dead, with an
    # invitation to relaunch something that had just started. Taking the
    # snapshot last cannot invent that gap; at worst it sees a run the board
    # has not heard of yet, which no surface asks about. `detail` already did
    # it in this order.
    tasks = board()
    listing = _ps(10)
    known = listing is not None
    commands = dict(listing or [])
    live = _live_map(commands)
    runs = []
    for task in tasks:
        task_id = str(task.get("id"))
        process = live.get(task_id)
        run = build_run(
            task,
            recorded.get(task_id, []),
            process,
            _claude_for(process, commands),
        )
        run.liveness_known = known
        runs.append(run)
    runs.sort(key=lambda r: (r.last_signal_at or 0), reverse=True)
    return runs


def detail(task_id: str) -> tuple[Run | None, dict[str, Any]]:
    """One run with its locators, and Hermes' own record of it.

    A surface showing a single task needs process truth as much as a listing
    does — built without it, every run on the page reads as dead. So the
    module answers for one run rather than leaving a renderer to assemble a
    half-populated one from `task_detail`.

    Returns the run and the raw payload, which also carries Hermes' run
    history and comments — its own records, which this module does not
    reinterpret.
    """
    payload = task_detail(task_id)
    task = payload.get("task") or {}
    if not task:
        return None, payload
    listing = _ps(10)
    commands = dict(listing or [])
    process = _live_map(commands).get(str(task.get("id")))
    run = build_run(
        task,
        events.read(task_id, limit=500),
        process,
        _claude_for(process, commands),
    )
    run.liveness_known = listing is not None
    return run, payload


def _live_map(commands: Mapping[int, str]) -> dict[str, Process]:
    """Every live run in one snapshot, keyed by task id.

    One task can put two processes on the table. A staged flow started through
    `run-loop.sh` leaves the wrapper in the foreground — it pipes the runner
    through `tee`, which is where `loop.log` comes from — so both the bash
    script and its Python child match, under the same task id. Whichever `ps`
    happened to emit last used to win, which meant a `full` run could be
    labelled `(classic)`, report the shell's pid as its runner, and send
    `_claude_for` hunting for a pid record a staged flow never writes.

    The child is the run; the wrapper is how it was started. So the staged
    shape wins, deterministically, rather than by listing order.
    """
    live: dict[str, Process] = {}
    for pid, command in commands.items():
        process = _classify(pid, command)
        if not process:
            continue
        existing = live.get(process.task_id)
        if existing and existing.shape == "staged" and process.shape != "staged":
            continue
        live[process.task_id] = process
    return live


def _claude_for(process: Process | None, commands: Mapping[int, str]) -> int | None:
    """The Claude child, for the one shape that has one.

    Only a classic run spawns Claude directly, and only while it is alive:
    `reap.sh` removes the record, so a dead run has nothing to verify against
    and a surviving record would name a pid that is somebody else's by now.
    """
    if not process or process.shape != "classic":
        return None
    return claude_child(process.task_id, commands)


def find(target: str, runs: list[Run] | None = None) -> Run | None:
    """One run, by task id or issue key. Case-insensitive on the issue key."""
    wanted = (target or "").strip()
    if not wanted:
        return None
    for run in runs if runs is not None else fleet():
        if run.task_id == wanted or (run.issue_key or "").upper() == wanted.upper():
            return run
    return None


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
    repo = Path(__file__).resolve().parents[1]
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


# Stamped once and then kept. Read per request it was worse than useless: it
# reported whatever the checkout says *now*, so a process running three-hour-old
# code displayed the newest commit and looked current. The whole point of the
# stamp is to catch that, and it could not.
#
# Stamped on first use rather than at import, which is a change forced by this
# module's new position. It used to live in `dash/data.py`, imported only by a
# web process that was about to render the stamp anyway. Now `runner.py` and
# `control.py` import it at module scope, so two `git` subprocesses — one of
# them `git status --porcelain`, which is not cheap on a cold or large
# worktree — ran on every flow start for a stamp no flow ever reads. Measured
# at 30ms of a 57ms `import cuzam.runner` on a warm clean checkout.
#
# "First use" is within a request or two of start for the dashboard, which is
# the only caller, so the stamp still catches the case it exists for.
_LOADED: tuple[str, bool] | None = None


def loaded_build() -> tuple[str, bool]:
    """The commit this process started on, remembered from the first ask."""
    global _LOADED
    if _LOADED is None:
        _LOADED = _read_commit()
    return _LOADED


def build_stamp() -> dict[str, str | bool]:
    """What this process is running — not what the checkout says today."""
    loaded_commit, loaded_dirty = loaded_build()
    current, _ = _read_commit()
    return {
        "commit": loaded_commit,
        "dirty": loaded_dirty,
        "uptime": humanise(int(time.time()) - STARTED_AT) or "0s",
        # A running process older than the checkout is the failure this
        # exists to surface, so it is stated rather than left to be inferred
        # from two hex strings.
        "stale": current != loaded_commit and current != "unknown",
        "current": current,
    }
