#!/usr/bin/env python3
"""Unit tests for the public configuration and flow command builder."""

from __future__ import annotations

import contextlib
import copy
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ristretto import events, gc, preflight
from ristretto.cli import main as cli_main
from ristretto.config import (
    ConfigError,
    doctor,
    flow_json,
    instance_value,
    load_config,
    repository_path,
    resolved_flow,
    resolved_provider,
    served_models,
    validate_config,
)
from ristretto.runner import (
    FlowError,
    artifact_dir,
    pid_record,
    pr_stage_failure,
    role_prompt,
    runner_command,
    stage_output_failure,
    uncommitted_paths,
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


class ContextLengthTests(unittest.TestCase):
    """Local model names are unknown to the runner, which then assumes 200k."""

    def setUp(self) -> None:
        config, _ = load_config(ROOT / "ristretto.yaml")
        self.config = copy.deepcopy(config)

    def _command_env(self, provider_name: str) -> dict[str, str]:
        provider = resolved_provider(self.config, provider_name)
        stage = {"id": "build", "role": "build", "mutates": True}
        _, env, _ = runner_command(provider, stage, "prompt", Path("/tmp"), Path("/tmp/out.md"))
        return env

    def test_declared_window_is_exported(self) -> None:
        env = self._command_env("local-coder")
        self.assertEqual(env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS"), "262144")

    def test_cloud_provider_gets_no_override(self) -> None:
        # Claude knows its own models; forcing a window would only cause harm.
        env = self._command_env("claude")
        self.assertNotIn("CLAUDE_CODE_MAX_CONTEXT_TOKENS", env)

    def test_context_length_must_be_a_positive_integer(self) -> None:
        for bad in ("262144", 0, -1, True, 1.5):
            config = copy.deepcopy(self.config)
            config["providers"]["local-coder"]["context_length"] = bad
            with self.assertRaisesRegex(ConfigError, "context_length", msg=f"accepted {bad!r}"):
                validate_config(config)


class DoctorLocalModelTests(unittest.TestCase):
    """A configured model name is not evidence the host still serves it.

    The runner binaries are stubbed throughout: whether `claude` and `codex`
    happen to be installed is a property of the machine running the suite,
    and CI has neither. Without this the provider check short-circuits at
    "command not found" and never reaches the model lookup under test.
    """

    def setUp(self) -> None:
        patcher = mock.patch("shutil.which", return_value="/usr/bin/stub")
        self.which = patcher.start()
        self.addCleanup(patcher.stop)
        config, _ = load_config(ROOT / "ristretto.yaml")
        self.config = copy.deepcopy(config)
        self.local_models = {
            resolved_provider(self.config, name)["model"]
            for name, provider in self.config["providers"].items()
            if provider.get("base_url")
        }
        self.assertTrue(self.local_models, "fixture needs at least one local provider")

    def test_missing_local_model_is_an_error(self) -> None:
        findings = doctor(self.config, {}, catalog=lambda url: {"some-other-model"})
        errors = [f for f in findings if f.startswith("ERROR") and "not served" in f]
        self.assertTrue(errors, f"expected a not-served error, got: {findings}")

    def test_served_local_model_is_ok(self) -> None:
        findings = doctor(self.config, {}, catalog=lambda url: self.local_models)
        self.assertFalse([f for f in findings if f.startswith("ERROR")], findings)
        self.assertTrue([f for f in findings if "serving" in f], findings)

    def test_unreachable_endpoint_warns_rather_than_errors(self) -> None:
        # The server being down is not a configuration error.
        findings = doctor(self.config, {}, catalog=lambda url: None)
        self.assertFalse([f for f in findings if f.startswith("ERROR")], findings)
        self.assertTrue([f for f in findings if f.startswith("WARN") and "cannot reach" in f])

    def test_endpoint_is_queried_once_per_base_url(self) -> None:
        calls: list[str] = []

        def catalog(url: str) -> set[str]:
            calls.append(url)
            return set()

        doctor(self.config, {}, catalog=catalog)
        self.assertTrue(calls, "expected at least one endpoint lookup")
        self.assertEqual(len(calls), len(set(calls)), f"duplicate lookups: {calls}")


class StageOutcomeTests(unittest.TestCase):
    """A zero exit code is not proof that a stage did its job.

    Every case here was observed in a real tier3 run that reported success.
    """

    BUILD = {"id": "build", "role": "build"}
    REVIEW = {"id": "review", "role": "review"}

    def test_model_failure_marker_fails_the_stage(self) -> None:
        text = "<model_failure>File already exists.</model_failure>"
        reason = stage_output_failure(self.BUILD, text)
        self.assertIsNotNone(reason)
        self.assertIn("File already exists.", reason or "")

    def test_empty_output_fails_the_stage(self) -> None:
        self.assertIsNotNone(stage_output_failure(self.BUILD, "   \n\t  "))

    def test_bare_protocol_tag_fails_the_stage(self) -> None:
        # A stage that emits only "<severity>10</severity>" has not reported.
        self.assertIsNotNone(stage_output_failure(self.BUILD, "<severity>10</severity>"))

    def test_real_output_passes(self) -> None:
        text = "Implemented the localized info label and added a regression test for it."
        self.assertIsNone(stage_output_failure(self.BUILD, text))

    def test_review_must_state_a_verdict(self) -> None:
        wordy = "I looked at the diff and it seems reasonable overall, nothing much to add."
        self.assertIsNotNone(stage_output_failure(self.REVIEW, wordy))
        self.assertIsNone(stage_output_failure(self.REVIEW, f"BLOCKING. {wordy}"))
        self.assertIsNone(stage_output_failure(self.REVIEW, f"CLEAN. {wordy}"))

    def test_terse_clean_review_is_not_rejected_for_length(self) -> None:
        # Shorter than the minimum for other roles, but a complete verdict.
        terse = "CLEAN. No findings."
        self.assertLess(len(terse), 40)
        self.assertIsNone(stage_output_failure(self.REVIEW, terse))


class PrStageTests(unittest.TestCase):
    def _repo(self, stack: contextlib.ExitStack) -> Path:
        cwd = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        run = lambda *a: subprocess.run(a, cwd=cwd, check=True, capture_output=True)
        run("git", "init", "-q", "-b", "main")
        run("git", "config", "user.email", "test@example.invalid")
        run("git", "config", "user.name", "Test")
        (cwd / "seed.txt").write_text("seed\n", encoding="utf-8")
        run("git", "add", "seed.txt")
        run("git", "commit", "-q", "-m", "seed")
        return cwd

    def test_no_commit_is_a_failure(self) -> None:
        with contextlib.ExitStack() as stack:
            cwd = self._repo(stack)
            reason = pr_stage_failure(cwd, "main")
            self.assertIsNotNone(reason)
            self.assertIn("committed nothing", reason or "")

    def test_uncommitted_work_is_a_failure(self) -> None:
        with contextlib.ExitStack() as stack:
            cwd = self._repo(stack)
            subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=cwd, check=True)
            (cwd / "done.txt").write_text("done\n", encoding="utf-8")
            subprocess.run(["git", "add", "done.txt"], cwd=cwd, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "work"], cwd=cwd, check=True)
            # The observed run left a new test file untracked and never committed it.
            (cwd / "extra.test.ts").write_text("stray\n", encoding="utf-8")
            reason = pr_stage_failure(cwd, "main")
            self.assertIsNotNone(reason)
            self.assertIn("uncommitted", reason or "")

    def test_committed_and_clean_passes(self) -> None:
        with contextlib.ExitStack() as stack:
            cwd = self._repo(stack)
            subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=cwd, check=True)
            (cwd / "done.txt").write_text("done\n", encoding="utf-8")
            subprocess.run(["git", "add", "done.txt"], cwd=cwd, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "work"], cwd=cwd, check=True)
            self.assertIsNone(pr_stage_failure(cwd, "main"))

    def test_run_artifacts_do_not_count_as_uncommitted(self) -> None:
        with contextlib.ExitStack() as stack:
            cwd = self._repo(stack)
            (cwd / ".ristretto" / "runs").mkdir(parents=True)
            (cwd / ".ristretto" / "runs" / "plan.md").write_text("plan\n", encoding="utf-8")
            self.assertEqual(uncommitted_paths(cwd), [])


class EventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.db = Path(scratch.name) / "events.db"

    def test_emit_and_read_roundtrip(self) -> None:
        events.emit(
            "t_1",
            "stage.failed",
            issue_key="XARI-33",
            project="kaffecard",
            stage="plan",
            payload={"reason": "model reported failure"},
            path=self.db,
        )
        records = events.read("t_1", path=self.db)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "stage.failed")
        self.assertEqual(records[0]["stage"], "plan")
        self.assertEqual(records[0]["payload"], {"reason": "model reported failure"})

    def test_unknown_kind_is_a_caller_bug_and_raises(self) -> None:
        with self.assertRaises(events.UnknownEventKind):
            events.emit("t_1", "stage.exploded", path=self.db)

    def test_storage_failure_never_raises(self) -> None:
        # Telemetry must not be able to fail the build it is describing.
        unwritable = Path("/proc/definitely/not/writable/events.db")
        with contextlib.redirect_stderr(io.StringIO()) as noise:
            self.assertFalse(events.emit("t_1", "run.started", path=unwritable))
        self.assertIn("could not record", noise.getvalue())

    def test_reads_are_newest_first_and_limited(self) -> None:
        for index in range(5):
            events.emit("t_1", "stage.passed", stage=f"s{index}", path=self.db, now=1000 + index)
        records = events.read("t_1", limit=2, path=self.db)
        self.assertEqual([r["stage"] for r in records], ["s4", "s3"])

    def test_events_are_scoped_by_task(self) -> None:
        events.emit("t_1", "run.started", path=self.db)
        events.emit("t_2", "run.started", path=self.db)
        self.assertEqual(len(events.read("t_1", path=self.db)), 1)
        self.assertEqual(len(events.read(path=self.db)), 2)

    def test_unserializable_payload_is_dropped_not_fatal(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(events.emit("t_1", "run.started", payload={"x": object()}, path=self.db))
        self.assertIsNone(events.read("t_1", path=self.db)[0]["payload"])


class PreflightTests(unittest.TestCase):
    """A repo is loop-capable only if a fresh worktree can run its gate."""

    def _repo(self) -> Path:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        origin = Path(scratch.name) / "origin.git"
        work = Path(scratch.name) / "work"
        run = lambda *a, **k: subprocess.run(list(a), check=True, capture_output=True, **k)
        run("git", "init", "-q", "--bare", "-b", "main", str(origin))
        run("git", "clone", "-q", str(origin), str(work))
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "T")):
            run("git", "config", key, value, cwd=work)
        (work / "seed.txt").write_text("seed\n", encoding="utf-8")
        run("git", "add", "-A", cwd=work)
        run("git", "commit", "-q", "-m", "seed", cwd=work)
        run("git", "push", "-q", "origin", "main", cwd=work)
        return work

    def test_gate_files_missing_entirely(self) -> None:
        findings = preflight.fast_findings(self._repo())
        self.assertEqual(len([f for f in findings if f.level == "ERROR"]), 2)
        self.assertTrue(all("missing" in f.message for f in findings))

    def test_gate_file_on_disk_but_uncommitted_is_an_error(self) -> None:
        # Exactly the pilates-flow case: present locally, absent from the ref
        # a fresh worktree starts from.
        repo = self._repo()
        for name in preflight.GATE_FILES:
            (repo / name).write_text("local only\n", encoding="utf-8")
        findings = preflight.fast_findings(repo)
        self.assertEqual(len([f for f in findings if f.level == "ERROR"]), 2)
        self.assertTrue(all("not committed" in f.message for f in findings))

    def test_committed_gate_files_pass(self) -> None:
        repo = self._repo()
        for name in preflight.GATE_FILES:
            (repo / name).write_text("committed\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "wire"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True, capture_output=True)
        findings = preflight.fast_findings(repo)
        self.assertFalse([f for f in findings if f.level == "ERROR"], findings)

    def test_origin_wins_over_a_stale_local_branch(self) -> None:
        # A local main sitting behind the remote must not be what we inspect.
        repo = self._repo()
        for name in preflight.GATE_FILES:
            (repo / name).write_text("committed\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "wire"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=repo, check=True, capture_output=True)
        self.assertEqual(preflight.resolve_ref(repo, "main"), "origin/main")
        self.assertFalse([f for f in preflight.fast_findings(repo) if f.level == "ERROR"])

    def test_non_git_directory_is_reported(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        findings = preflight.fast_findings(Path(scratch.name))
        self.assertEqual(len(findings), 1)
        self.assertIn("not a git repository", findings[0].message)


class GarbageCollectionTests(unittest.TestCase):
    """Removing a worktree must never lose work that only exists there."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.repo = Path(scratch.name) / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(list(a), cwd=self.repo, check=True, capture_output=True)
        run("git", "init", "-q", "-b", "main")
        run("git", "config", "user.email", "t@example.invalid")
        run("git", "config", "user.name", "T")
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "seed")

    def _worktree(self, name: str) -> Path:
        path = self.repo / ".worktrees" / name
        subprocess.run(
            ["git", "worktree", "add", "--detach", "--quiet", str(path), "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        self.addCleanup(
            lambda: subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=self.repo,
                check=False,
                capture_output=True,
            )
        )
        return path

    def _only(self, tasks: dict) -> gc.Candidate:
        candidates = [c for c in gc.plan(self.repo, tasks) if c.path.name.startswith("t_")]
        self.assertEqual(len(candidates), 1, candidates)
        return candidates[0]

    def test_finished_task_with_clean_tree_is_removable(self) -> None:
        self._worktree("t_a1b2c3d4")
        decision = self._only({"t_a1b2c3d4": {"id": "t_a1b2c3d4", "status": "done"}})
        self.assertEqual(decision.action, "remove")

    def test_uncommitted_work_is_never_removed(self) -> None:
        path = self._worktree("t_a1b2c3d4")
        (path / "unsaved.txt").write_text("work\n", encoding="utf-8")
        decision = self._only({"t_a1b2c3d4": {"id": "t_a1b2c3d4", "status": "done"}})
        self.assertEqual(decision.action, "keep")
        self.assertIn("unsaved.txt", decision.reason)

    def test_run_artifacts_do_not_block_removal(self) -> None:
        path = self._worktree("t_a1b2c3d4")
        (path / ".ristretto" / "runs").mkdir(parents=True)
        (path / ".ristretto" / "runs" / "plan.md").write_text("plan\n", encoding="utf-8")
        decision = self._only({"t_a1b2c3d4": {"id": "t_a1b2c3d4", "status": "done"}})
        self.assertEqual(decision.action, "remove")

    def test_running_task_is_left_alone(self) -> None:
        self._worktree("t_a1b2c3d4")
        for status in ("running", "blocked", "ready"):
            decision = self._only({"t_a1b2c3d4": {"id": "t_a1b2c3d4", "status": status}})
            self.assertEqual(decision.action, "keep", status)

    def test_unknown_task_is_left_for_a_human(self) -> None:
        self._worktree("t_a1b2c3d4")
        decision = self._only({})
        self.assertEqual(decision.action, "keep")
        self.assertIn("no matching task", decision.reason)

    def test_directories_not_named_after_a_task_are_untouched(self) -> None:
        # A developer's own worktree must never be a candidate, whatever the
        # board contains.
        self._worktree("my-own-experiment")
        candidates = gc.plan(self.repo, {"my-own-experiment": {"status": "done"}})
        mine = [c for c in candidates if c.path.name == "my-own-experiment"]
        self.assertEqual(mine[0].action, "keep")
        self.assertIn("not a task worktree", mine[0].reason)

    def test_reclaim_removes_only_approved_candidates(self) -> None:
        keep = self._worktree("t_deadbee1")
        drop = self._worktree("t_deadbee2")
        (keep / "unsaved.txt").write_text("work\n", encoding="utf-8")
        tasks = {
            "t_deadbee1": {"id": "t_deadbee1", "status": "done"},
            "t_deadbee2": {"id": "t_deadbee2", "status": "done"},
        }
        gc.reclaim(self.repo, gc.plan(self.repo, tasks))
        self.assertTrue(keep.exists(), "a dirty worktree was removed")
        self.assertFalse(drop.exists(), "a clean finished worktree was left behind")

    def test_merged_branches_excludes_base_and_current(self) -> None:
        run = lambda *a: subprocess.run(list(a), cwd=self.repo, check=True, capture_output=True)
        run("git", "branch", "merged-work")
        names = gc.merged_branches(self.repo, "main")
        self.assertIn("merged-work", names)
        self.assertNotIn("main", names)

    def test_unmerged_branch_is_not_offered(self) -> None:
        run = lambda *a: subprocess.run(list(a), cwd=self.repo, check=True, capture_output=True)
        run("git", "checkout", "-q", "-b", "unmerged")
        (self.repo / "new.txt").write_text("new\n", encoding="utf-8")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "unmerged work")
        run("git", "checkout", "-q", "main")
        self.assertNotIn("unmerged", gc.merged_branches(self.repo, "main"))


if __name__ == "__main__":
    unittest.main()
