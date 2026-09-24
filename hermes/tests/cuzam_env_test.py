#!/usr/bin/env python3
"""Reading a setting that has two names for one release.

The case worth testing is not "the old name works". It is the one where
getting it wrong is invisible: an unread `RISTRETTO_STATE_HOME` does not
raise, it resolves to the default, and a run then opens an empty event store
beside the real one while every surface agrees nothing ever happened.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cuzam import env, events  # noqa: E402


class LegacyNameTest(unittest.TestCase):
    def test_both_prefixes_map_back(self) -> None:
        self.assertEqual(env.legacy_name("CUZAM_STATE_HOME"), "RISTRETTO_STATE_HOME")
        self.assertEqual(env.legacy_name("ZAM_PYTHON"), "RIS_PYTHON")

    def test_an_unrenamed_name_is_a_mistake_in_the_caller(self) -> None:
        # Deriving the old name by chopping at the first underscore would
        # turn a typo into a variable that silently never falls back.
        with self.assertRaises(ValueError):
            env.legacy_name("HERMES_HOME")


class FallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        env._announced.clear()

    def test_the_current_name_is_read(self) -> None:
        self.assertEqual(env.get("CUZAM_STATE_HOME", None, {"CUZAM_STATE_HOME": "/new"}), "/new")

    def test_the_old_name_is_still_read(self) -> None:
        self.assertEqual(
            env.get("CUZAM_STATE_HOME", None, {"RISTRETTO_STATE_HOME": "/old"}), "/old"
        )

    def test_the_current_name_wins_when_both_are_set(self) -> None:
        value = env.get(
            "CUZAM_STATE_HOME", None,
            {"CUZAM_STATE_HOME": "/new", "RISTRETTO_STATE_HOME": "/old"},
        )
        self.assertEqual(value, "/new")

    def test_an_empty_current_value_counts_as_set(self) -> None:
        # Exporting CUZAM_STATE_HOME="" to mean "use the default" must not be
        # overridden by a stale RISTRETTO_STATE_HOME in the same environment.
        value = env.get(
            "CUZAM_STATE_HOME", "/default",
            {"CUZAM_STATE_HOME": "", "RISTRETTO_STATE_HOME": "/old"},
        )
        self.assertEqual(value, "")

    def test_neither_set_gives_the_default(self) -> None:
        self.assertEqual(env.get("CUZAM_STATE_HOME", "/default", {}), "/default")


class StateHomeTest(unittest.TestCase):
    """The reader where a missed fallback is worst."""

    def setUp(self) -> None:
        env._announced.clear()

    def test_a_pre_rename_environment_still_finds_its_state(self) -> None:
        # Not hypothetical: the launchd plist, the cron entries and any shell
        # profile all export the old name until they are edited by hand.
        self.assertEqual(
            events.state_home({"RISTRETTO_STATE_HOME": "/old/state"}),
            Path("/old/state"),
        )

    def test_nothing_set_is_the_new_default(self) -> None:
        self.assertEqual(events.state_home({}), Path.home() / ".cuzam")


if __name__ == "__main__":
    unittest.main()
