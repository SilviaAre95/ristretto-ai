#!/usr/bin/env python3
"""Unit tests for the approval store.

The property under test throughout is that nothing except an explicit human
allow produces an allow.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import time

from ristretto import approvals, broker, events, runner


class ApprovalStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "approvals.db"
        self.events = self.dir / "events.db"
        patcher = mock.patch.object(events, "store_path", return_value=self.events)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, request_id: str = "u1", **kwargs) -> dict:
        return approvals.request(
            request_id,
            kwargs.pop("task_id", "t_a1b2c3d4"),
            kwargs.pop("tool_name", "Bash"),
            kwargs.pop("tool_input", {"command": "rm -rf build"}),
            path=self.path,
            **kwargs,
        )

    def test_a_request_is_pending_and_announced(self) -> None:
        self.ask()
        waiting = approvals.pending(path=self.path)
        self.assertEqual([item["id"] for item in waiting], ["u1"])
        self.assertIn("rm -rf build", waiting[0]["what"])
        kinds = [item["kind"] for item in events.read(path=self.events)]
        self.assertIn("awaiting.approval", kinds)

    def test_the_first_decision_wins(self) -> None:
        self.ask()
        won, _ = approvals.decide("u1", approvals.ALLOW, actor="dashboard", path=self.path)
        lost, message = approvals.decide("u1", approvals.DENY, actor="slack", path=self.path)
        self.assertTrue(won)
        self.assertFalse(lost)
        self.assertIn("already allow", message)
        self.assertIn("dashboard", message)

    def test_concurrent_deciders_produce_exactly_one_winner(self) -> None:
        # Both surfaces are live at once; a race must not double-decide.
        self.ask()
        results: list[bool] = []
        lock = threading.Lock()

        def answer(verdict: str, who: str) -> None:
            won, _ = approvals.decide("u1", verdict, actor=who, path=self.path)
            with lock:
                results.append(won)

        threads = [
            threading.Thread(target=answer, args=(approvals.ALLOW, "dashboard")),
            threading.Thread(target=answer, args=(approvals.DENY, "slack")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), [False, True])

    def test_a_decided_request_leaves_the_pending_list(self) -> None:
        self.ask()
        approvals.decide("u1", approvals.DENY, actor="slack", path=self.path)
        self.assertEqual(approvals.pending(path=self.path), [])

    def test_an_unknown_decision_value_is_a_deny(self) -> None:
        # A corrupt or hostile value must never resolve to allow.
        self.ask()
        _, verdict = approvals.decide("u1", "yes-please", actor="x", path=self.path)
        self.assertEqual(verdict, approvals.DENY)

    def test_deciding_something_that_does_not_exist_fails(self) -> None:
        won, message = approvals.decide("nope", approvals.ALLOW, actor="x", path=self.path)
        self.assertFalse(won)
        self.assertIn("no such approval", message)


class AwaitDecisionTest(ApprovalStoreTest):
    def test_an_allow_is_relayed(self) -> None:
        self.ask()
        approvals.decide("u1", approvals.ALLOW, actor="dashboard", path=self.path)
        decision, _ = approvals.await_decision("u1", path=self.path, sleep=lambda _: None)
        self.assertEqual(decision, approvals.ALLOW)

    def test_a_deny_carries_its_reason(self) -> None:
        self.ask()
        approvals.decide("u1", approvals.DENY, actor="slack", reason="not on main", path=self.path)
        decision, reason = approvals.await_decision("u1", path=self.path, sleep=lambda _: None)
        self.assertEqual(decision, approvals.DENY)
        self.assertEqual(reason, "not on main")

    def test_no_answer_parks_as_denied(self) -> None:
        self.ask()
        clock = iter([0, 0, 1, 999])
        decision, reason = approvals.await_decision(
            "u1",
            timeout_seconds=10,
            path=self.path,
            now=lambda: next(clock),
            sleep=lambda _: None,
        )
        self.assertEqual(decision, approvals.DENY)
        self.assertIn("timeout", reason)
        # And it is recorded, so the surfaces stop offering a dead question.
        self.assertEqual(approvals.pending(path=self.path), [])

    def test_an_unreadable_store_is_a_deny(self) -> None:
        # Fail closed: losing the store must not mean proceeding.
        with mock.patch.object(approvals, "connect", side_effect=sqlite3.Error("gone")):
            decision, reason = approvals.await_decision("u1", path=self.path, sleep=lambda _: None)
        self.assertEqual(decision, approvals.DENY)
        self.assertIn("unreadable", reason)


class DescribeTest(unittest.TestCase):
    def test_the_command_is_named_not_just_the_tool(self) -> None:
        self.assertEqual(
            approvals.describe("Bash", {"command": "git push --force"}),
            "Bash: git push --force",
        )

    def test_a_long_command_is_truncated(self) -> None:
        text = approvals.describe("Bash", {"command": "x" * 500})
        self.assertLessEqual(len(text), 130)
        self.assertTrue(text.endswith("…"))

    def test_an_unrecognised_shape_still_names_the_tool(self) -> None:
        self.assertEqual(approvals.describe("WebFetch", {"weird": 1}), "WebFetch")




class BrokerTest(ApprovalStoreTest):
    """The shape of what goes back to Claude Code is a hard contract: a wrong
    field name or an extra content block and the permission prompt fails.
    """

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(approvals, "store_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env = {"RISTRETTO_TASK_ID": "t_a1b2c3d4", "RISTRETTO_APPROVAL_TIMEOUT": "60"}

    def test_allow_returns_the_updated_input(self) -> None:
        payload = {"tool_name": "Bash", "input": {"command": "ls"}, "tool_use_id": "u1"}
        with mock.patch.object(approvals, "await_decision", return_value=(approvals.ALLOW, "")):
            result = broker.decide(payload, environ=self.env)
        self.assertEqual(result, {"behavior": "allow", "updatedInput": {"command": "ls"}})

    def test_deny_carries_the_reason(self) -> None:
        payload = {"tool_name": "Bash", "input": {"command": "ls"}, "tool_use_id": "u2"}
        with mock.patch.object(approvals, "await_decision", return_value=(approvals.DENY, "nope")):
            result = broker.decide(payload, environ=self.env)
        self.assertEqual(result, {"behavior": "deny", "message": "nope"})

    def test_a_denied_result_never_carries_updated_input(self) -> None:
        # updatedInput on a deny is how a "no" turns into a "yes, with these
        # arguments" if anything downstream reads the wrong field.
        result = broker.permission_result(approvals.DENY, message="no")
        self.assertNotIn("updatedInput", result)

    def test_no_owning_task_is_a_deny(self) -> None:
        payload = {"tool_name": "Bash", "input": {}, "tool_use_id": "u3"}
        result = broker.decide(payload, environ={})
        self.assertEqual(result["behavior"], "deny")
        self.assertIn("RISTRETTO_TASK_ID", result["message"])

    def test_the_request_is_recorded_for_both_surfaces(self) -> None:
        payload = {"tool_name": "Bash", "input": {"command": "rm -rf x"}, "tool_use_id": "u4"}
        with mock.patch.object(approvals, "await_decision", return_value=(approvals.DENY, "")):
            broker.decide(payload, environ=self.env)
        stored = approvals.get("u4", path=self.path)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["task_id"], "t_a1b2c3d4")
        self.assertIn("rm -rf x", stored["what"])

    def test_a_call_with_no_tool_use_id_still_works(self) -> None:
        # Claude has passed one every time observed, but a missing id must not
        # crash the gate into failing open.
        with mock.patch.object(approvals, "await_decision", return_value=(approvals.DENY, "")):
            result = broker.decide({"tool_name": "Bash", "input": {}}, environ=self.env)
        self.assertEqual(result["behavior"], "deny")



class HeartbeatKeeperTest(unittest.TestCase):
    """A long stage must keep the claim alive on its own.

    The first live run spent 35 minutes inside one build stage without
    reaching a boundary; boundary-only heartbeats would have let the task be
    reclaimed under a live pid.
    """

    def test_it_beats_without_a_stage_boundary(self) -> None:
        beats: list[str] = []
        with mock.patch.object(runner, "heartbeat", side_effect=lambda _t, s: beats.append(s)):
            pulse = runner.Heartbeat("t_a1b2c3d4", interval=0.01)
            pulse.enter("build")
            pulse.start()
            for _ in range(200):
                if len(beats) >= 3:
                    break
                time.sleep(0.01)
            pulse.stop()
        self.assertGreaterEqual(len(beats), 3, "a long stage stopped reporting itself alive")
        self.assertEqual(beats[-1], "build", "the beat should name the stage still running")

    def test_stopping_ends_the_beats(self) -> None:
        # A heartbeat outliving its flow is a lie the board acts on.
        beats: list[str] = []
        with mock.patch.object(runner, "heartbeat", side_effect=lambda _t, s: beats.append(s)):
            pulse = runner.Heartbeat("t_a1b2c3d4", interval=0.01)
            pulse.start()
            time.sleep(0.05)
            pulse.stop()
            time.sleep(0.05)
            settled = len(beats)
            time.sleep(0.05)
        self.assertEqual(len(beats), settled)

if __name__ == "__main__":
    unittest.main()
