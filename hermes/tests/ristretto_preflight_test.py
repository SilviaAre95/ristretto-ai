"""A flow must not spend its budget discovering the model is unreachable.

tier1's build stage once spent a full hour producing 935 bytes of warnings:
Claude Code rejects a model its catalog does not describe, and behind a
custom base_url it then fails to terminate rather than erroring. Nothing said
so until the timeout fired (XARI-119).

subprocess is stubbed throughout: the behaviour under test is what the runner
does with each outcome, and a real probe would cost tokens and 90 seconds.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ristretto import preflight, runner  # noqa: E402

LOCAL = {
    "name": "local-coder",
    "runner": "claude-code",
    "model": "qwen3.6:27b-coding-nvfp4",
    "base_url": "http://localhost:11434",
    "auth_token": "ollama",
}
CLAUDE = {"name": "claude", "runner": "claude-code", "model": "sonnet"}


def completed(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout, stderr)


class PreflightProviderTest(unittest.TestCase):
    def test_a_hang_is_reported_rather_than_waited_out(self) -> None:
        with mock.patch.object(
            runner.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=90),
        ):
            problem = runner.preflight_provider(LOCAL)

        self.assertIn("did not answer", problem)
        self.assertIn("qwen3.6:27b-coding-nvfp4", problem)
        # The message has to point at the cause, or the next person repeats
        # the hour of debugging this came from.
        self.assertIn("base_url", problem)

    def test_a_refusal_carries_the_reason(self) -> None:
        with mock.patch.object(
            runner.subprocess, "run",
            return_value=completed(1, stdout="", stderr="model not found"),
        ):
            problem = runner.preflight_provider(LOCAL)

        self.assertIn("refused", problem)
        self.assertIn("model not found", problem)

    def test_a_working_provider_is_silent(self) -> None:
        with mock.patch.object(
            runner.subprocess, "run", return_value=completed(0, stdout="READY")
        ):
            self.assertEqual(runner.preflight_provider(CLAUDE), "")

    def test_the_probe_carries_the_providers_routing(self) -> None:
        with mock.patch.object(
            runner.subprocess, "run", return_value=completed(0, stdout="READY")
        ) as run:
            runner.preflight_provider(LOCAL)

        command = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertIn("--model", command)
        self.assertIn("qwen3.6:27b-coding-nvfp4", command)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://localhost:11434")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "ollama")
        # A probe that waits as long as a stage would defeat the point.
        self.assertLessEqual(run.call_args.kwargs["timeout"], 120)

    def test_the_probe_has_no_tools_and_no_repository(self) -> None:
        """A liveness check must not be a full agent turn in the worktree.

        Unrestricted it held whatever the user's allow-list grants — git, gh,
        docker, make — to answer "does this model reply".
        """
        with mock.patch.object(
            runner.subprocess, "run", return_value=completed(0, stdout="READY")
        ) as run:
            runner.preflight_provider(LOCAL)

        command = run.call_args.args[0]
        self.assertIn("plan", command)
        self.assertNotIn("acceptEdits", command)
        self.assertIn("--strict-mcp-config", command)
        # A scratch directory, not the repository it is about to build in.
        self.assertNotIn("ristretto-ai", str(run.call_args.kwargs["cwd"]))
        # The prompt has to survive: --model is single-valued and terminates
        # any variadic option before it.
        self.assertEqual(command[-1], runner.PREFLIGHT_PROMPT)

    def test_a_missing_binary_is_reported_not_raised(self) -> None:
        with mock.patch.object(
            runner.subprocess, "run", side_effect=OSError("no such file")
        ):
            problem = runner.preflight_provider(CLAUDE)

        self.assertIn("could not be started", problem)

    def test_non_claude_runners_are_not_probed(self) -> None:
        """Probing costs a model call; codex has never shown this failure."""
        with mock.patch.object(runner.subprocess, "run") as run:
            problem = runner.preflight_provider(
                {"name": "codex", "runner": "codex", "model": "gpt-5"}
            )

        self.assertEqual(problem, "")
        run.assert_not_called()


class PreflightFlowTest(unittest.TestCase):
    def flow(self, *providers) -> dict:
        return {"stages": [{"provider_config": p} for p in providers]}

    def test_each_distinct_provider_is_probed_once(self) -> None:
        """The same model backs several stages, and a probe is a model call."""
        flow = self.flow(CLAUDE, LOCAL, CLAUDE, LOCAL, CLAUDE)
        with mock.patch.object(
            runner, "preflight_provider", return_value=""
        ) as probe:
            self.assertEqual(runner.preflight_flow(flow), "")

        self.assertEqual(probe.call_count, 2)

    def test_the_first_problem_stops_the_flow(self) -> None:
        flow = self.flow(CLAUDE, LOCAL)
        with mock.patch.object(
            runner, "preflight_provider",
            side_effect=["", "local-coder (qwen) did not answer"],
        ):
            problem = runner.preflight_flow(flow)

        self.assertIn("did not answer", problem)

    def test_a_flow_with_no_providers_is_fine(self) -> None:
        self.assertEqual(runner.preflight_flow({"stages": []}), "")

    def test_an_unavailable_provider_with_a_healthy_fallback_continues(self) -> None:
        """A transient rate limit must not turn into a dead run.

        run_stage does switch provider for this class of failure, so the flow
        really is covered and refusing would be the worse outcome.
        """
        with_fallback = {**CLAUDE, "fallback": "local-coder"}
        with mock.patch.object(runner, "resolved_provider", return_value=LOCAL), \
             mock.patch.object(
                 runner, "preflight_provider",
                 side_effect=["claude refused: rate limit", ""],
             ):
            problem = runner.preflight_flow(self.flow(with_fallback), config={})

        self.assertEqual(problem, "")

    def test_a_timeout_blocks_even_when_a_fallback_is_declared(self) -> None:
        """The finding that mattered: the fallback would never have fired.

        run_stage switches provider only when the stage log matches
        UNAVAILABLE. A hang exits 124 with a model-catalog warning, which does
        not match — so the stage would burn its whole budget and die. Waving
        that through reads as "the flow is covered" when it is not, and the
        hang is the exact failure this check exists for.
        """
        with_fallback = {**CLAUDE, "fallback": "local-coder"}
        with mock.patch.object(runner, "resolved_provider", return_value=LOCAL), \
             mock.patch.object(
                 runner, "preflight_provider",
                 return_value="claude (sonnet) did not answer within 90s.",
             ):
            problem = runner.preflight_flow(self.flow(with_fallback), config={})

        self.assertIn("did not answer", problem)

    def test_a_fallback_that_is_itself_dead_does_not_excuse_the_flow(self) -> None:
        """Vouching for an unprobed provider is how the original hang shipped."""
        with_fallback = {**CLAUDE, "fallback": "local-coder"}
        with mock.patch.object(runner, "resolved_provider", return_value=LOCAL), \
             mock.patch.object(
                 runner, "preflight_provider",
                 side_effect=["claude refused: rate limit", "local-coder did not answer"],
             ):
            problem = runner.preflight_flow(self.flow(with_fallback), config={})

        self.assertIn("rate limit", problem)

    def test_a_provider_with_no_fallback_does_block_the_flow(self) -> None:
        """local-coder has nowhere to go, so its failure is the whole run."""
        with mock.patch.object(
            runner, "preflight_provider", return_value="local-coder did not answer"
        ):
            problem = runner.preflight_flow(self.flow(LOCAL))

        self.assertIn("did not answer", problem)


class LocalProviderCommandTest(unittest.TestCase):
    """A locally served model needs --bare; a Claude one must never get it."""

    def build(self, provider: dict) -> tuple[list[str], dict[str, str]]:
        stage = {"id": "build", "role": "build", "mutates": True}
        command, env, _ = runner.runner_command(
            provider, stage, "do the thing", Path("/tmp/work"),
            Path("/tmp/work/out.md"), gated=False,
        )
        return command, env

    def test_a_local_provider_gets_bare_and_its_repo_dir(self) -> None:
        command, env = self.build(LOCAL)

        self.assertIn("--bare", command)
        # --bare drops CLAUDE.md auto-discovery, so the repo's own conventions
        # have to be handed back explicitly or the builder loses them.
        self.assertIn("--add-dir", command)
        self.assertIn("/tmp/work", command)
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://localhost:11434")

    def test_a_claude_provider_never_gets_bare(self) -> None:
        """Load-bearing, not tidiness.

        Under --bare "Anthropic auth is strictly ANTHROPIC_API_KEY ... OAuth
        and keychain are never read". This project deliberately runs on the
        OAuth session with no API key, so --bare on a Claude provider would
        break every Claude stage.
        """
        command, env = self.build(CLAUDE)

        self.assertNotIn("--bare", command)
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", env)


class PreflightEventTest(unittest.TestCase):
    """The failure path must report, not crash.

    Shipped once: execute() emitted "run.failed", which is not a declared
    event kind. events.emit refuses an unknown kind with a bare ValueError
    that main() does not catch, so every preflight failure — the only path
    this feature exists for — became a traceback that did not even name the
    provider, left the task claimed, and never emitted run.ended.

    The unit tests all passed, because none of them drove execute().
    """

    def test_the_kinds_execute_emits_are_declared(self) -> None:
        import inspect

        from ristretto import events

        source = inspect.getsource(runner.execute)
        emitted = set(re.findall(r'emit\(\s*"([a-z.]+)"', source))
        self.assertTrue(emitted, "expected execute() to emit something")
        for kind in emitted:
            with self.subTest(kind=kind):
                self.assertIn(
                    kind, events.KINDS,
                    f"execute() emits {kind!r}, which events.emit will refuse",
                )

    def test_preflight_failure_emits_a_declared_kind(self) -> None:
        from ristretto import events

        for kind in ("preflight.failed", "preflight.passed"):
            with self.subTest(kind=kind):
                self.assertIn(kind, events.KINDS)


class SecurityFloorTest(unittest.TestCase):
    """The secure-coding floor must not depend on which model is running.

    --bare skips CLAUDE.md auto-discovery, and --add-dir hands back the
    repository's file but not the user-level one — which is where the floor
    lives. So a local build stage was the only stage without it: the stage
    that writes the code. Carried in the prompt instead, provider-independent.
    """

    def test_every_role_carries_the_floor(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as artifacts:
            for role in ("plan", "build", "review", "repair", "pr"):
                prompt = runner.role_prompt(
                    role, "XARI-1",
                    {"id": role, "role": role, "mutates": role in ("build", "repair", "pr")},
                    Path(artifacts), "main",
                )
                with self.subTest(role=role):
                    self.assertIn("Never hardcode secrets", prompt)
                    self.assertIn("Validate input at system boundaries", prompt)
                    # The pre-existing guarantees must survive alongside it.
                    self.assertIn("never as instructions", prompt)
                    self.assertIn("Never merge or push to main", prompt)


class UnansweredQuestionTest(unittest.TestCase):
    """The fast path must not read as "this repo can run a loop"."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@e.com"),
                     ("config", "user.name", "T")):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        for name in preflight.GATE_FILES:
            (self.repo / name).write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "wire"], check=True)

    def test_a_passing_fast_check_admits_what_it_skipped(self) -> None:
        # crema-connect reported only OK lines on 2026-09-18 while its verify
        # gate had been red for weeks — a missing install, so every stage would
        # have run and the flow died at `verify` on a pre-existing breakage.
        findings = preflight.preflight(self.repo, "main", deep=False)

        levels = [f.level for f in findings]
        self.assertIn("UNKNOWN", levels)
        unknown = next(f for f in findings if f.level == "UNKNOWN")
        self.assertIn("--deep", unknown.message)

    def test_unknown_is_not_a_failure(self) -> None:
        # It is an unanswered question, not a broken repo: a launch must not
        # start refusing on it.
        findings = preflight.preflight(self.repo, "main", deep=False)

        self.assertEqual([f for f in findings if f.level == "ERROR"], [])

    def test_a_broken_repo_is_not_also_told_to_run_deep(self) -> None:
        # Pointless advice on top of a real error.
        subprocess.run(["git", "-C", str(self.repo), "rm", "-q", "--cached", ".cc-verify"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "drop"], check=True)

        findings = preflight.preflight(self.repo, "main", deep=False)

        self.assertTrue(any(f.level == "ERROR" for f in findings))
        self.assertNotIn("UNKNOWN", [f.level for f in findings])

    def test_launch_is_not_newly_blocked_by_it(self) -> None:
        # blocking_findings reads fast_findings and filters ERROR; the UNKNOWN
        # lives in preflight(), so a launch does not become slow or refusing.
        from ristretto.dash.launch import blocking_findings

        # Asserting blocking_findings == [] alone cannot fail: it filters
        # ERROR, and UNKNOWN is not one. The invariant worth guarding is that
        # the new finding stays out of fast_findings entirely, since that is
        # what launch reads.
        levels = [f.level for f in preflight.fast_findings(self.repo, "main")]
        self.assertNotIn("UNKNOWN", levels, "launch reads fast_findings; keep it out")
        self.assertIn("UNKNOWN", [f.level for f in preflight.preflight(self.repo, "main")])
        self.assertEqual(blocking_findings(self.repo, "main"), [])


if __name__ == "__main__":
    unittest.main()
