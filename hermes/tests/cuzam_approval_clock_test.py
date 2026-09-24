"""The stage clock must not run while a stage is waiting on a person (XARI-128).

Run 67 spent 3437 of its 3600 seconds blocked at permission prompts, got 163
seconds of work, and died reporting "timed out after 3600s with nothing
written". The perverse property under test throughout: asking permission
carefully must not be what makes a stage fail.

The interval arithmetic is tested against the shape of run 67's own rows
rather than an invented one, because the two things that make it non-obvious —
overlapping requests, and a request the kill left undecided — are both
properties of what Claude Code really did, not of a shape someone imagined.
The task id below is synthetic; only the relative timings are real.
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

from cuzam import approvals, runner  # noqa: E402


# Run 67 (2026-09-09), as seconds from its first prompt: (requested, decided
# or None, expires). Timings measured from the approvals store; the last row
# really was still undecided, because the kill landed before await_decision
# could park it.
RUN_67 = [
    (0, 758, 1800),        # Bash,  allowed after 12m38s
    (794, 1071, 2594),     # Bash,  allowed after 4m37s
    (1076, 1409, 2876),    # Read,  allowed after 5m33s
    (1079, 1408, 2879),    # Bash,  overlaps the Read almost entirely
    (1456, 1734, 3256),    # Bash,  allowed after 4m38s
    (1748, 1765, 3548),    # Bash,  allowed after 17s
    (1766, None, 3566),    # Bash,  the stage was killed before this was parked
]
# The stage's 3600s deadline fell 3540s after the first prompt: it had been
# working for about a minute before it first asked for anything.
RUN_67_KILLED_AT = 3540
RUN_67_SUM = 758 + 277 + 333 + 329 + 278 + 17 + 1774    # 3766 — more than the hour
RUN_67_UNION = 758 + 277 + 333 + 278 + 17 + 1774        # 3437
RUN_67_WORKING = 3600 - RUN_67_UNION                    # 163 seconds of an hour


class BlockedSecondsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "approvals.db"

    def rows(self, spans, task_id: str = "t_run67", base: int = 0) -> None:
        with approvals.connect(self.path) as connection:
            for index, (requested, decided, expires) in enumerate(spans):
                connection.execute(
                    "INSERT INTO approvals (id, task_id, tool_name, requested_at, "
                    "expires_at, decision, decided_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        f"r{index}",
                        task_id,
                        "Bash",
                        base + requested,
                        base + expires,
                        None if decided is None else approvals.ALLOW,
                        None if decided is None else base + decided,
                    ),
                )

    def blocked(self, since: float = 0, until: float | None = RUN_67_KILLED_AT) -> float:
        return approvals.blocked_seconds(
            "t_run67", since, until=until, path=self.path
        )

    def test_run_67_lost_almost_its_entire_hour(self) -> None:
        self.rows(RUN_67)

        self.assertAlmostEqual(self.blocked(), RUN_67_UNION)
        # What the model actually got: 163 seconds of a 3600-second budget.
        self.assertAlmostEqual(3600 - self.blocked(), RUN_67_WORKING)

    def test_overlapping_requests_are_merged_not_summed(self) -> None:
        # Claude Code asks for several tool calls in one turn, so two prompts
        # are outstanding at once. Summing them credits a stage more waiting
        # than the wall clock contains, which is a budget nobody can reason
        # about — run 67's rows add up to 3766s inside a 3600s hour.
        self.rows(RUN_67)

        self.assertLess(self.blocked(), RUN_67_SUM)
        self.assertLess(self.blocked(), 3600)

    def test_a_request_the_kill_left_undecided_stops_at_its_expiry(self) -> None:
        # await_decision stamps decided_at when it parks a request as denied.
        # A row still open means the stage was killed first — run 67's last
        # one is still NULL in the live store today. Counted to "now" it would
        # buy the stage unlimited budget forever after.
        self.rows([(0, None, 1800)])

        self.assertAlmostEqual(self.blocked(until=1800), 1800)
        self.assertAlmostEqual(self.blocked(until=99999), 1800)

    def test_a_request_still_open_counts_up_to_now(self) -> None:
        self.rows([(0, None, 1800)])

        self.assertAlmostEqual(self.blocked(until=600), 600)

    def test_waiting_before_the_stage_started_is_not_credited(self) -> None:
        # A previous attempt's prompt is not this attempt's lost time, and
        # that holds for the part of it that overlaps: `since` is taken just
        # before the process is spawned, so a request older than `since`
        # belongs to a process that is already gone.
        self.rows([(0, 600, 1800)])

        self.assertAlmostEqual(self.blocked(since=300), 0)
        self.assertAlmostEqual(self.blocked(since=900), 0)

    def test_an_orphaned_request_does_not_freeze_the_next_attempt_s_clock(self) -> None:
        # A stage killed at its deadline leaves its last request undecided
        # with up to half an hour still on it, and nothing reaps those rows.
        # The fallback attempt starts seconds later: if the orphan counted, its
        # credit would grow one second per second while the new attempt worked
        # uninterrupted, and the deadline would never arrive.
        self.rows([(0, None, 1800)])
        relaunched = 10

        self.assertAlmostEqual(self.blocked(since=relaunched, until=20), 0)
        self.assertAlmostEqual(self.blocked(since=relaunched, until=600), 0)

    def test_an_old_request_answered_late_is_not_credited_either(self) -> None:
        # The same leak wearing a different hat: clamping the start to `since`
        # would have credited this attempt the 50s between its launch and an
        # answer to a question the previous attempt asked.
        self.rows([(0, 60, 1800)])

        self.assertAlmostEqual(self.blocked(since=10, until=600), 0)

    def test_another_task_is_not_credited(self) -> None:
        self.rows([(0, 600, 1800)], task_id="t_someone_else")

        self.assertAlmostEqual(self.blocked(), 0)

    def test_no_approvals_is_no_credit(self) -> None:
        self.assertAlmostEqual(self.blocked(), 0)

    def test_an_unreadable_store_is_worth_no_credit(self) -> None:
        # This decides how long a stage may keep running, so a store that
        # cannot be read has to fail towards the shorter budget.
        blocked = approvals.blocked_seconds("t_run67", 0, path=self.dir)

        self.assertEqual(blocked, 0.0)


class ApprovalCreditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "approvals.db"
        patcher = mock.patch.object(approvals, "store_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_credit_is_capped(self) -> None:
        # Otherwise an agent asking questions nobody answers holds the worktree
        # and the Hermes claim indefinitely, each expiry buying another half
        # hour. Six unanswered requests, back to back.
        now = int(time.time())
        began = now - 6 * 1800
        with approvals.connect(self.path) as connection:
            for index in range(6):
                start = began + index * 1800
                connection.execute(
                    "INSERT INTO approvals (id, task_id, tool_name, requested_at, "
                    "expires_at, decision, decided_at) VALUES (?,?,?,?,?,?,?)",
                    (f"r{index}", "t_abc", "Bash", start, start + 1800,
                     approvals.DENY, start + 1800),
                )

        credit = runner.approval_credit("t_abc", began)

        self.assertEqual(credit(), float(runner.MAX_APPROVAL_CREDIT))

    def test_no_task_id_means_no_credit_callable(self) -> None:
        self.assertIsNone(runner.approval_credit("", time.time()))


class RunProcessDeadlineTest(unittest.TestCase):
    """The deadline itself, against real processes rather than a mocked clock."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())

    def run_sleeping(self, seconds: float, timeout: int, credit=None):
        return runner.run_process(
            [sys.executable, "-c", f"import time; time.sleep({seconds})"],
            {"PATH": "/usr/bin:/bin"},
            self.dir,
            self.dir / "stage.log",
            self.dir / "stage.txt",
            self.dir / "pid.json",
            "python",
            timeout,
            False,
            credit,
        )

    def test_a_stage_that_overruns_with_no_credit_is_killed(self) -> None:
        code, _, forgiven = self.run_sleeping(30, timeout=1)

        self.assertEqual(code, 124)
        self.assertEqual(forgiven, 0.0)

    def test_time_spent_waiting_is_given_back(self) -> None:
        # The acceptance criterion, in miniature: a stage that would have been
        # killed at its deadline survives because the seconds it spent at a
        # prompt are not its own.
        code, _, forgiven = self.run_sleeping(3, timeout=1, credit=lambda: 30.0)

        self.assertEqual(code, 0)
        self.assertEqual(forgiven, 30.0)

    def test_credit_does_not_make_a_stage_immortal(self) -> None:
        # Waiting that has already ended buys a bounded extension and no more.
        started = time.monotonic()

        with mock.patch.object(runner, "CREDIT_POLL_SECONDS", 0.5):
            code, _, forgiven = self.run_sleeping(60, timeout=1, credit=lambda: 2.0)

        self.assertEqual(code, 124)
        self.assertEqual(forgiven, 2.0)
        self.assertLess(time.monotonic() - started, 20)

    def test_output_survives_a_deadline_that_was_extended(self) -> None:
        # communicate() is resumed rather than restarted after a timeout, so
        # everything written before the first deadline has to still be there.
        code, text, _ = runner.run_process(
            [
                sys.executable,
                "-c",
                "import sys, time; print('before'); sys.stdout.flush(); "
                "time.sleep(2); print('after')",
            ],
            {"PATH": "/usr/bin:/bin"},
            self.dir,
            self.dir / "stage.log",
            self.dir / "stage.txt",
            self.dir / "pid.json",
            "python",
            1,
            True,
            lambda: 30.0,
        )

        self.assertEqual(code, 0)
        self.assertIn("before", text)
        self.assertIn("after", text)
        self.assertIn("before", (self.dir / "stage.txt").read_text(encoding="utf-8"))
        self.assertIn("after", (self.dir / "stage.txt").read_text(encoding="utf-8"))

    def test_the_pid_record_is_cleared_on_an_extended_run(self) -> None:
        record = self.dir / "pid.json"

        runner.run_process(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            {"PATH": "/usr/bin:/bin"},
            self.dir,
            self.dir / "stage.log",
            self.dir / "stage.txt",
            record,
            "python",
            1,
            False,
            lambda: 30.0,
        )

        self.assertFalse(record.exists())
        self.assertIsNone(runner.ACTIVE_PROCESS)


class TimeoutReasonTest(unittest.TestCase):
    """"timed out after 3600s" was true of run 67 and diagnosed nothing."""

    def test_no_waiting_reads_as_before(self) -> None:
        self.assertEqual(
            runner.timeout_reason(3600, 0.0, ""),
            "timed out after 3600s with nothing written",
        )

    def test_waiting_is_named_and_not_charged(self) -> None:
        reason = runner.timeout_reason(3600, 2400.0, "9 file(s) kept as a WIP commit")

        self.assertIn("3600s of working time", reason)
        self.assertIn("40m waiting on approvals was not charged", reason)
        self.assertIn("9 file(s) kept", reason)

    def test_hitting_the_ceiling_does_not_accuse_you_of_not_answering(self) -> None:
        # The ceiling is reached as readily by many prompts answered promptly
        # as by four nobody replied to. Telling someone who answered every
        # time to answer faster is the same class of misdiagnosis this
        # function exists to end.
        reason = runner.timeout_reason(3600, float(runner.MAX_APPROVAL_CREDIT), "")

        self.assertNotIn("unanswered", reason)
        self.assertIn("waiting on approvals", reason)

    def test_dying_at_a_prompt_is_a_different_failure_from_running_out(self) -> None:
        out_of_work = runner.timeout_reason(3600, 0.0, "")
        out_of_patience = runner.timeout_reason(
            3600, float(runner.MAX_APPROVAL_CREDIT), ""
        )

        self.assertIn("waiting on approvals", out_of_patience)
        self.assertNotIn("waiting on approvals", out_of_work)
        self.assertNotEqual(out_of_work, out_of_patience)


if __name__ == "__main__":
    unittest.main()
