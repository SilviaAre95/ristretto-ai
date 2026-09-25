"""Which copy of Cuzam a dispatched flow runs.

The skills are symlinks into the working checkout and the package is an
editable install, so until now the runtime *was* whatever you had open: a flow
launched mid-edit ran half-finished code, on whatever branch happened to be
out, and a run could be described only as "whatever was there at the time".
Twice on 2026-09-10 an experiment had to be preceded by `git checkout main`
for its result to mean anything, and once a fix had to be held back because
editing the file would have swapped code under a live flow.

So a flow runs from a checkout nobody edits: `~/.cuzam/runtime`, tracking
`origin/<base>`, updated deliberately by `make install-runtime`. The launcher
stays wherever you invoked it — that part is interactive and you are watching
it. What gets pinned is the hour-long unattended part.

Deliberately not automatic. A runtime that silently fast-forwarded would
reintroduce the problem in a slower form: the flow would still run code you
had not chosen, just code from a different moment. Updating is a decision, and
`flow.json` records which commit was decided on.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Mapping

from . import events

# Where the pinned checkout lives, beside the rest of Cuzam's state.
RUNTIME_DIR = "runtime"
# Its virtualenv. Separate from the development one on purpose: sharing would
# import the editable install and defeat the whole arrangement.
RUNTIME_VENV = ".venv"


def runtime_root(environ: Mapping[str, str] | None = None) -> Path:
    return events.state_home(environ) / RUNTIME_DIR


# Where the classic loop lives inside a checkout. The last three segments are
# load-bearing, not cosmetic: `runs.CLASSIC_SCRIPT` and the awk in
# `scripts/live-runs.sh` both identify a classic run by a command line ending in
# `loop-runner/scripts/run-loop.sh`. A run spawned from any other path is a run
# neither implementation can see — it reads as dead while it works, and every
# surface invites the operator to relaunch it. Moving the script means moving
# both matchers and the contract test in the same change.
CLASSIC_SCRIPT_PATH = Path("hermes/skills/loop-runner/scripts/run-loop.sh")

# Environment that would un-pin a pinned interpreter by putting another copy
# of the package ahead of its own site-packages. PYTHONPATH is not a corner
# case here: scripts/check.sh and run-loop.sh both export it.
UNPINNING_ENV = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")


def runtime_python(environ: Mapping[str, str] | None = None) -> Path | None:
    """The interpreter a flow should run under, or None when unpinned.

    Checks that it can import the runner, not merely that a file exists.
    `python3 -m venv` succeeding and `pip install` then failing leaves an
    interpreter behind that cannot import anything — and the flow spawned
    under it dies instantly on ModuleNotFoundError while the launch reports
    success, the task stays claimed, and the day-scoped idempotency key
    refuses every retry until midnight.
    """
    candidate = runtime_root(environ) / RUNTIME_VENV / "bin" / "python"
    if not candidate.is_file():
        return None
    try:
        proved = subprocess.run(
            [str(candidate), "-P", "-c", "import cuzam.runner"],
            capture_output=True, text=True, check=False, timeout=60,
            cwd="/", env=pinned_env(dict(environ) if environ else None),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return candidate if proved.returncode == 0 else None


def pinned_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a pinned interpreter runs in, minus what would un-pin it.

    `-P` stops Python putting the working directory on sys.path, which matters
    because a flow's cwd is the worktree — and a worktree of *this* repository
    contains a `cuzam/` package, so the pin was defeated for precisely the
    repository where it matters most. PYTHONPATH survives `-P` and has to be
    removed separately.
    """
    import os as _os

    env = dict(_os.environ if environ is None else environ)
    for name in UNPINNING_ENV:
        env.pop(name, None)
    return env


def runtime_identity(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """What the pinned checkout is, for the record a run leaves behind.

    Reports `pinned: "no"` rather than raising when the runtime is absent.
    Refusing to launch would be the stricter choice, and the wrong one: an
    install that has not run `make install-runtime` yet would lose the ability
    to dispatch at all, which is a worse failure than a clearly-labelled
    unpinned run.
    """
    root = runtime_root(environ)
    if runtime_python(environ) is None:
        return {"pinned": "no", "reason": "no runtime checkout — run `make install-runtime`"}

    def git(*args: str) -> str:
        try:
            done = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True, text=True, check=False, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (done.stdout or "").strip() if done.returncode == 0 else ""

    identity: dict[str, str] = {"pinned": "yes", "path": str(root)}
    commit = git("rev-parse", "HEAD")
    if not commit:
        # git() returns "" for a failure, a timeout and an empty result alike,
        # so without this a runtime that is not a git checkout at all — copied,
        # rsynced, .git deleted — would be recorded as clean with no commit.
        # That is the most misleading record this function could produce, for a
        # feature whose entire purpose is that a run can state what ran it.
        identity["tree"] = "unknown"
        return identity
    identity["commit"] = commit[:12]
    # A pinned checkout that someone edited is no longer pinned to anything.
    identity["tree"] = "dirty" if git("status", "--porcelain") else "clean"
    return identity


def flow_script(
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, str]:
    """(path to run-loop.sh, warning) for running the classic loop.

    The classic loop is a shell program, so `flow_interpreter` cannot pin it —
    that pins the interpreter, and the interpreter never sees this script. It
    used to be pinned by a symlink `link-loop-runner.sh` moved, because the only
    thing that ran it was a Hermes worker reading a skill. The launcher starts it
    now, so the launcher has to resolve it, and it resolves it the same way and
    with the same visible fallback as the interpreter.

    Probes the file and not its directory, for the reason `link-loop-runner.sh`
    gives: a half-cloned runtime has the tree without the script, and pointing at
    that breaks every classic run.
    """
    pinned = runtime_root(environ) / CLASSIC_SCRIPT_PATH
    if pinned.is_file():
        return pinned, ""
    return (
        Path(__file__).resolve().parents[1] / CLASSIC_SCRIPT_PATH,
        "running from the development checkout, not a pinned runtime — "
        "this flow executes whatever is in that tree right now; "
        "run `make install-runtime` to pin it",
    )


def flow_interpreter(
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], dict[str, str], str]:
    """(argv prefix, environment, warning) for running a flow.

    Returns the flags and environment as well as the path, because a pinned
    interpreter that inherits PYTHONPATH or runs with the worktree on sys.path
    is not pinned at all — it just looks it. Keeping the three together means
    a caller cannot take the interpreter and forget the rest.

    sys.executable is the fallback for the same reason the broker uses it:
    whatever is first on a PATH usually cannot import cuzam. The fallback
    keeps the launcher's environment untouched — it *is* the development
    checkout, so stripping PYTHONPATH there could break the very import it
    needs.
    """
    import os as _os

    pinned = runtime_python(environ)
    if pinned is not None:
        return [str(pinned), "-P"], pinned_env(environ), ""
    return (
        [sys.executable],
        dict(_os.environ if environ is None else environ),
        "running from the development checkout, not a pinned runtime — "
        "this flow executes whatever is in that tree right now; "
        "run `make install-runtime` to pin it",
    )
