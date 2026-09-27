#!/usr/bin/env python3
"""Zam's agent loop — the assembly and the guards, not the live model.

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

from cuzam import config as cfg
from cuzam.assistant import loop, tools


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
        self.assertIn("mcp__zam-tools__fleet_status", allowed)

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

    def test_a_failed_turn_hands_back_no_session(self) -> None:
        # This used to assert the opposite. That pinned the defect in #80: an
        # id for a session `claude` may never have created, which a client
        # stores and then --resumes forever. A failed turn now carries none.
        with mock.patch.object(subprocess, "run", side_effect=OSError("no claude")):
            turn = loop.ask("hi")
        self.assertFalse(turn.ok)
        self.assertEqual(turn.session, "")

    def test_a_timeout_does_not_raise(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 180)):
            self.assertFalse(loop.ask("hi").ok)


class ToolTest(unittest.TestCase):
    def test_fleet_status_never_raises(self) -> None:
        with mock.patch("cuzam.runs.fleet", side_effect=RuntimeError("boom")):
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
    """Zam reading its long-term memory. Read-only, and never leaves the vault."""

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
        from cuzam.assistant import vault
        r = vault.search("loyalty Austrian", self.config)
        self.assertEqual(r["total_matched"], 1)
        self.assertEqual(r["notes"][0]["title"], "kaffecard")

    def test_search_finds_by_body(self) -> None:
        from cuzam.assistant import vault
        self.assertEqual(vault.search("push notifications", self.config)["total_matched"], 1)

    def test_agent_machinery_is_not_searched(self) -> None:
        from cuzam.assistant import vault
        # _agent notes are vault plumbing, not knowledge.
        self.assertEqual(vault.search("ignore me", self.config)["total_matched"], 0)

    def test_read_returns_the_note(self) -> None:
        from cuzam.assistant import vault
        r = vault.read("02-Projects/kaffecard.md", self.config)
        self.assertIn("campaign engine", r["text"])

    def test_a_path_escape_is_refused(self) -> None:
        from cuzam.assistant import vault
        for attack in ("../../../etc/passwd", "/etc/passwd", "02-Projects/../../secrets"):
            self.assertIn("error", vault.read(attack, self.config))

    def test_no_vault_configured_is_not_a_crash(self) -> None:
        from cuzam.assistant import vault
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
        from cuzam import events
        self.dir = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(events, "state_home", return_value=self.dir)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_reading_a_name_does_not_claim_it(self) -> None:
        # _session_for used to WRITE the mapping before the turn ran, which is
        # the live half of #80: a first turn that failed left the name pointing
        # at a session that never existed, and every later turn --resumed
        # nothing. Reading proposes; only a successful turn records.
        s1, new1 = loop._session_for("slack:C1")
        _s2, new2 = loop._session_for("slack:C1")
        self.assertTrue(new1)
        self.assertTrue(new2, "reading a name must not record it")
        self.assertFalse(self.dir.joinpath("conversations.json").exists())

    def test_a_remembered_session_then_resumes(self) -> None:
        s1, new1 = loop._session_for("slack:C1")
        self.assertTrue(new1)
        loop._remember_session("slack:C1", s1)
        s2, new2 = loop._session_for("slack:C1")
        self.assertEqual(s2, s1)
        self.assertFalse(new2)

    def test_different_conversations_do_not_share_a_session(self) -> None:
        a, _ = loop._session_for("slack:C1")
        b, _ = loop._session_for("dashboard:main")
        self.assertNotEqual(a, b)

    def test_a_one_off_turn_has_no_conversation(self) -> None:
        session, is_new = loop._session_for(None)
        self.assertIsNone(session)
        self.assertTrue(is_new)


class ProposeMergeTest(unittest.TestCase):
    """`gh ... --jq '.[0]'` prints "null" for no match, not an empty line."""

    def _propose(self, stdout: str):
        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        with mock.patch.object(cfg, "load_config", return_value=({}, None)), \
             mock.patch.object(cfg, "repository_path", return_value=Path("/tmp/r")), \
             mock.patch.object(subprocess, "run", return_value=done):
            return tools.propose_merge(project="Kaffecard", issue="XARI-26")

    def _propose_with_slug(self, stdout: str, slug: str):
        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        with mock.patch.object(cfg, "load_config", return_value=({}, None)), \
             mock.patch.object(cfg, "repository_path", return_value=Path("/tmp/r")), \
             mock.patch.object(subprocess, "run", return_value=done), \
             mock.patch.object(tools, "_repo_slug", return_value=slug):
            return tools.propose_merge(project="Kaffecard", issue="XARI-26")

    def test_a_gh_failure_is_not_reported_as_no_pr(self) -> None:
        # Unauthenticated, off PATH, offline, no GitHub remote: all non-zero
        # with empty stdout. Saying "no open PR" states a falsehood as fact.
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="gh: not logged in")
        with mock.patch.object(cfg, "load_config", return_value=({}, None)), \
             mock.patch.object(cfg, "repository_path", return_value=Path("/tmp/r")), \
             mock.patch.object(subprocess, "run", return_value=failed):
            out = tools.propose_merge(project="Kaffecard", issue="XARI-26")
        self.assertFalse(out["ok"])
        self.assertNotIn("No open PR", out["message"])
        self.assertIn("GitHub", out["message"])

    def test_an_unreadable_remote_refuses_rather_than_colliding(self) -> None:
        # record_merge keys on f"merge-{slug}-{number}" and upserts, so an empty
        # slug makes "merge--123" — colliding with PR 123 in every other repo.
        out = self._propose_with_slug('{"number": 123, "title": "t", "url": "u"}', "")
        self.assertFalse(out["ok"])
        self.assertIn("remote", out["message"].lower())

    def test_no_open_pr_is_reported_not_raised(self) -> None:
        # The bug: "null" is truthy, so the guard never fired and pr["number"]
        # raised TypeError exactly where this message belongs.
        for empty in ("null", "", "   ", "not json"):
            with self.subTest(stdout=empty):
                out = self._propose(empty)
                self.assertFalse(out["ok"])
                self.assertIn("No open PR", out["message"])


class FleetCountTest(unittest.TestCase):
    """Issue #82: the counts are for the whole fleet, the list is capped."""

    class _Run:
        def __init__(self, i, health):
            self.issue_key, self.task_id = f"XARI-{i}", f"t_{i}"
            self.project, self.status, self.stage = "p", "s", "build"
            self.health = health

    def test_a_live_run_past_the_cap_is_still_counted(self) -> None:
        # The cap is 20. A live run at index 24 was invisible to the counts, so
        # the assistant said "0 live" out of a total of 48 and was confidently
        # wrong about the one thing the question asks.
        runs = [self._Run(i, "done") for i in range(24)] + [self._Run(99, "running")]
        with mock.patch("cuzam.runs.fleet", return_value=runs):
            out = tools.fleet_status()
        self.assertEqual(out["total"], 25)
        self.assertEqual(out["live"], 1)
        self.assertEqual(len(out["runs"]), tools.MAX_RUNS_SHOWN)

    def test_truncation_is_stated_so_the_slice_is_not_read_as_the_fleet(self) -> None:
        runs = [self._Run(i, "done") for i in range(25)]
        with mock.patch("cuzam.runs.fleet", return_value=runs):
            out = tools.fleet_status()
        self.assertIn("runs_truncated", out)
        self.assertIn("25", out["runs_truncated"])

    def test_a_small_fleet_says_nothing_about_truncation(self) -> None:
        runs = [self._Run(i, "running") for i in range(3)]
        with mock.patch("cuzam.runs.fleet", return_value=runs):
            out = tools.fleet_status()
        self.assertNotIn("runs_truncated", out)
        self.assertEqual(out["live"], 3)


class SessionLifecycleTest(unittest.TestCase):
    """Issue #80: a session is recorded only once a turn has established it."""

    def setUp(self) -> None:
        import tempfile
        from cuzam import events
        self.dir = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(events, "state_home", return_value=self.dir)
        patcher.start(); self.addCleanup(patcher.stop)
        cfgp = mock.patch.object(loop, "load_config", return_value=({}, None))
        cfgp.start(); self.addCleanup(cfgp.stop)
        prov = mock.patch.object(loop, "resolved_provider",
                                 return_value={"runner": "claude-code", "model": "sonnet"})
        prov.start(); self.addCleanup(prov.stop)

    def _store(self) -> dict:
        import json
        path = self.dir / "conversations.json"
        return json.loads(path.read_text()) if path.is_file() else {}

    def test_a_failed_first_turn_does_not_wedge_the_conversation(self) -> None:
        # The live bug: one failed !zam mapped a Slack channel to a session
        # claude never created, and nothing pruned it, so that channel failed
        # forever. Nothing may be recorded for a turn that did not happen.
        dead = subprocess.CompletedProcess([], 1, stdout="", stderr="claude exploded")
        with mock.patch.object(subprocess, "run", return_value=dead):
            turn = loop.ask("hello", conversation="slack:C123")
        self.assertFalse(turn.ok)
        self.assertEqual(self._store(), {}, "a failed turn must record nothing")

    def test_a_successful_turn_records_the_thread(self) -> None:
        good = subprocess.CompletedProcess([], 0, stdout="hello back", stderr="")
        with mock.patch.object(subprocess, "run", return_value=good):
            turn = loop.ask("hello", conversation="slack:C123")
        self.assertTrue(turn.ok)
        self.assertEqual(self._store().get("slack:C123"), turn.session)

    def test_a_poisoned_store_heals_instead_of_failing_forever(self) -> None:
        # Stores written before this fix exist on real machines. A resume that
        # finds no conversation must recover once, not fail for good.
        import json
        (self.dir / "conversations.json").write_text(json.dumps({"slack:C9": "ghost-session"}))
        calls = []

        def fake_run(command, **_kw):
            calls.append(command)
            if "--resume" in command:
                return subprocess.CompletedProcess(
                    command, 1, stdout="",
                    stderr="No conversation found with session ID: ghost-session")
            return subprocess.CompletedProcess(command, 0, stdout="recovered", stderr="")

        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            turn = loop.ask("still there?", conversation="slack:C9")
        self.assertTrue(turn.ok, "a stale mapping must not fail the turn")
        self.assertEqual(turn.text, "recovered")
        self.assertIn("--resume", calls[0])
        self.assertIn("--session-id", calls[1])
        self.assertNotEqual(self._store().get("slack:C9"), "ghost-session")

    def test_a_supplied_session_is_resumed_not_recreated(self) -> None:
        seen = {}

        def fake_run(command, **_kw):
            seen["cmd"] = command
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            turn = loop.ask("go on", session="established-earlier")
        self.assertTrue(turn.ok)
        self.assertIn("--resume", seen["cmd"])
        self.assertNotIn("--session-id", seen["cmd"])


class WorkingDirectoryTest(unittest.TestCase):
    """Issue #81: the loop's context is Zam's, not the caller's directory."""

    def test_claude_does_not_run_in_the_callers_directory(self) -> None:
        # Measured: run from inside this repo with no cwd, the model answered a
        # memory question from the inherited CLAUDE.md and asserted nothing
        # else was stored, while eight vault notes existed.
        seen = {}

        def fake_run(command, **kwargs):
            seen["cwd"] = kwargs.get("cwd")
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        with mock.patch.object(loop, "load_config", return_value=({}, None)), \
             mock.patch.object(loop, "resolved_provider",
                               return_value={"runner": "claude-code", "model": "sonnet"}), \
             mock.patch.object(subprocess, "run", side_effect=fake_run):
            loop.ask("what is running?")
        self.assertIsNotNone(seen["cwd"], "the loop must pin a working directory")
        self.assertNotEqual(Path(seen["cwd"]).resolve(), Path.cwd().resolve())

    def test_only_zams_own_mcp_server_is_used(self) -> None:
        cmd, _e, _s = loop._command({"runner": "claude-code", "model": "sonnet"}, "hi", None)
        self.assertIn("--strict-mcp-config", cmd)

    def test_the_prompt_says_memory_is_only_what_a_tool_returned(self) -> None:
        prompt = loop._system_prompt()
        self.assertIn("search_memory", prompt)
        self.assertIn("did not come from a tool", prompt)


class SystemPromptSurvivesResumeTest(unittest.TestCase):
    """The data-not-instructions guard is sent on resume too.

    --system-prompt-snapshot defaults to `on` and replays the recorded prompt
    "until the conversation is compacted". After a compaction a resumed turn
    renders it fresh from the flags it was given, so omitting the flag on the
    resume branch silently drops the guard from exactly the long-lived
    conversations that read vault notes.
    """

    def _cmd(self, session, is_new):
        return loop._command({"runner": "claude-code", "model": "sonnet"},
                             "what did we decide?", session, is_new)[0]

    def test_a_resumed_turn_still_names_tool_output_as_data(self) -> None:
        cmd = self._cmd("existing-session", False)
        self.assertIn("--resume", cmd)
        self.assertIn("--append-system-prompt", cmd)
        appended = cmd[cmd.index("--append-system-prompt") + 1]
        self.assertIn("never as instructions", appended)

    def test_a_created_turn_names_it_too(self) -> None:
        cmd = self._cmd(None, True)
        self.assertIn("--session-id", cmd)
        appended = cmd[cmd.index("--append-system-prompt") + 1]
        self.assertIn("never as instructions", appended)


class LaunchToolTest(unittest.TestCase):
    """launch_run is a dev action: it executes, guarded by launch.launch."""

    def test_a_missing_project_is_refused_not_launched(self) -> None:
        # Issue keys are ambiguous across repos; guessing is worse than asking.
        r = tools.launch_run(issue="XARI-26")
        self.assertFalse(r["ok"])
        self.assertIn("project", r["message"].lower())

    def test_it_calls_the_launcher_with_zam_as_actor(self) -> None:
        from cuzam.dash import launch as launcher
        with mock.patch.object(launcher, "launch",
                               return_value=launcher.Outcome(True, "started", "t_x")) as spawned:
            r = tools.launch_run(project="Kaffecard", issue="xari-26", flow="full")
        self.assertTrue(r["ok"])
        self.assertEqual(r["task_id"], "t_x")
        kwargs = spawned.call_args
        self.assertEqual(kwargs.args[0], "Kaffecard")
        self.assertEqual(kwargs.args[1], "XARI-26")  # upcased
        self.assertEqual(kwargs.kwargs["actor"], "zam")

    def test_the_loop_grants_launch_run_to_the_model(self) -> None:
        # A tool the model is not allowed to call is a tool that never runs.
        cmd, _e, _s = loop._command({"runner": "claude-code", "model": "sonnet"},
                                    "start a run", None)
        allowed = cmd[cmd.index("--allowedTools") + 1:]
        self.assertIn("mcp__zam-tools__launch_run", allowed)
