#!/usr/bin/env python3
"""Every rename shim says when it goes, next to itself.

`RISTRETTO_*` became `CUZAM_*` and `RIS_*` became `ZAM_*` on 2026-09-24, and
the old spellings are still read for one release so an environment exported
before the rename keeps working. The rule for removing them lived in exactly
one place — `CHANGELOG.md`, under the 0.2.0 rename entry — which is not a file
anyone opens while doing the removal. Marker coverage when this was written was
3 of 4 in `cuzam/`, 2 of 12 in `scripts/`, 6 of 13 under `hermes/`.

That is the failure this file exists for, and it is not hypothetical in either
direction. A shim nobody can find is a shim that outlives its release and
becomes load-bearing. A shim removed without noticing a second reader of the
same name resolves to a default that exists, which is how `RISTRETTO_HERMES_HOME`
would have turned into "Hermes is not installed" rather than into an error
naming a variable.

So `grep -rn 0.3.0` now finds every one of them, and this test is what keeps
that true when the next one is added.

**Delete this file in 0.3.0, with the shims it polices.** It is excluded from
its own scan — `hermes/tests` is not scanned at all — so nothing else would
surface it, and the line you are reading is what `grep -rn 0.3.0` returns for
it. When the last shim goes, `shim_sites()` returns nothing and the scan test
skips with that instruction rather than failing: a guard that goes red on the
cleanup it was written for would be an argument against doing the cleanup.

Discovered rather than listed, for the reason `scripts/check.sh` gives about
its own test collection: a hand-maintained list means a new site is simply
absent from it, which is worse than no check. The exclusions below are by
*rule* and not by filename drift.
"""

from __future__ import annotations

import ast
import re
import unittest
import pathlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Where a legacy name is *read* — i.e. where a shim actually lives. Tests are
# not scanned as a class: a test naming an old name is asserting something
# about it, not shimming it, and several already carry their own markers.
SOURCES = ("cuzam", "scripts", "hermes/scripts", "hermes/skills", ".githooks")
SUFFIXES = (".py", ".sh", ".toml")


def _is_source(path: pathlib.Path) -> bool:
    """A file whose contents this guard should read.

    Extension OR shebang, and the shebang half is not hypothetical: a review
    found `.githooks/pre-push` — tracked, executable, extensionless, and holding
    an unmarked `RISTRETTO_PRIVATE_ROOT_COMMIT` fallback that the first version
    of this scan could not see at all. Its shim failing open matters more than
    most: at 0.3.0 a grep sweep would drop the fallback from `install.sh` and
    leave the push guard enforcing a different root commit than the installer
    validated.

    Keyed on the shebang rather than the executable bit, because a file's mode
    is not what decides whether it is source.
    """
    if not path.is_file() or "__pycache__" in path.parts:
        return False
    if path.suffix in SUFFIXES:
        return True
    if path.suffix:
        return False
    try:
        with path.open("rb") as handle:
            first = handle.readline(128)
    except OSError:  # pragma: no cover - unreadable is not source
        return False
    return first.startswith(b"#!") and any(
        token in first for token in (b"sh", b"python")
    )

# The spellings that mean "this is here for the old name".
#
# Widened after a review named shapes the repository actually uses that the
# first pattern missed: the launchd label `com.ristretto.dash`, a
# `$HOME/.ristretto` with no trailing slash, and the console-script names in any
# spelling other than the exact `ristretto = ` line pyproject happens to have.
# A shim the guard passes silently undoes the claim that `grep -rn 0.3.0` finds
# all of them.
LEGACY = re.compile(
    r"RISTRETTO_[A-Z0-9_]+"
    r"|RIS_[A-Z0-9_]+"
    r"|ristretto\.runner"
    r"|\.ristretto\b"
    r"|com\.ristretto\."
    r"|cc-ris-session"
    r"|ris:[a-z-]+"
    r"|\bris-[a-z]+"
    r"|\b(ristretto|nemo)\s*=",
    re.MULTILINE,
)

# The marker. Any mention of the release the shims go in.
MARKER = "0.3.0"

EXCLUDED = {
    # The shim machinery itself. Its module docstring carries the marker, and
    # every line in it is about the old names by construction.
    "cuzam/env.py",
    # The one-time rename migration. Its whole subject is the old names, so a
    # marker per line would be noise — and unlike a shim it is NOT dropped at
    # 0.3.0: someone upgrading straight from Ristretto still needs it after the
    # shims are gone. That is why it is excluded rather than marked.
    "scripts/migrate-cuzam.sh",
}


def shim_sites() -> list[tuple[str, int, str]]:
    """Every line in non-test source that reads a pre-rename name."""
    found: list[tuple[str, int, str]] = []
    paths = [
        path
        for source in SOURCES
        if (ROOT / source).exists()
        for path in sorted((ROOT / source).rglob("*"))
        if _is_source(path)
    ]
    # pyproject.toml ships the legacy console scripts and is not under SOURCES.
    paths.append(ROOT / "pyproject.toml")
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if relative in EXCLUDED:
            continue
        prose = _prose_lines(path)
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            # A comment or docstring that mentions an old name is prose ABOUT
            # a shim, not a shim. Only code reads a variable, so only code
            # needs the marker —
            # and demanding one per sentence of an explanation would push the
            # marker away from the line that matters. This is also what makes
            # the rule below strict enough to be useful: the sites left are all
            # single lines of code.
            if _is_comment(line) or number in prose:
                continue
            if LEGACY.search(line):
                found.append((relative, number, line.strip()))
    return found


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _prose_lines(path: pathlib.Path) -> set[int]:
    """Lines that are a Python docstring, and so prose rather than code.

    Only bare string *statements* — a module, class or function docstring, or a
    free-standing string. Not every string literal: `RUNNER_MODULES` in
    `runs.py` and the worktree patterns in `gc.py` are real shims that live
    inside string literals, and excluding those would make this scan blind to
    the two it most needs to see.
    """
    if path.suffix != ".py":
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
        return set()
    prose: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                prose.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return prose


def marked(relative: str, number: int) -> bool:
    """Is this shim's marker in the comment attached to it?

    Structural rather than a distance, and that is the second attempt. A
    proximity window was tried twice — 25 lines, then 20 — and both let an
    unrelated marker elsewhere in the file cover a brand-new shim. The second
    was caught by a review appending one to `setup-dev.sh`, 54 lines long with
    its only marker at line 41: fourteen lines away, inside the window, and
    about something else entirely. Any distance wide enough for a real comment
    block is wide enough for a short file, so distance is the wrong instrument.

    What the rule protects is that a person reading the shim sees when it goes.
    So: the marker is on the shim line itself — a trailing `# drop in 0.3.0` is
    the usual shape for one of a group — or in the contiguous comment block
    directly above it, blank lines skipped. A marker elsewhere in the same file
    does not count, because inheriting cover from an unrelated one is the
    failure both windows had.

    Every language scanned here comments with `#`.
    """
    lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
    index = number - 1
    if MARKER in lines[index]:
        return True
    end = index - 1
    while end >= 0 and not lines[end].strip():
        end -= 1
    if end < 0 or not _is_comment(lines[end]):
        return False
    start = end
    while start > 0 and _is_comment(lines[start - 1]):
        start -= 1
    return any(MARKER in line for line in lines[start : end + 1])


class ShimMarkerTest(unittest.TestCase):
    def test_the_scan_finds_something(self) -> None:
        """A pattern that matches nothing would make this file vacuous.

        The count is not asserted — it changes as shims are added and removed,
        and pinning it would make every such change edit this test. What is
        asserted is that the scan is still looking at the right thing: the
        known readers of the two renamed state variables have to be in it.
        """
        sites = shim_sites()
        if not sites:
            raise unittest.SkipTest(
                "no pre-rename name is read anywhere: the shims are gone, so "
                "delete this file and the exclusions in it"
            )
        self.assertGreater(len(sites), 5, sites)
        files = {relative for relative, _, _ in sites}
        # The shell installers are the largest group and the likeliest to be
        # missed by a pattern change, so one of them anchors the scan.
        self.assertIn("scripts/install-runtime.sh", files)

    def test_no_file_reads_a_legacy_name_with_no_marker_at_all(self) -> None:
        """The weak check, which the proximity one cannot make.

        A proximity window can only ask "is there a marker near this line". It
        cannot notice a file that reads a legacy name and mentions 0.3.0
        nowhere — a new script, or an old one whose only marker was deleted
        with the shim it described. This asks that, and it is deliberately
        cruder: passing it means nothing about placement.
        """
        unmarked = sorted(
            {
                relative
                for relative, _, _ in shim_sites()
                if MARKER not in (ROOT / relative).read_text(encoding="utf-8")
            }
        )
        self.assertEqual(
            unmarked, [],
            f"these read a pre-rename name and never mention {MARKER}: {unmarked}",
        )

    def test_every_shim_says_when_it_goes(self) -> None:
        unmarked = [
            f"{relative}:{number}: {line}"
            for relative, number, line in shim_sites()
            if not marked(relative, number)
        ]
        self.assertEqual(
            unmarked, [],
            "these read a pre-rename name with no 0.3.0 marker in the comment "
            "attached to them. Put one in the comment block directly above the "
            "line (or on the line itself) — 'Drop in 0.3.0.' is enough — so that "
            "`grep -rn 0.3.0` finds it when the shims are removed. A marker "
            "elsewhere in the same file does not count, because that is how a "
            "new shim inherits cover from an unrelated one. The rule is in "
            "CHANGELOG.md under the rename entry, which is not where anyone "
            "doing the removal looks:\n  " + "\n  ".join(unmarked),
        )


if __name__ == "__main__":
    unittest.main()
