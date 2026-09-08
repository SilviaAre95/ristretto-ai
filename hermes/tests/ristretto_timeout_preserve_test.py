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

    # --- defects found in review of PR #53 -------------------------------

    def test_counts_files_in_a_new_directory_not_status_lines(self) -> None:
        """`git status --porcelain` collapses an untracked directory.

        Without -uall, a stage that adds a module reports "1 file" while
        committing many — and this number is the whole point of the change.
        """
        package = self.repo / "src" / "feature"
        package.mkdir(parents=True)
        for index in range(6):
            (package / f"f{index}.py").write_text(f"# {index}\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("6 file(s)", kept)

    def test_counts_a_rename_as_one_file(self) -> None:
        """A rename is one file that moved, and the count should say so.

        Counting status lines would also give 1 here, but for the wrong reason
        — it treats "R old -> new" as one line. Counting the commit's own
        file list is right by construction, and git's rename detection makes
        it report the moved file once rather than as a delete plus an add.
        """
        (self.repo / "DOC.md").write_text("base\n", encoding="utf-8")
        (self.repo / "README.md").unlink()

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("1 file(s)", kept)
        committed = git(
            "show", "--pretty=format:", "--name-only", "HEAD", cwd=self.repo
        ).stdout
        self.assertIn("DOC.md", committed)

    def test_refuses_on_detached_head_rather_than_committing_off_branch(self) -> None:
        """A commit on a detached HEAD is as lost as no commit at all.

        Reporting it as preserved would be a false claim of safety — worse
        than admitting the work is still loose.
        """
        head = git("rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        git("checkout", "-q", "--detach", head, cwd=self.repo)
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("NOT kept", kept)
        self.assertIn("detached", kept)
        self.assertEqual(self.commit_count(), 1)
        # The work is still there to be recovered by hand.
        self.assertTrue((self.repo / "feature.py").exists())

    def test_refuses_mid_merge_rather_than_committing_conflict_markers(self) -> None:
        git("checkout", "-q", "-b", "other", cwd=self.repo)
        (self.repo / "README.md").write_text("theirs\n", encoding="utf-8")
        git("commit", "-q", "-am", "theirs", cwd=self.repo)
        git("checkout", "-q", "main", cwd=self.repo)
        (self.repo / "README.md").write_text("ours\n", encoding="utf-8")
        git("commit", "-q", "-am", "ours", cwd=self.repo)
        merged = git("merge", "other", cwd=self.repo)
        self.assertNotEqual(merged.returncode, 0, "expected a conflict")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("NOT kept", kept)
        self.assertIn("MERGE_HEAD", kept)

    def test_a_failed_commit_never_reports_that_nothing_was_written(self) -> None:
        """The exact misleading message this whole change exists to remove.

        Work demonstrably exists — `changed` was non-empty — so returning ""
        would make the caller print "with nothing written" while the work sits
        uncommitted. A stale index.lock is a plausible leftover, since the
        runner SIGKILLs a stage that may have been mid-git at the deadline.
        """
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")
        lock = Path(
            git("rev-parse", "--absolute-git-dir", cwd=self.repo).stdout.strip()
        ) / "index.lock"
        lock.write_text("", encoding="utf-8")
        self.addCleanup(lambda: lock.unlink(missing_ok=True))

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertNotEqual(kept, "")
        self.assertIn("NOT kept", kept)
        self.assertIn("1 changed path(s)", kept)

    # --- findings from the security review of PR #53 ----------------------

    def test_refuses_to_commit_to_the_base_branch(self) -> None:
        """The "it's only the run's own branch" defence, actually enforced.

        Hermes normally supplies a worktree on a feature branch, but
        run-loop.sh can be re-run by hand from the primary checkout — which is
        the recovery step the flow guard prints. Committing unreviewed model
        output onto main would poison every worktree cut from it afterwards.
        """
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600, base="main")

        self.assertIn("NOT kept", kept)
        self.assertIn("base branch", kept)
        self.assertEqual(self.commit_count(), 1)

    def test_commits_on_a_feature_branch_with_the_same_base_set(self) -> None:
        git("checkout", "-q", "-b", "xariprojects/xari-1", cwd=self.repo)
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600, base="main")

        self.assertIn("1 file(s) kept", kept)
        self.assertEqual(self.commit_count(), 2)

    def test_never_commits_a_gitignored_secret(self) -> None:
        """The missing test for the change's entire risk surface.

        `git add -A` decides what becomes permanent. .gitignore is what stands
        between a stage's stray .env and the branch, so assert it rather than
        assuming it.
        """
        (self.repo / ".gitignore").write_text(".env\n*.pem\n", encoding="utf-8")
        git("add", ".gitignore", cwd=self.repo)
        git("commit", "-q", "-m", "ignore secrets", cwd=self.repo)

        (self.repo / ".env").write_text("API_KEY=super-secret\n", encoding="utf-8")
        (self.repo / "server.pem").write_text("-----BEGIN KEY-----\n", encoding="utf-8")
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("1 file(s)", kept)
        committed = git(
            "show", "--pretty=format:", "--name-only", "HEAD", cwd=self.repo
        ).stdout
        self.assertIn("feature.py", committed)
        self.assertNotIn(".env", committed)
        self.assertNotIn("server.pem", committed)

    def test_runs_commit_hooks_and_only_bypasses_when_they_refuse(self) -> None:
        """A pre-commit hook is often a repo's only secret scan.

        Bypassing it unconditionally would remove the one check that sees the
        staged diff; letting it veto would lose the work. So: try, then bypass
        and say so.
        """
        hooks = self.repo / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        marker = self.repo / "hook-ran"
        hook = hooks / "pre-commit"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertTrue(marker.exists(), "a passing hook should have run")
        self.assertNotIn("bypassed", kept)

    def test_says_so_when_it_had_to_bypass_the_hooks(self) -> None:
        hooks = self.repo / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        kept = runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("kept", kept)
        self.assertIn("bypassed", kept)

    def test_the_commit_carries_a_machine_readable_trailer(self) -> None:
        """A squash-merge rewrites the subject; the trailer is what survives."""
        (self.repo / "feature.py").write_text("print('work')\n", encoding="utf-8")

        runner.preserve_work(self.repo, "build", 3600)

        body = git("log", "-1", "--pretty=%B", cwd=self.repo).stdout
        self.assertIn("Ristretto-Preserved: build", body)


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

    def test_a_stage_cannot_extend_its_budget_by_rewriting_the_config(self) -> None:
        """.cc-dev.yaml is pinned at flow start, like .cc-verify's digest.

        Both are control-plane values in files a mutating stage can rewrite.
        Read per stage from disk, a build stage could raise its own and every
        later stage's deadline — and preserve_work would commit that edit so
        it survived into the retry and the PR.

        run_stage takes the pinned value and must not consult the file, so a
        mid-run rewrite has no effect on the budget actually used.
        """
        import inspect

        source = inspect.getsource(runner.run_stage)
        self.assertIn("pinned_stage_timeout", source)
        self.assertNotIn(
            "repo_stage_timeout(cwd)",
            source,
            "run_stage must use the pinned value, not re-read .cc-dev.yaml",
        )

        # And the pin is taken once, at flow start, alongside the verify digest.
        started = inspect.getsource(runner.execute)
        self.assertIn("pinned_stage_timeout = repo_stage_timeout(cwd)", started)

    def test_absurd_values_are_bounded_rather_than_obeyed(self) -> None:
        self.write_dev_config("stage_timeout: 999999\n")
        self.assertEqual(runner.repo_stage_timeout(self.repo), runner.MAX_STAGE_TIMEOUT)
        self.write_dev_config("stage_timeout: 1\n")
        self.assertEqual(runner.repo_stage_timeout(self.repo), runner.MIN_STAGE_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
