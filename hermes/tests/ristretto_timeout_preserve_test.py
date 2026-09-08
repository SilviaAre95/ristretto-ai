"""A stage killed at its deadline must not take its work with it (XARI-118).

These run against real git repositories rather than mocks: the thing under
test is a sequence of git invocations against a worktree, and a mocked git
would prove only that the arguments look plausible.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ristretto import runner  # noqa: E402


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


class PreserveWorkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.email", "test@example.com", cwd=self.repo)
        git("config", "user.name", "Test", cwd=self.repo)
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "base", cwd=self.repo)
        self.addCleanup(self.tmp.cleanup)

    def head_subject(self) -> str:
        return git("log", "-1", "--pretty=%s", cwd=self.repo).stdout.strip()

    def commit_count(self) -> int:
        return int(git("rev-list", "--count", "HEAD", cwd=self.repo).stdout.strip())

    def test_commits_modified_and_new_files(self) -> None:
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("2 file(s)", kept)
        self.assertEqual(self.commit_count(), 2)
        self.assertIn("wip(build)", self.head_subject())
        # Nothing left behind: the point is that the worktree can now be
        # reclaimed without losing anything.
        self.assertEqual(
            git("status", "--porcelain", cwd=self.repo).stdout.strip(), ""
        )

    def test_never_commits_ristretto_run_artifacts(self) -> None:
        """Run logs are not the flow's work product.

        .ristretto/ is untracked in the repos this runs against, so a bare
        `git add -A` would sweep the run's own logs into the branch.
        """
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")
        artifacts = self.repo / runner.ARTIFACT_DIR_NAME / "runs" / "t_1"
        artifacts.mkdir(parents=True)
        (artifacts / "build.log").write_text("noise\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("1 file(s)", kept)
        tracked = git("ls-files", cwd=self.repo).stdout
        self.assertIn("feature.py", tracked)
        self.assertNotIn(runner.ARTIFACT_DIR_NAME, tracked)

    def test_reports_nothing_when_there_is_nothing_to_keep(self) -> None:
        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertEqual(kept, "")
        self.assertEqual(self.commit_count(), 1)

    def test_ignores_run_artifacts_when_deciding_there_is_nothing(self) -> None:
        artifacts = self.repo / runner.ARTIFACT_DIR_NAME
        artifacts.mkdir()
        (artifacts / "loop.log").write_text("noise\n", encoding="utf-8")

        self.assertEqual(runner.preserve_work(self.repo, "build", 3600), "")
        self.assertEqual(self.commit_count(), 1)

    def test_survives_a_failing_pre_commit_hook(self) -> None:
        """A repo's hook must not be able to veto preservation."""
        hooks = self.repo / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("1 file(s)", kept)
        self.assertEqual(self.commit_count(), 2)

    def test_a_non_repository_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(runner.preserve_work(Path(plain), "build", 3600), "")


class RepoStageTimeoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write_dev_config(self, body: str) -> None:
        (self.repo / runner.DEV_CONFIG).write_text(body, encoding="utf-8")

    def test_absent_config_falls_through_to_the_default(self) -> None:
        self.assertIsNone(runner.repo_stage_timeout(self.repo))

    def test_reads_the_repositorys_declared_budget(self) -> None:
        self.write_dev_config("base: main\nstage_timeout: 7200\n")
        self.assertEqual(runner.repo_stage_timeout(self.repo), 7200)

    def test_config_without_the_key_falls_through(self) -> None:
        self.write_dev_config("base: main\nmax_retries: 3\n")
        self.assertIsNone(runner.repo_stage_timeout(self.repo))

    def test_malformed_config_does_not_kill_the_run(self) -> None:
        self.write_dev_config("base: [unclosed\n")
        self.assertIsNone(runner.repo_stage_timeout(self.repo))

    def test_non_numeric_value_falls_through(self) -> None:
        self.write_dev_config("stage_timeout: soon\n")
        self.assertIsNone(runner.repo_stage_timeout(self.repo))

    def test_absurd_values_are_bounded_rather_than_obeyed(self) -> None:
        self.write_dev_config("stage_timeout: 999999\n")
        self.assertEqual(runner.repo_stage_timeout(self.repo), runner.MAX_STAGE_TIMEOUT)
        self.write_dev_config("stage_timeout: 1\n")
        self.assertEqual(runner.repo_stage_timeout(self.repo), runner.MIN_STAGE_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
