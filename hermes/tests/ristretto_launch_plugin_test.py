#!/usr/bin/env python3
"""The Slack launch command. Deterministic: no model decides what runs."""

from __future__ import annotations

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ris_launch_plugin", ROOT / "hermes" / "plugins" / "ris-launch" / "__init__.py"
)
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


class ParseTest(unittest.TestCase):
    def setUp(self) -> None:
        which = mock.patch.object(plugin.shutil, "which", return_value="/usr/bin/ristretto")
        which.start(); self.addCleanup(which.stop)
        run = mock.patch.object(subprocess, "run")
        self.run = run.start(); self.addCleanup(run.stop)
        self.run.return_value = subprocess.CompletedProcess([], 0, "XARI-42 started", "")

    def argv(self) -> list[str]:
        return self.run.call_args.args[0]

    def test_a_full_command_maps_to_the_cli(self) -> None:
        plugin.start("XARI-42 tier1 unattended project:Kaffecard")
        self.assertEqual(
            self.argv()[1:],
            ["launch", "Kaffecard", "XARI-42", "--flow", "tier1", "--actor", "slack", "--unattended"],
        )

    def test_the_default_flow_is_tier1_and_attended(self) -> None:
        plugin.start("XARI-7 project:Krome")
        argv = self.argv()
        self.assertIn("tier1", argv)
        self.assertNotIn("--unattended", argv)

    def test_a_lowercase_key_is_upcased(self) -> None:
        plugin.start("xari-9 project:Kaffecard")
        self.assertIn("XARI-9", self.argv())

    def test_the_actor_is_slack(self) -> None:
        plugin.start("XARI-1 project:Kaffecard")
        self.assertEqual(self.argv()[self.argv().index("--actor") + 1], "slack")

    def test_chat_client_noise_after_the_command_is_ignored(self) -> None:
        # Slack appends "*Sent using* Claude"; a stray word must not block a launch.
        plugin.start("XARI-42 tier2 project:Kaffecard *Sent using* Claude")
        argv = self.argv()
        self.assertIn("XARI-42", argv)
        self.assertIn("tier2", argv)

    def test_a_missing_issue_is_explained_not_launched(self) -> None:
        plugin.start("do the thing")
        self.assertFalse(self.run.called)

    def test_a_missing_project_is_explained_not_launched(self) -> None:
        # The ambiguity is real: every project shares the XARI prefix.
        msg = plugin.start("XARI-42")
        self.assertIn("which project", msg.lower())
        self.assertFalse(self.run.called)


class SafetyTest(unittest.TestCase):
    def test_a_missing_binary_is_reported(self) -> None:
        with mock.patch.object(plugin.shutil, "which", return_value=None):
            self.assertIn("not on PATH", plugin.start("XARI-42 project:Kaffecard"))

    def test_a_launcher_that_hangs_does_not_raise(self) -> None:
        with mock.patch.object(plugin.shutil, "which", return_value="/usr/bin/ristretto"), \
             mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("ristretto", 120)):
            self.assertIn("could not start", plugin.start("XARI-42 project:Kaffecard"))

    def test_no_model_sits_in_the_launch_path(self) -> None:
        # No model *call* in the path — the docstring may discuss agents, but
        # nothing here imports or invokes one. Match call shapes, not prose.
        source = (ROOT / "hermes" / "plugins" / "ris-launch" / "__init__.py").read_text()
        import re
        for forbidden in (r"import\s+\w*(openai|anthropic)", r"\brun_agent\b",
                          r"chat_completion", r"messages\.create", r"hermes\s+send"):
            self.assertIsNone(re.search(forbidden, source, re.IGNORECASE), forbidden)


if __name__ == "__main__":
    unittest.main()
