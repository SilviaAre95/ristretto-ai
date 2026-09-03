#!/usr/bin/env python3
"""The contract between Nemo and wayworks.

Nemo reads convention files that wayworks' harness-init writes. They live in
separate repositories with separate suites, so a rename on either side breaks
the other silently. This is the one test that spans the boundary.

When wayworks is not checked out as a sibling — CI, a fresh clone — the
cross-repo assertions skip rather than fail: absence of wayworks is not a
contract violation.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ristretto import seam

# wayworks is expected beside ristretto-ai in the same parent directory.
WAYWORKS = Path(__file__).resolve().parents[2].parent / "wayworks"
HARNESS_INIT = WAYWORKS / "plugins" / "harness" / "commands" / "harness-init.md"


class SeamDeclarationTest(unittest.TestCase):
    """Nemo's side: the names are declared once and used from there."""

    def test_preflight_uses_the_declared_names(self) -> None:
        from ristretto import preflight
        self.assertIs(preflight.GATE_FILES, seam.GATE_FILES)

    def test_the_verify_gate_name_is_not_re_hardcoded(self) -> None:
        # A stray "\.cc-verify" literal is how the single source of truth
        # quietly stops being single.
        src = (Path(__file__).resolve().parents[2] / "ristretto").rglob("*.py")
        offenders = []
        for path in src:
            if path.name == "seam.py":
                continue
            text = path.read_text()
            if '".cc-verify"' in text or '".cc-dev.yaml"' in text:
                offenders.append(path.name)
        self.assertEqual(offenders, [], f"convention names hardcoded outside seam.py: {offenders}")


@unittest.skipUnless(HARNESS_INIT.is_file(), "wayworks not checked out as a sibling")
class WayworksContractTest(unittest.TestCase):
    """wayworks' side: harness-init still creates the names Nemo reads."""

    def setUp(self) -> None:
        self.init = HARNESS_INIT.read_text()

    def test_harness_init_creates_every_convention_file(self) -> None:
        missing = [name for name in seam.CONVENTION_FILES if name not in self.init]
        self.assertEqual(
            missing, [],
            f"wayworks harness-init no longer creates: {missing}. "
            "A convention was renamed on one side of the seam and not the other.",
        )


if __name__ == "__main__":
    unittest.main()
