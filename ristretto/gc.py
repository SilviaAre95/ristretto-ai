"""Reclaim the worktrees and branches finished tasks leave behind.

Every issue gets its own worktree so several can run in parallel without
fighting over one checkout. Nothing has ever removed them: Hermes creates the
worktree, the task reaches a terminal state, and the directory stays on disk
until someone notices months later.

Removing a worktree does not lose commits — the branch keeps them — so the
check that matters is uncommitted work in the tree. Deleting a *branch* can
lose commits, so that requires the commits to be merged into the base ref.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, NamedTuple

# Only ever consider directories Hermes named after a task. This is a shape
# check, not the authority — a name must also match a real task on the board,
# be terminal, and have a clean tree. Kept deliberately loose on the character
# class so a change to Hermes' id format degrades into manual cleanup rather
# than silently reintroducing the pile-up this command exists to prevent.
TASK_WORKTREE = re.compile(r"^t_[0-9A-Za-z]{6,}$")
TERMINAL_STATES = frozenset({"done", "archived"})
# Run artifacts and editor noise are not work worth preserving.
IGNORED_DIRT = ("\\.ristretto/", "\\.DS_Store", "\\.cc-ris-session")


class Candidate(NamedTuple):
    path: Path
    task_id: str
    action: str  # remove | keep
    reason: str

    def __str__(self) -> str:
        verb = "REMOVE" if self.action == "remove" else "KEEP  "
        return f"{verb} {self.path}  ({self.reason})"


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False, timeout=timeout
    )


def board_tasks(timeout: int = 60) -> dict[str, Mapping[str, Any]]:
    """Task id -> task, including archived. Empty if the board is unreadable."""
    tasks: dict[str, Mapping[str, Any]] = {}
    result = subprocess.run(
        ["hermes", "kanban", "list", "--json", "--archived"],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        return tasks
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return tasks
    items = payload if isinstance(payload, list) else payload.get("tasks", [])
    for item in items:
        if isinstance(item, Mapping) and item.get("id"):
            tasks[str(item["id"])] = item
    return tasks


def dirty_paths(worktree: Path) -> list[str]:
    """Uncommitted work in a worktree, ignoring run artifacts and editor noise."""
    result = _git(worktree, "status", "--porcelain")
    if result.returncode != 0:
        return []
    dirt = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if path and not any(re.match(pattern, path) for pattern in IGNORED_DIRT):
            dirt.append(path)
    return dirt


def worktrees(repo: Path) -> list[Path]:
    result = _git(repo, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return []
    found = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.split(" ", 1)[1])
            if path.resolve() != repo.resolve():
                found.append(path)
    return found


def plan(repo: Path, tasks: Mapping[str, Mapping[str, Any]] | None = None) -> list[Candidate]:
    """Decide what may be reclaimed, without touching anything."""
    board = board_tasks() if tasks is None else tasks
    candidates: list[Candidate] = []
    for path in worktrees(repo):
        name = path.name
        if not TASK_WORKTREE.match(name):
            candidates.append(Candidate(path, name, "keep", "not a task worktree"))
            continue
        task = board.get(name)
        if task is None:
            candidates.append(
                Candidate(path, name, "keep", "no matching task on the board — inspect by hand")
            )
            continue
        status = str(task.get("status", "")).lower()
        if status not in TERMINAL_STATES:
            candidates.append(Candidate(path, name, "keep", f"task is {status or 'unknown'}"))
            continue
        if not path.exists():
            candidates.append(Candidate(path, name, "remove", "directory already gone"))
            continue
        dirt = dirty_paths(path)
        if dirt:
            listed = ", ".join(dirt[:3]) + (" …" if len(dirt) > 3 else "")
            candidates.append(
                Candidate(path, name, "keep", f"uncommitted work would be lost: {listed}")
            )
            continue
        candidates.append(Candidate(path, name, "remove", f"task is {status}, tree is clean"))
    return candidates


def reclaim(repo: Path, candidates: list[Candidate]) -> list[str]:
    """Remove the approved worktrees. Returns lines describing what happened."""
    done = []
    for candidate in candidates:
        if candidate.action != "remove":
            continue
        result = _git(repo, "worktree", "remove", "--force", str(candidate.path), timeout=120)
        if result.returncode == 0:
            done.append(f"removed {candidate.path}")
        else:
            done.append(f"FAILED {candidate.path}: {result.stderr.strip()[:160]}")
    _git(repo, "worktree", "prune")
    done.append("pruned stale worktree metadata")
    return done


def merged_branches(repo: Path, base: str = "main") -> list[str]:
    """Local task branches whose commits are already in the base ref."""
    ref = None
    for candidate in (f"origin/{base}", base):
        if _git(repo, "rev-parse", "--verify", "--quiet", candidate).returncode == 0:
            ref = candidate
            break
    if ref is None:
        return []
    result = _git(repo, "branch", "--merged", ref, "--format=%(refname:short)")
    if result.returncode != 0:
        return []
    current = _git(repo, "branch", "--show-current").stdout.strip()
    return [
        name.strip()
        for name in result.stdout.splitlines()
        if name.strip() and name.strip() not in {base, current}
    ]


def delete_branches(repo: Path, names: list[str]) -> list[str]:
    done = []
    for name in names:
        # -d, never -D: git refuses anything not fully merged, which is the
        # safety net rather than our own bookkeeping.
        result = _git(repo, "branch", "-d", name)
        done.append(
            f"deleted branch {name}"
            if result.returncode == 0
            else f"kept branch {name}: {result.stderr.strip()[:120]}"
        )
    return done
