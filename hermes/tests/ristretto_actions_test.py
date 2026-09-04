#!/usr/bin/env python3
"""Gated actions: proposed, then executed only on a human's winning allow."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ristretto import actions, approvals, events


class MergeGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "approvals.db"
        patcher = mock.patch.object(events, "store_path", return_value=self.dir / "events.db")
        patcher.start(); self.addCleanup(patcher.stop)

    def propose(self, pr=17):
        return actions.record_merge("XARI-28", "o/kaffecard", pr, "b", path=self.path)

    def test_a_proposal_does_not_merge(self) -> None:
        with mock.patch.object(subprocess, "run") as run:
            self.propose()
        run.assert_not_called()
        self.assertEqual(len(approvals.pending(path=self.path)), 1)

    def test_approve_executes_the_merge(self) -> None:
        r = self.propose(17)
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "Merged", "")
            won, msg = actions.answer(r["id"], approvals.ALLOW, actor="dashboard", path=self.path)
        argv = run.call_args.args[0]
        self.assertTrue(won)
        self.assertEqual(argv[:4], ["gh", "pr", "merge", "17"])
        self.assertIn("merged PR #17", msg)

    def test_deny_never_merges(self) -> None:
        r = self.propose()
        with mock.patch.object(subprocess, "run") as run:
            actions.answer(r["id"], approvals.DENY, actor="slack", reason="not yet", path=self.path)
        run.assert_not_called()

    def test_the_merged_pr_is_the_one_named_not_the_callers_idea(self) -> None:
        # The approval fixes the PR; execution reads the record, not any later input.
        r = self.propose(42)
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            actions.answer(r["id"], approvals.ALLOW, actor="dashboard", path=self.path)
        self.assertIn("42", run.call_args.args[0])

    def test_a_failed_merge_is_recorded_not_hidden(self) -> None:
        r = self.propose()
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 1, "", "not mergeable")
            won, msg = actions.answer(r["id"], approvals.ALLOW, actor="dashboard", path=self.path)
        self.assertTrue(won)  # the approval won; the merge failed
        self.assertIn("failed", msg.lower())
        self.assertIn("FAILED", approvals.get(r["id"], path=self.path)["reason"])

    def test_a_second_approver_cannot_merge_again(self) -> None:
        # First-decision-wins already; the action must fire exactly once.
        r = self.propose()
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            actions.answer(r["id"], approvals.ALLOW, actor="dashboard", path=self.path)
            won2, _ = actions.answer(r["id"], approvals.ALLOW, actor="slack", path=self.path)
        self.assertFalse(won2)
        self.assertEqual(run.call_count, 1)

    def test_a_plain_permission_is_decided_but_not_executed(self) -> None:
        # A non-merge approval routes through answer() untouched.
        approvals.request("p1", "t_x", "Bash", {"command": "ls"}, path=self.path)
        with mock.patch.object(subprocess, "run") as run:
            won, _ = actions.answer("p1", approvals.ALLOW, actor="x", path=self.path)
        self.assertTrue(won)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
