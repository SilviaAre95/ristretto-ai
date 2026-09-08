"""A flow must not spend its budget discovering the model is unreachable.

tier1's build stage once spent a full hour producing 935 bytes of warnings:
Claude Code rejects a model its catalog does not describe, and behind a
custom base_url it then fails to terminate rather than erroring. Nothing said
so until the timeout fired (XARI-119).

subprocess is stubbed throughout: the behaviour under test is what the runner
does with each outcome, and a real probe would cost tokens and 90 seconds.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ristretto import runner  # noqa: E402

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
            problem = runner.preflight_provider(LOCAL, Path("/tmp"))

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
            problem = runner.preflight_provider(LOCAL, Path("/tmp"))

        self.assertIn("refused", problem)
        self.assertIn("model not found", problem)

    def test_a_working_provider_is_silent(self) -> None:
        with mock.patch.object(
            runner.subprocess, "run", return_value=completed(0, stdout="READY")
        ):
            self.assertEqual(runner.preflight_provider(CLAUDE, Path("/tmp")), "")

    def test_the_probe_carries_the_providers_routing(self) -> None:
        with mock.patch.object(
            runner.subprocess, "run", return_value=completed(0, stdout="READY")
        ) as run:
            runner.preflight_provider(LOCAL, Path("/tmp"))

        command = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertIn("--model", command)
        self.assertIn("qwen3.6:27b-coding-nvfp4", command)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://localhost:11434")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "ollama")
        # A probe that waits as long as a stage would defeat the point.
        self.assertLessEqual(run.call_args.kwargs["timeout"], 120)

    def test_a_missing_binary_is_reported_not_raised(self) -> None:
        with mock.patch.object(
            runner.subprocess, "run", side_effect=OSError("no such file")
        ):
            problem = runner.preflight_provider(CLAUDE, Path("/tmp"))

        self.assertIn("could not be started", problem)

    def test_non_claude_runners_are_not_probed(self) -> None:
        """Probing costs a model call; codex has never shown this failure."""
        with mock.patch.object(runner.subprocess, "run") as run:
            problem = runner.preflight_provider(
                {"name": "codex", "runner": "codex", "model": "gpt-5"}, Path("/tmp")
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
            self.assertEqual(runner.preflight_flow(flow, Path("/tmp")), "")

        self.assertEqual(probe.call_count, 2)

    def test_the_first_problem_stops_the_flow(self) -> None:
        flow = self.flow(CLAUDE, LOCAL)
        with mock.patch.object(
            runner, "preflight_provider",
            side_effect=["", "local-coder (qwen) did not answer"],
        ):
            problem = runner.preflight_flow(flow, Path("/tmp"))

        self.assertIn("did not answer", problem)

    def test_a_flow_with_no_providers_is_fine(self) -> None:
        self.assertEqual(runner.preflight_flow({"stages": []}, Path("/tmp")), "")

    def test_a_provider_with_a_fallback_does_not_block_the_flow(self) -> None:
        """Refusing here would be a worse failure than the one being prevented.

        run_stage already switches to the fallback when a provider turns out
        to be unavailable, so a transient rate limit at preflight must not
        turn into a dead run.
        """
        with_fallback = {**CLAUDE, "fallback": "local-coder"}
        with mock.patch.object(
            runner, "preflight_provider", return_value="claude refused: rate limit"
        ):
            problem = runner.preflight_flow(
                self.flow(with_fallback), Path("/tmp")
            )

        self.assertEqual(problem, "")

    def test_a_provider_with_no_fallback_does_block_the_flow(self) -> None:
        """local-coder has nowhere to go, so its failure is the whole run."""
        with mock.patch.object(
            runner, "preflight_provider", return_value="local-coder did not answer"
        ):
            problem = runner.preflight_flow(self.flow(LOCAL), Path("/tmp"))

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


if __name__ == "__main__":
    unittest.main()
