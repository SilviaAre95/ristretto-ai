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

Discovered rather than listed, for the reason `scripts/check.sh` gives about
its own test collection: a hand-maintained list means a new site is simply
absent from it, which is worse than no check. The exclusions below are by
*rule* and not by filename drift.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Where a legacy name is *read* — i.e. where a shim actually lives. Tests are
# not scanned as a class: a test naming an old name is asserting something
# about it, not shimming it, and several already carry their own markers.
SOURCES = ("cuzam", "scripts", "hermes/scripts", "hermes/skills")
SUFFIXES = (".py", ".sh", ".toml")

# The spellings that mean "this is here for the old name".
LEGACY = re.compile(
    r"RISTRETTO_[A-Z0-9_]+"
    r"|RIS_[A-Z0-9_]+"
    r"|ristretto\.runner"
    r"|\.ristretto/"
    r"|cc-ris-session"
    r"|ris:[a-z-]+"
    r"|\bris-[a-z]+"
    r"|^ristretto = "
    r"|^nemo = ",
    re.MULTILINE,
)

# The marker. Any mention of the release the shims go in.
MARKER = "0.3.0"

# How far from the shim the marker may sit. Both numbers were measured against
# the real sites rather than picked, and both directions are needed: several
# shims are explained by a comment block whose marker is its *last* line, and
# one — the legacy module name in live-runs.sh's awk program — is matched by
# code sixteen lines below the comment that explains it.
#
# Sized so that the check actually bites. At 25/10 (the first attempt),
# appending a brand-new unmarked shim to the end of a 33-line script passed,
# because a marker near the top of that file was inside the window and counted
# as covering it. That is the case this file exists to catch, so the window is
# smaller than the shortest such file.
#
# Residual, named rather than engineered away: a new shim added within twenty
# lines of an existing marker passes. That case is benign — the marker really
# is adjacent, so the person doing the 0.3.0 removal sees it, which is the
# property being protected. What the window must not be is "anywhere in this
# file", which the per-file check below covers separately and weakly.
ABOVE, BELOW = 20, 8

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
    for source in SOURCES:
        for path in sorted((ROOT / source).rglob("*")):
            if path.suffix not in SUFFIXES or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative in EXCLUDED:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, start=1):
                if LEGACY.search(line):
                    found.append((relative, number, line.strip()))
    # pyproject.toml ships the legacy console scripts and is not under SOURCES.
    pyproject = ROOT / "pyproject.toml"
    for number, line in enumerate(pyproject.read_text().splitlines(), start=1):
        if LEGACY.search(line):
            found.append(("pyproject.toml", number, line.strip()))
    return found


def marked(relative: str, number: int) -> bool:
    lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
    window = lines[max(0, number - 1 - ABOVE) : number + BELOW]
    return any(MARKER in line for line in window)


class ShimMarkerTest(unittest.TestCase):
    def test_the_scan_finds_something(self) -> None:
        """A pattern that matches nothing would make this file vacuous.

        The count is not asserted — it changes as shims are added and removed,
        and pinning it would make every such change edit this test. What is
        asserted is that the scan is still looking at the right thing: the
        known readers of the two renamed state variables have to be in it.
        """
        sites = shim_sites()
        self.assertGreater(len(sites), 10, sites)
        files = {relative for relative, _, _ in sites}
        for expected in ("cuzam/config.py", "scripts/install-runtime.sh"):
            self.assertIn(expected, files)

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
            "these read a pre-rename name with no 0.3.0 marker within "
            f"{ABOVE} lines above or {BELOW} below. Add one — a comment saying "
            "'Drop in 0.3.0' is enough — so that `grep -rn 0.3.0` finds it "
            "when the shims are removed. The rule is in CHANGELOG.md under the "
            "rename entry, which is not where anyone doing the removal looks:"
            "\n  " + "\n  ".join(unmarked),
        )


if __name__ == "__main__":
    unittest.main()
