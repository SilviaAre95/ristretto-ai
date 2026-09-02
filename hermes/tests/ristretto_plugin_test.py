#!/usr/bin/env python3
"""The Slack answering path.

What matters here is that a decision is a decision: the handler shells a
fixed command, and no model sits between the operator's words and the store.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ris_approvals_plugin", ROOT / "hermes" / "plugins" / "ris-approvals" / "__init__.py"
)
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


class CommandTest(unittest.TestCase):
    def setUp(self) -> None:
        which = mock.patch.object(plugin.shutil, "which", return_value="/usr/local/bin/ristretto")
        which.start()
        self.addCleanup(which.stop)
        run = mock.patch.object(subprocess, "run")
        self.run = run.start()
        self.addCleanup(run.stop)
        # The handler asks the store what is pending before deciding whether
        # the first word is an id, so the stub has to answer both questions
        # the way the real CLI does.
        self.pending_listing = (
            "a1b2c3  t_a1b2c3d4  Bash: git push --force  (30m left)\n"
            "slack-live-1  t_6ac82896  Bash: npm run db:migrate  (59m left)"
        )

        def fake(argv, **kwargs):
            if "pending" in argv:
                return subprocess.CompletedProcess(argv, 0, self.pending_listing, "")
            return subprocess.CompletedProcess(argv, 0, "a1b2c3: allow", "")

        self.run.side_effect = fake

    def argv(self) -> list[str]:
        """The deciding call — the pending lookup runs first and is not it."""
        for call in reversed(self.run.call_args_list):
            argv = call.args[0]
            if "pending" not in argv:
                return argv
        raise AssertionError("no deciding call was made")

    def test_a_bare_approve_names_no_request(self) -> None:
        # The CLI resolves it when exactly one is pending and refuses when
        # more are, which is where that judgement belongs.
        plugin.approve("")
        self.assertEqual(self.argv()[1:3], ["approvals", "approve"])
        self.assertNotIn("--reason", self.argv())

    def test_an_id_is_passed_through(self) -> None:
        plugin.approve("a1b2c3")
        self.assertIn("a1b2c3", self.argv())

    def test_the_actor_is_recorded_as_slack(self) -> None:
        # So the dashboard can say who answered when it loses the race.
        plugin.deny("a1b2c3")
        self.assertEqual(self.argv()[self.argv().index("--actor") + 1], "slack")

    def test_a_denial_carries_its_reason(self) -> None:
        plugin.deny("a1b2c3 not on a friday")
        self.assertEqual(self.argv()[self.argv().index("--reason") + 1], "not on a friday")

    def test_approve_never_sends_a_reason(self) -> None:
        plugin.approve("a1b2c3 whatever they typed")
        self.assertNotIn("--reason", self.argv())

    def test_a_missing_binary_is_reported_not_swallowed(self) -> None:
        with mock.patch.object(plugin.shutil, "which", return_value=None):
            self.assertIn("not on PATH", plugin.approve("a1"))
        self.run.assert_not_called()

    def test_an_unreachable_store_is_reported(self) -> None:
        self.run.side_effect = OSError("boom")
        self.assertIn("could not reach", plugin.approve("a1"))

    def test_a_timeout_does_not_raise(self) -> None:
        self.run.side_effect = subprocess.TimeoutExpired("ristretto", 30)
        self.assertIn("could not reach", plugin.deny("a1"))


class RegistrationTest(unittest.TestCase):
    def test_it_registers_the_three_commands(self) -> None:
        registered: dict[str, object] = {}

        class Ctx:
            def register_command(self, name, handler, description="", args_hint=""):
                registered[name] = handler

        plugin.register(Ctx())
        self.assertEqual(
            sorted(registered), ["ris-approve", "ris-deny", "ris-pending"]
        )

    def test_no_model_sits_in_the_decision_path(self) -> None:
        # The gate exists because a person is being asked. An agent that also
        # reads issue text and code comments must not be the one answering.
        source = (ROOT / "hermes" / "plugins" / "ris-approvals" / "__init__.py").read_text()
        # Whole words, not substrings: the first version of this test matched
        # "llm" inside "fullmatch" and failed on a regex call.
        for forbidden in (
            r"\bhermes\s+send\b", r"\bclaude\b", r"\bllm\b",
            r"\bopenai\b", r"\brun_agent\b", r"\bchat_completion\b",
        ):
            self.assertIsNone(
                re.search(forbidden, source, re.IGNORECASE),
                f"{forbidden} appears in the decision path",
            )


if __name__ == "__main__":
    unittest.main()


class ArgumentParsingTest(CommandTest):
    """What a chat client actually sends is not what someone typed."""

    def test_client_boilerplate_is_not_taken_for_an_id(self) -> None:
        # Slack delivered "!ris-approve *Sent using* Claude ...", so "*Sent"
        # became the request id and the reply read "no such approval".
        plugin.approve("*Sent using* Claude")
        argv = self.argv()
        self.assertNotIn("*Sent", argv)
        self.assertEqual(argv[1:3], ["approvals", "approve"])

    def test_a_real_id_is_still_passed(self) -> None:
        plugin.approve("slack-live-1")
        self.assertIn("slack-live-1", self.argv())

    def test_prose_after_a_deny_becomes_the_reason(self) -> None:
        plugin.deny("not right now")
        argv = self.argv()
        self.assertEqual(argv[argv.index("--reason") + 1], "not right now")
        self.assertNotIn("not", argv[:4])

    def test_an_id_then_prose_splits_correctly(self) -> None:
        plugin.deny("slack-live-1 not on a friday")
        argv = self.argv()
        self.assertIn("slack-live-1", argv)
        self.assertEqual(argv[argv.index("--reason") + 1], "not on a friday")
