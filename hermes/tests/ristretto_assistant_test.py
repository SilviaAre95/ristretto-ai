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
    def build(self, session=None, is_new=True):
        provider = {"runner": "claude-code", "model": "sonnet"}
        return loop._command(provider, "what is running?", session, is_new)

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
        # A continuing turn (is_new=False) resumes; a brand-new session id is
        # created with --session-id, never resumed (resuming a non-existent
        # session fails with "No conversation found").
        cmd, _e, sid = self.build(session="abc-123", is_new=False)
        self.assertIn("--resume", cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], "abc-123")
        self.assertEqual(sid, "abc-123")

    def test_a_new_conversation_creates_rather_than_resumes(self) -> None:
        cmd, _e, _sid = self.build(session="fresh-1", is_new=True)
        self.assertIn("--session-id", cmd)
        self.assertNotIn("--resume", cmd)


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

    def test_the_tool_set_is_reads_plus_launch(self) -> None:
        # The gate is for merge and deploy — the dangerous, per-repo actions.
        # Launching a run is dev work: it produces a PR the user reviews, so it
        # is a permitted tool. This is the tripwire for a *gated* action (merge,
        # deploy) appearing without its gate: if one shows up here, it needs
        # more than a set-membership update.
        self.assertEqual(
            set(tools.TOOLS),
            {"fleet_status", "search_memory", "read_note", "launch_run", "propose_merge"},
        )
        # A gated action must reach the human as a PROPOSAL, never execute on
        # the model's call. propose_merge is fine (it queues an approval);
        # merge_pr / deploy as tools the model runs directly are not.
        for direct in ("merge_pr", "deploy", "delete", "push_main"):
            self.assertNotIn(direct, tools.TOOLS,
                             f"{direct} would execute on the model's say-so — must be gated")


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
    def test_the_tool_set_is_reads_plus_launch(self) -> None:
        # launch_run is a permitted dev action (produces a PR to review); the
        # gated actions are merge and deploy, which must not appear as bare
        # tools.
        self.assertEqual(
            set(tools.TOOLS),
            {"fleet_status", "search_memory", "read_note", "launch_run", "propose_merge"},
        )

    def test_the_vault_tools_carry_a_query_schema(self) -> None:
        # A tool with no declared params is one the model calls with none.
        _desc, _fn, props = tools.TOOLS["search_memory"]
        self.assertIn("query", props)


class ConversationMemoryTest(unittest.TestCase):
    """A named conversation keeps one session across turns."""

    def setUp(self) -> None:
        import tempfile
        from ristretto import events
        self.dir = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(events, "state_home", return_value=self.dir)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_first_turn_is_new_and_the_same_key_resumes(self) -> None:
        s1, new1 = loop._session_for("slack:C1")
        s2, new2 = loop._session_for("slack:C1")
        self.assertTrue(new1)
        self.assertFalse(new2)
        self.assertEqual(s1, s2)

    def test_different_conversations_do_not_share_a_session(self) -> None:
        a, _ = loop._session_for("slack:C1")
        b, _ = loop._session_for("dashboard:main")
        self.assertNotEqual(a, b)

    def test_a_one_off_turn_has_no_conversation(self) -> None:
        session, is_new = loop._session_for(None)
        self.assertIsNone(session)
        self.assertTrue(is_new)


class LaunchToolTest(unittest.TestCase):
    """launch_run is a dev action: it executes, guarded by launch.launch."""

    def test_a_missing_project_is_refused_not_launched(self) -> None:
        # Issue keys are ambiguous across repos; guessing is worse than asking.
        r = tools.launch_run(issue="XARI-26")
        self.assertFalse(r["ok"])
        self.assertIn("project", r["message"].lower())

    def test_it_calls_the_launcher_with_nemo_as_actor(self) -> None:
        from ristretto.dash import launch as launcher
        with mock.patch.object(launcher, "launch",
                               return_value=launcher.Outcome(True, "started", "t_x")) as spawned:
            r = tools.launch_run(project="Kaffecard", issue="xari-26", flow="tier1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["task_id"], "t_x")
        kwargs = spawned.call_args
        self.assertEqual(kwargs.args[0], "Kaffecard")
        self.assertEqual(kwargs.args[1], "XARI-26")  # upcased
        self.assertEqual(kwargs.kwargs["actor"], "nemo")

    def test_the_loop_grants_launch_run_to_the_model(self) -> None:
        # A tool the model is not allowed to call is a tool that never runs.
        cmd, _e, _s = loop._command({"runner": "claude-code", "model": "sonnet"},
                                    "start a run", None)
        allowed = cmd[cmd.index("--allowedTools") + 1:]
        self.assertIn("mcp__nemo-tools__launch_run", allowed)
