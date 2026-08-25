"""Check that a repository can actually run a supervised loop.

Every task builds in a fresh worktree created from the base branch, so the
loop only ever sees what is committed. A developer's own checkout accumulates
installed dependencies, generated clients, and hand-made config files, and
none of that exists in the worktree. The resulting failures do not look like
missing setup — they look like the model wrote broken code — so they get
blamed on the model and the real cause survives.

The fast checks answer "are the loop's own files in git?". The deep check
answers the only question that really matters: "does the verify gate pass in
a clone that has nothing but the repository?"
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

GATE_FILES = (".cc-dev.yaml", ".cc-verify")


class Finding(NamedTuple):
    level: str  # OK | ERROR
    message: str

    def __str__(self) -> str:
        return f"{self.level} {self.message}"


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def resolve_ref(repo: Path, base: str) -> str | None:
    """The ref a fresh worktree would start from.

    origin wins over the local branch: a local `main` can sit behind the
    remote for weeks, and checking the stale one would report on a tree
    nobody is going to build.
    """
    for ref in (f"origin/{base}", base):
        if _git(repo, "rev-parse", "--verify", "--quiet", ref).returncode == 0:
            return ref
    return None


def tracked_in_base(repo: Path, base: str, name: str) -> bool:
    """Is this path committed on the base ref (not merely on disk)?"""
    ref = resolve_ref(repo, base)
    if ref is None:
        return False
    return _git(repo, "cat-file", "-e", f"{ref}:{name}").returncode == 0


def fast_findings(repo: Path, base: str = "main") -> list[Finding]:
    """Cheap checks: the loop's own files must be in git, not just on disk."""
    findings: list[Finding] = []
    if not (repo / ".git").exists():
        return [Finding("ERROR", f"{repo} is not a git repository")]
    for name in GATE_FILES:
        on_disk = (repo / name).exists()
        committed = tracked_in_base(repo, base, name)
        if committed:
            findings.append(Finding("OK", f"{name} is committed on {base}"))
        elif on_disk:
            findings.append(
                Finding(
                    "ERROR",
                    f"{name} exists locally but is not committed on {base}; "
                    "a fresh worktree will not have it",
                )
            )
        else:
            findings.append(Finding("ERROR", f"{name} is missing — the repo is not wired for the loop"))
    return findings


def deep_findings(repo: Path, base: str = "main", timeout: int = 1800) -> list[Finding]:
    """Clone the base branch to a temp dir, install, and run the verify gate.

    This is the check that catches setup living outside the repository — a
    generated database client, a build step nothing re-runs — which the fast
    checks cannot see.
    """
    ref = resolve_ref(repo, base)
    if ref is None:
        return [Finding("ERROR", f"cannot resolve base branch {base}")]
    if not tracked_in_base(repo, base, ".cc-verify"):
        return [Finding("ERROR", f"cannot run the gate: .cc-verify is not committed on {ref}")]
    with tempfile.TemporaryDirectory(prefix="ris-preflight-") as scratch:
        clone = Path(scratch) / "repo"
        # A worktree, not a clone: it is exactly the mechanism the loop uses,
        # and it pins the same ref the fast checks inspected. Cloning would
        # silently pick up a local branch sitting behind the remote.
        added = _git(repo, "worktree", "add", "--detach", "--quiet", str(clone), ref, timeout=300)
        if added.returncode != 0:
            return [Finding("ERROR", f"could not check out {ref}: {added.stderr.strip()[:200]}")]
        try:
            return _gate_findings(clone, ref, timeout)
        finally:
            _git(repo, "worktree", "remove", "--force", str(clone), timeout=120)
            _git(repo, "worktree", "prune")


def _gate_findings(clone: Path, ref: str, timeout: int) -> list[Finding]:
    """Install dependencies and run the verify gate inside a clean checkout."""
    findings = [Finding("OK", f"checked out {ref} into a scratch worktree")]
    if (clone / "package.json").exists():
        install = subprocess.run(
            ["npm", "ci"] if (clone / "package-lock.json").exists() else ["npm", "install"],
            cwd=clone,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if install.returncode != 0:
            return findings + [
                Finding("ERROR", f"dependency install failed: {install.stderr.strip()[-300:]}")
            ]
        findings.append(Finding("OK", "dependencies installed from a clean checkout"))
    gate = subprocess.run(
        ["bash", str(clone / ".cc-verify")],
        cwd=clone,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if gate.returncode != 0:
        tail = (gate.stdout + gate.stderr).strip().splitlines()[-6:]
        detail = " / ".join(line.strip() for line in tail if line.strip())
        findings.append(
            Finding(
                "ERROR",
                "verify gate fails from a clean checkout — the loop cannot pass it either: "
                + detail[:400],
            )
        )
    else:
        findings.append(Finding("OK", "verify gate passes from a clean checkout"))
    return findings


def preflight(repo: Path, base: str = "main", deep: bool = False) -> list[Finding]:
    findings = fast_findings(repo, base)
    if deep and not any(f.level == "ERROR" for f in findings):
        if shutil.which("git") is None:
            return findings + [Finding("ERROR", "git not found")]
        findings.extend(deep_findings(repo, base))
    return findings
