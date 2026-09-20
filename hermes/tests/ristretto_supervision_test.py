"""A dispatched run must survive being watched, and losing its supervisor.

Three failures from one tier1 run on 2026-09-10, none of them the model's:

* the supervising worker agent read a silent stage as a hang and killed the
  run three times in four attempts, twice against an instruction that says in
  as many words not to;
* the kill left 148 lines of finished work uncommitted, because the recovery
  written for XARI-118 only fires on our own deadline;
* the worktree had been cut from whatever the repo checkout had selected, so
  the branch carried an unrelated commit.

The git-backed tests run against real repositories rather than mocks: what is
under test is a sequence of git invocations, and a mocked git would only prove
the arguments look plausible.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ristretto import runner  # noqa: E402
from ristretto.dash import launch  # noqa: E402


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


class ProgressTickTest(unittest.TestCase):
    """A stage prints one line and then nothing. That is what got it killed."""

    def tick(self, stage: str, elapsed: float, blocked: float) -> str:
        pulse = runner.Heartbeat("t_abc", interval=300, tick=1)
        pulse.stage = stage
        pulse.stage_started = time.monotonic() - elapsed
        with mock.patch.object(runner.approvals, "blocked_seconds", return_value=blocked):
            from io import StringIO

            buf = StringIO()
            with mock.patch.object(sys, "stderr", buf):
                pulse.report()
            return buf.getvalue().strip()

    def test_a_working_stage_says_so(self) -> None:
        line = self.tick("build", elapsed=252, blocked=0)

        self.assertIn("build", line)
        self.assertIn("4m12s", line)
        self.assertNotIn("waiting on you", line)

    def test_a_stage_blocked_on_a_person_says_which(self) -> None:
        # The whole point: silence because a model is thinking and silence
        # because nobody has answered the prompt look identical otherwise.
        line = self.tick("build", elapsed=450, blocked=198)

        self.assertIn("7m30s", line)
        self.assertIn("3m18s of it waiting on you", line)

    def test_the_tick_is_far_shorter_than_the_board_heartbeat(self) -> None:
        # The board tolerates an hour of quiet; the watching agent tolerated
        # about two minutes.
        self.assertLess(runner.PROGRESS_TICK_SECONDS, runner.HEARTBEAT_SECONDS / 4)

    def test_entering_a_stage_restarts_its_clock(self) -> None:
        pulse = runner.Heartbeat("t_abc")
        pulse.stage_started = time.monotonic() - 9999
        with mock.patch.object(runner, "heartbeat"):
            pulse.enter("review")

        self.assertEqual(pulse.stage, "review")
        self.assertLess(time.monotonic() - pulse.stage_started, 5)

    def test_durations_read_the_way_a_person_writes_them(self) -> None:
        self.assertEqual(runner._duration(9), "9s")
        self.assertEqual(runner._duration(252), "4m12s")
        self.assertEqual(runner._duration(3800), "1h03m")


class TerminationPreservesWorkTest(unittest.TestCase):
    """XARI-118 kept a timed-out stage's work. A kill skipped that entirely."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.email", "test@example.com", cwd=self.repo)
        git("config", "user.name", "Test", cwd=self.repo)
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "base", cwd=self.repo)
        git("checkout", "-q", "-b", "feature", cwd=self.repo)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.disarm)

    def disarm(self) -> None:
        runner.ACTIVE_STAGE, runner.ACTIVE_CWD, runner.ACTIVE_BASE = "", None, ""
        runner.ACTIVE_PROCESS, runner.ACTIVE_RECORD = None, None

    def arm(self) -> None:
        runner.ACTIVE_STAGE, runner.ACTIVE_CWD, runner.ACTIVE_BASE = "build", self.repo, "main"

    def head_subject(self) -> str:
        return git("log", "-1", "--pretty=%s", cwd=self.repo).stdout.strip()

    def test_a_terminated_stage_keeps_what_it_wrote(self) -> None:
        (self.repo / "feature.py").write_text("print('148 lines')\n", encoding="utf-8")
        self.arm()

        with self.assertRaises(SystemExit):
            runner.cleanup_process()

        self.assertEqual(git("status", "--porcelain", cwd=self.repo).stdout.strip(), "")
        self.assertIn("wip(build)", self.head_subject())

    def test_the_commit_says_it_was_killed_not_timed_out(self) -> None:
        # Recovering by hand meant calling preserve_work with timeout=0, which
        # produced "stage timed out after 0s" — false, and the kind of thing
        # someone later has to disbelieve.
        (self.repo / "feature.py").write_text("work\n", encoding="utf-8")
        self.arm()

        with self.assertRaises(SystemExit):
            runner.cleanup_process()

        self.assertIn("terminated", self.head_subject())
        self.assertNotIn("timed out", self.head_subject())

    def test_an_unarmed_signal_commits_nothing(self) -> None:
        # Read-only stages never arm, and a signal arriving between stages must
        # not commit whatever happens to be lying around.
        (self.repo / "stray.py").write_text("not mine\n", encoding="utf-8")

        with self.assertRaises(SystemExit):
            runner.cleanup_process()

        self.assertIn("stray.py", git("status", "--porcelain", cwd=self.repo).stdout)

    def test_preserve_work_still_reports_a_timeout_when_it_is_one(self) -> None:
        (self.repo / "feature.py").write_text("work\n", encoding="utf-8")

        runner.preserve_work(self.repo, "build", 3600)

        self.assertIn("timed out after 3600s", self.head_subject())


class PinBranchToBaseTest(unittest.TestCase):
    """A run that starts from the wrong commit produces a plausible-looking PR."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = root / "origin"
        self.repo = root / "clone"
        self.origin.mkdir()
        git("init", "-q", "-b", "main", cwd=self.origin)
        git("config", "user.email", "t@e.com", cwd=self.origin)
        git("config", "user.name", "T", cwd=self.origin)
        (self.origin / "README.md").write_text("upstream\n", encoding="utf-8")
        git("add", "-A", cwd=self.origin)
        git("commit", "-q", "-m", "upstream base", cwd=self.origin)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.repo)], check=True)
        git("config", "user.email", "t@e.com", cwd=self.repo)
        git("config", "user.name", "T", cwd=self.repo)
        self.addCleanup(self.tmp.cleanup)

    def sha(self, ref: str, cwd: Path | None = None) -> str:
        return git("rev-parse", ref, cwd=cwd or self.repo).stdout.strip()

    def test_the_branch_is_cut_from_origin_not_from_a_stray_checkout(self) -> None:
        # The exact 2026-09-10 shape: the repo is parked on unrelated work.
        git("checkout", "-q", "-b", "chore/permission-floor", cwd=self.repo)
        (self.repo / "settings.json").write_text("{}\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "unrelated", cwd=self.repo)
        stray = self.sha("HEAD")

        problem = launch.pin_branch_to_base(str(self.repo), "xariprojects/xari-129", "main")

        self.assertEqual(problem, "")
        self.assertEqual(self.sha("xariprojects/xari-129"), self.sha("origin/main"))
        self.assertNotEqual(self.sha("xariprojects/xari-129"), stray)

    def test_it_fetches_so_the_pin_is_not_to_a_stale_origin(self) -> None:
        # Pinning to an origin/main nobody has fetched picks a different wrong
        # commit rather than the right one.
        (self.origin / "new.md").write_text("moved on\n", encoding="utf-8")
        git("add", "-A", cwd=self.origin)
        git("commit", "-q", "-m", "upstream moved", cwd=self.origin)
        moved = self.sha("HEAD", cwd=self.origin)

        launch.pin_branch_to_base(str(self.repo), "xariprojects/xari-1", "main")

        self.assertEqual(self.sha("xariprojects/xari-1"), moved)

    def test_an_existing_branch_is_left_alone(self) -> None:
        # Relaunching an issue must not discard commits a previous attempt
        # preserved — which is the only copy of a killed stage's work.
        git("branch", "xariprojects/xari-129", cwd=self.repo)
        git("checkout", "-q", "xariprojects/xari-129", cwd=self.repo)
        (self.repo / "recovered.py").write_text("kept\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "wip(build): stage was terminated", cwd=self.repo)
        kept = self.sha("xariprojects/xari-129")

        problem = launch.pin_branch_to_base(str(self.repo), "xariprojects/xari-129", "main")

        self.assertEqual(problem, "")
        self.assertEqual(self.sha("xariprojects/xari-129"), kept)

    def test_a_missing_base_is_reported_not_guessed(self) -> None:
        problem = launch.pin_branch_to_base(str(self.repo), "xariprojects/xari-2", "nope")

        self.assertTrue(problem)
        self.assertEqual(
            git("rev-parse", "--verify", "--quiet", "xariprojects/xari-2", cwd=self.repo).returncode,
            1,
        )


if __name__ == "__main__":
    unittest.main()


class FileEditingInstructionTest(unittest.TestCase):
    """Sixteen approvals to append one route, and 289 lines destroyed."""

    def prompt(self, role: str) -> str:
        import tempfile
        stage = {"id": role, "role": role, "mutates": role in {"build", "repair", "pr"}, "inputs": []}
        return runner.role_prompt(role, "XARI-9", stage, Path(tempfile.mkdtemp()), "main")

    def test_every_mutating_stage_is_told_which_tools_to_edit_with(self) -> None:
        for role in ("build", "repair", "pr"):
            with self.subTest(role=role):
                text = self.prompt(role)
                self.assertIn("Write and Edit tools", text)
                self.assertIn("not with shell", text)

    def test_it_says_what_to_use_rather_than_only_what_to_avoid(self) -> None:
        # Told only "do not use cat", a model escalates — the observed run went
        # cat -> sed/head -> a Node script, one gated command at a time.
        text = self.prompt("build")

        self.assertLess(text.index("Write and Edit"), text.index("`cat >`"),
                        "the tool to use should come before the ones to avoid")
        self.assertIn("node", text, "node was the escalation; name it")

    def test_it_gives_the_reason_the_shell_route_corrupts_files(self) -> None:
        text = self.prompt("build")

        self.assertIn("line position rather than by content", text)


class SignalPreservesWorkTest(unittest.TestCase):
    """The Stop button was the one path that dropped work."""

    def test_the_signal_exits_are_the_shell_convention(self) -> None:
        self.assertEqual(runner.SIGNAL_EXITS[143], "SIGTERM")
        self.assertEqual(runner.SIGNAL_EXITS[137], "SIGKILL")
        self.assertEqual(runner.SIGNAL_EXITS[130], "SIGINT")

    def test_a_killed_stage_reports_stopped_not_failed(self) -> None:
        # "exit 143" alone reads as the model breaking; it means someone
        # pressed Stop.
        self.assertNotIn(124, runner.SIGNAL_EXITS, "124 is our own deadline, not a signal")
