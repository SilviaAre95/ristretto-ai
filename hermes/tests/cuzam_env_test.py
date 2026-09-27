#!/usr/bin/env python3
"""Reading a setting that has two names for one release.

The case worth testing is not "the old name works". It is the one where
getting it wrong is invisible: an unread `RISTRETTO_STATE_HOME` does not
raise, it resolves to the default, and a run then opens an empty event store
beside the real one while every surface agrees nothing ever happened.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cuzam import config, env, events  # noqa: E402


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


class HermesHomeTest(unittest.TestCase):
    """The one `RISTRETTO_*` reader that used to say nothing.

    `hermes_home` read all three names straight from the environment, so a
    machine still exporting the old spelling worked and was never told it was
    on a shim. It is also the reader whose failure after 0.3.0 is least
    diagnosable: Hermes resolves to `~/.hermes`, which exists, and the symptom
    is "not installed" rather than "you renamed a variable".
    """

    def setUp(self) -> None:
        env._announced.clear()

    def _capture(self) -> contextlib.AbstractContextManager:
        return contextlib.redirect_stderr(io.StringIO())

    def test_the_installers_order_is_preserved(self) -> None:
        self.assertEqual(config.hermes_home({"CUZAM_HERMES_HOME": "/a"}), Path("/a"))
        self.assertEqual(config.hermes_home({"HERMES_HOME": "/c"}), Path("/c"))
        self.assertEqual(
            config.hermes_home({"CUZAM_HERMES_HOME": "/a", "HERMES_HOME": "/c"}),
            Path("/a"),
        )

    def test_the_new_name_wins_over_the_old(self) -> None:
        with self._capture():
            found = config.hermes_home(
                {"CUZAM_HERMES_HOME": "/a", "RISTRETTO_HERMES_HOME": "/b"}
            )
        self.assertEqual(found, Path("/a"))

    def test_a_pre_rename_environment_still_finds_hermes(self) -> None:
        with self._capture():
            self.assertEqual(
                config.hermes_home({"RISTRETTO_HERMES_HOME": "/b"}), Path("/b")
            )

    def test_the_legacy_name_announces_itself(self) -> None:
        """The point of the change, and the part with no coverage before.

        A fallback nobody is told about is a fallback nobody removes — and this
        was the only `RISTRETTO_*` read in the package that printed nothing.
        """
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            config.hermes_home({"RISTRETTO_HERMES_HOME": "/b"})
        self.assertIn("RISTRETTO_HERMES_HOME is deprecated", stream.getvalue())
        self.assertIn("0.3.0", stream.getvalue())

    def test_hermes_own_name_is_not_deprecated(self) -> None:
        """`HERMES_HOME` belongs to Hermes and outlives the shim."""
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            config.hermes_home({"HERMES_HOME": "/c"})
        self.assertEqual(stream.getvalue(), "")

    def test_an_empty_new_name_means_the_default(self) -> None:
        """`env.py`'s documented semantics, which this reader now shares.

        Exporting `CUZAM_HERMES_HOME=""` to mean "use the default" must not
        then be overridden by a stale `RISTRETTO_HERMES_HOME` beside it. The
        shell scripts use `${A:-${B:-...}}` and fall through on empty, so they
        differ in exactly this corner; the Python semantics are the documented
        ones.
        """
        with self._capture():
            found = config.hermes_home(
                {"CUZAM_HERMES_HOME": "", "RISTRETTO_HERMES_HOME": "/b"}
            )
        self.assertEqual(found, Path.home() / ".hermes")

    def test_nothing_set_is_hermes_default(self) -> None:
        self.assertEqual(config.hermes_home({}), Path.home() / ".hermes")


class ConfigDirTest(unittest.TestCase):
    """The other installer/package split, found while fixing the first one.

    `install.sh`, `uninstall.sh` and `migrate-cuzam.sh` all resolve
    `${CUZAM_CONFIG_DIR:-${RISTRETTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-...}/cuzam}}`.
    Python honoured only `XDG_CONFIG_HOME`, so on a machine setting
    `CUZAM_CONFIG_DIR` the installer wrote a configuration no reader here ever
    opened — and the symptom is the shipped defaults being used while a
    perfectly good user config sits on disk.
    """

    def setUp(self) -> None:
        env._announced.clear()

    def test_the_installers_chain_is_honoured_in_order(self) -> None:
        self.assertEqual(config.config_dir({"CUZAM_CONFIG_DIR": "/c"}), Path("/c"))
        self.assertEqual(
            config.config_dir({"XDG_CONFIG_HOME": "/x"}), Path("/x/cuzam")
        )
        self.assertEqual(
            config.config_dir({"CUZAM_CONFIG_DIR": "/c", "XDG_CONFIG_HOME": "/x"}),
            Path("/c"),
        )
        self.assertEqual(config.config_dir({}), Path.home() / ".config" / "cuzam")

    def test_the_legacy_directory_name_still_works_and_says_so(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            found = config.config_dir({"RISTRETTO_CONFIG_DIR": "/r"})
        self.assertEqual(found, Path("/r"))
        self.assertIn("RISTRETTO_CONFIG_DIR is deprecated", stream.getvalue())
        self.assertIn("0.3.0", stream.getvalue())

    def test_the_config_and_secrets_paths_both_follow_it(self) -> None:
        """The whole point: a reader that ignored it read the wrong file."""
        self.assertEqual(
            config.user_config_path({"CUZAM_CONFIG_DIR": "/c"}), Path("/c/config.yaml")
        )
        self.assertEqual(
            config.user_env_path({"CUZAM_CONFIG_DIR": "/c"}), Path("/c/env")
        )

    def test_an_explicit_config_file_still_wins(self) -> None:
        self.assertEqual(
            config.user_config_path({"CUZAM_CONFIG": "/f.yaml", "CUZAM_CONFIG_DIR": "/c"}),
            Path("/f.yaml"),
        )


if __name__ == "__main__":
    unittest.main()
