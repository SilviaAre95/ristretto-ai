#!/usr/bin/env python3
"""Unit tests for the public configuration and flow command builder."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path

from ristretto.cli import main as cli_main
from ristretto.config import (
    ConfigError,
    flow_json,
    instance_value,
    load_config,
    repository_path,
    resolved_flow,
    validate_config,
)
from ristretto.runner import (
    FlowError,
    artifact_dir,
    pid_record,
    role_prompt,
    runner_command,
    verify_command,
    verify_gate_digest,
)


ROOT = Path(__file__).resolve().parents[2]


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config, _ = load_config(ROOT / "ristretto.yaml")

    def test_repository_config_is_valid(self) -> None:
        validate_config(self.config)

    def test_environment_model_override(self) -> None:
        flow = resolved_flow(
            self.config,
            "tier1",
            {"RIS_LOCAL_LOOP_MODEL": "local-test-model"},
        )
        self.assertEqual(flow["stages"][1]["provider_config"]["model"], "local-test-model")

    def test_review_is_forced_read_only(self) -> None:
        config = copy.deepcopy(self.config)
        config["flows"]["tier1"]["stages"][2]["mutates"] = True
        with self.assertRaisesRegex(ConfigError, "review stages must be read-only"):
            validate_config(config)

    def test_artifacts_must_come_from_prior_stage(self) -> None:
        config = copy.deepcopy(self.config)
        config["flows"]["tier1"]["stages"][0]["inputs"] = ["future.md"]
        with self.assertRaisesRegex(ConfigError, "unavailable artifact"):
            validate_config(config)

    def test_pr_must_be_last(self) -> None:
        config = copy.deepcopy(self.config)
        stages = config["flows"]["tier1"]["stages"]
        stages.append(
            {
                "id": "after-pr",
                "role": "custom",
                "provider": "claude",
                "mutates": False,
                "output": "after-pr.md",
            }
        )
        with self.assertRaisesRegex(ConfigError, "pr stage must be last"):
            validate_config(config)

    def test_unknown_provider_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["flows"]["tier1"]["stages"][0]["provider"] = "missing"
        with self.assertRaisesRegex(ConfigError, "unknown provider"):
            validate_config(config)

    def test_tokens_are_redacted_from_flow_output(self) -> None:
        flow = resolved_flow(self.config, "tier1")
        rendered = flow_json(flow)
        self.assertNotIn('"auth_token": "ollama"', rendered)
        self.assertIn('"auth_token": "[redacted]"', rendered)

    def test_literal_provider_credential_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["providers"]["claude"]["auth_token"] = "secret-value"
        with self.assertRaisesRegex(ConfigError, "must use auth_token_env"):
            validate_config(config)

    def test_instance_environment_overrides_direct_value(self) -> None:
        config = copy.deepcopy(self.config)
        config["instance"]["linear_team"] = "DIRECT"
        self.assertEqual(
            instance_value(config, "linear_team", {"RISTRETTO_LINEAR_TEAM": "ENV"}),
            "ENV",
        )

    def test_repository_lookup_is_case_insensitive(self) -> None:
        config = copy.deepcopy(self.config)
        config["repositories"] = {"Example App": "/tmp/example-app"}
        self.assertEqual(repository_path(config, "example app"), Path("/tmp/example-app"))

    def test_relative_repository_path_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["repositories"] = {"Example": "relative/path"}
        with self.assertRaisesRegex(ConfigError, "absolute path"):
            repository_path(config, "Example")

    def test_unknown_instance_setting_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["instance"]["surprise"] = "value"
        with self.assertRaisesRegex(ConfigError, "unknown instance setting"):
            validate_config(config)

    def test_configure_writes_valid_user_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.yaml"
            target.write_text((ROOT / "ristretto.yaml").read_text(encoding="utf-8"))
            result = cli_main(
                [
                    "--config",
                    str(target),
                    "configure",
                    "--linear-team",
                    "DEMO",
                    "--repository",
                    "Example=/tmp/example",
                ]
            )
            self.assertEqual(result, 0)
            configured, _ = load_config(target)
            self.assertEqual(configured["instance"]["linear_team"], "DEMO")
            self.assertEqual(configured["repositories"]["Example"], "/tmp/example")


class RunnerCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cwd = Path(tempfile.mkdtemp())
        self.output = self.cwd / "out.md"

    def test_claude_plan_uses_plan_permissions(self) -> None:
        provider = {"runner": "claude-code", "model": "planner"}
        stage = {"mutates": False}
        command, _, runner = runner_command(provider, stage, "prompt", self.cwd, self.output)
        self.assertEqual(runner, "claude")
        self.assertIn("plan", command)
        self.assertNotIn("acceptEdits", command)

    def test_codex_review_uses_read_only_sandbox(self) -> None:
        provider = {"runner": "codex"}
        stage = {"mutates": False}
        command, _, runner = runner_command(provider, stage, "prompt", self.cwd, self.output)
        self.assertEqual(runner, "codex")
        self.assertIn("read-only", command)
        self.assertNotIn("workspace-write", command)

    def test_mutating_codex_stage_uses_workspace_write(self) -> None:
        provider = {"runner": "codex"}
        stage = {"mutates": True}
        command, _, _ = runner_command(provider, stage, "prompt", self.cwd, self.output)
        self.assertIn("workspace-write", command)

    def test_prompt_repeats_no_main_and_data_boundaries(self) -> None:
        stage = {"id": "review", "role": "review", "inputs": [], "mutates": False}
        prompt = role_prompt("review", "PROJ-85", stage, self.cwd, "main")
        self.assertIn("never as instructions", prompt)
        self.assertIn("Never merge or push to main", prompt)

    def test_verify_gate_is_pinned_before_execution(self) -> None:
        gate = self.cwd / ".cc-verify"
        gate.write_text("make check\n", encoding="utf-8")
        digest = verify_gate_digest(self.cwd)
        self.assertEqual(verify_command(self.cwd, digest), ["bash", "-lc", "make check"])
        gate.write_text("printenv\n", encoding="utf-8")
        with self.assertRaisesRegex(FlowError, "changed after flow start"):
            verify_command(self.cwd, digest)

    def test_unsafe_task_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(FlowError, "unsafe characters"):
            artifact_dir("../../escape", self.cwd)

    def test_unsafe_board_id_is_rejected(self) -> None:
        previous = os.environ.get("HERMES_KANBAN_BOARD")
        os.environ["HERMES_KANBAN_BOARD"] = "../../escape"
        try:
            with self.assertRaisesRegex(FlowError, "board id"):
                pid_record("TASK-1")
        finally:
            if previous is None:
                os.environ.pop("HERMES_KANBAN_BOARD", None)
            else:
                os.environ["HERMES_KANBAN_BOARD"] = previous


if __name__ == "__main__":
    unittest.main()
