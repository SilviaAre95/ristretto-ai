#!/usr/bin/env python3
"""Nemo's agent loop — the assembly and the guards, not the live model.

The live behaviour (does Claude call the tool, does resume carry context) is
verified by hand against the real model; these pin the parts that must not
drift: the provider choice, the command shape, and that a surface always gets
an answer.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from ristretto.assistant import loop, tools


class ProviderChoiceTest(unittest.TestCase):
    def test_defaults_to_claude(self) -> None:
        self.assertEqual(loop.provider_name({}), "claude")

    def test_config_can_switch_the_provider(self) -> None:
        cfg = {"instance": {"assistant_provider": "local-brain"}}
        self.assertEqual(loop.provider_name(cfg), "local-brain")


class CommandShapeTest(unittest.TestCase):
    def build(self, session=None):
        provider = {"runner": "claude-code", "model": "sonnet"}
        return loop._command(provider, "what is running?", session)

    def test_the_tool_server_and_read_tools_are_granted(self) -> None:
        cmd, _env, _sid = self.build()
        self.assertIn("--mcp-config", cmd)
        allowed = cmd[cmd.index("--allowedTools") + 1:]
        self.assertIn("mcp__nemo-tools__fleet_status", allowed)

    def test_a_variadic_flag_is_never_last_before_the_prompt(self) -> None:
        # --mcp-config and --allowedTools both take lists; the prompt must not
        # be swallowed (broker.py paid for this lesson once).
        cmd, _e, _s = self.build()
        for variadic in ("--mcp-config", "--allowedTools"):
            after = cmd[cmd.index(variadic) + 1:]
            self.assertTrue(any(x.startswith("--") for x in after), variadic)
        self.assertEqual(cmd[-1], "what is running?")

    def test_it_runs_tools_not_plan_mode(self) -> None:
        # plan mode blocks tool execution — the one thing this loop exists to do.
        cmd, _e, _s = self.build()
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "default")
        self.assertNotIn("--no-session-persistence", cmd)

    def test_a_fresh_conversation_gets_a_session_id(self) -> None:
        cmd, _e, sid = self.build()
        self.assertIn("--session-id", cmd)
        self.assertTrue(sid)

    def test_continuing_resumes_the_given_session(self) -> None:
        cmd, _e, sid = self.build(session="abc-123")
        self.assertIn("--resume", cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], "abc-123")
        self.assertEqual(sid, "abc-123")


class SafetyTest(unittest.TestCase):
    def test_empty_input_asks_for_input(self) -> None:
        self.assertFalse(loop.ask("   ").ok)

    def test_a_failed_turn_still_returns_the_session(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=OSError("no claude")):
            turn = loop.ask("hi")
        self.assertFalse(turn.ok)
        self.assertTrue(turn.session)

    def test_a_timeout_does_not_raise(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 180)):
            self.assertFalse(loop.ask("hi").ok)


class ToolTest(unittest.TestCase):
    def test_fleet_status_never_raises(self) -> None:
        with mock.patch("ristretto.dash.data.fleet", side_effect=RuntimeError("boom")):
            out = tools.fleet_status()
        self.assertIn("error", out)
        self.assertEqual(out["runs"], [])

    def test_only_read_tools_in_v1(self) -> None:
        # A mutating tool must not appear without the approval gate, which is
        # not built yet. This test is the tripwire for that. fleet_status,
        # search_memory and read_note are all read-only.
        self.assertEqual(set(tools.TOOLS), {"fleet_status", "search_memory", "read_note"})


if __name__ == "__main__":
    unittest.main()


class VaultReaderTest(unittest.TestCase):
    """Nemo reading its long-term memory. Read-only, and never leaves the vault."""

    def setUp(self) -> None:
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        (self.root / "02-Projects").mkdir()
        (self.root / "_agent").mkdir()
        (self.root / "02-Projects" / "kaffecard.md").write_text(
            '---\nsummary: "Kaffecard loyalty platform for Austrian cafes"\n---\n'
            "# Kaffecard\nThe campaign engine sends push notifications.\n"
        )
        (self.root / "_agent" / "INSTRUCTIONS.md").write_text(
            '---\nsummary: "agent rules"\n---\nignore me\n'
        )
        self.config = {"instance": {"knowledge_vault": str(self.root)}}

    def test_search_finds_by_summary(self) -> None:
        from ristretto.assistant import vault
        r = vault.search("loyalty Austrian", self.config)
        self.assertEqual(r["total_matched"], 1)
        self.assertEqual(r["notes"][0]["title"], "kaffecard")

    def test_search_finds_by_body(self) -> None:
        from ristretto.assistant import vault
        self.assertEqual(vault.search("push notifications", self.config)["total_matched"], 1)

    def test_agent_machinery_is_not_searched(self) -> None:
        from ristretto.assistant import vault
        # _agent notes are vault plumbing, not knowledge.
        self.assertEqual(vault.search("ignore me", self.config)["total_matched"], 0)

    def test_read_returns_the_note(self) -> None:
        from ristretto.assistant import vault
        r = vault.read("02-Projects/kaffecard.md", self.config)
        self.assertIn("campaign engine", r["text"])

    def test_a_path_escape_is_refused(self) -> None:
        from ristretto.assistant import vault
        for attack in ("../../../etc/passwd", "/etc/passwd", "02-Projects/../../secrets"):
            self.assertIn("error", vault.read(attack, self.config))

    def test_no_vault_configured_is_not_a_crash(self) -> None:
        from ristretto.assistant import vault
        self.assertIn("error", vault.search("anything", {"instance": {}}))


class ToolSurfaceTest(unittest.TestCase):
    def test_v1_tools_are_read_only(self) -> None:
        # The tripwire: a mutating tool must not appear without the approval
        # gate, which is not built yet.
        self.assertEqual(set(tools.TOOLS), {"fleet_status", "search_memory", "read_note"})

    def test_the_vault_tools_carry_a_query_schema(self) -> None:
        # A tool with no declared params is one the model calls with none.
        _desc, _fn, props = tools.TOOLS["search_memory"]
        self.assertIn("query", props)
