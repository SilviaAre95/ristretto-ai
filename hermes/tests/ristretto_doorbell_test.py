#!/usr/bin/env python3
"""Tests for the Slack doorbell.

A notifier has two ways to fail badly: telling you nothing, and telling you
so much that you stop reading. Both are covered here.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ristretto import doorbell, events

BASE = "http://100.64.0.1:8787"


def event(kind, **payload):
    return {
        "id": 1,
        "task_id": "t_a1b2c3d4",
        "issue_key": payload.pop("issue_key", "XARI-33"),
        "kind": kind,
        "stage": payload.pop("stage", None),
        "payload": payload or None,
        "created_at": 1_700_000_000,
    }


class MilestoneTests(unittest.TestCase):
    def test_progress_never_rings_the_doorbell(self) -> None:
        # A tier run emits six stage starts and six passes. Notifying on
        # those trains the reader to ignore the channel.
        for quiet in ("stage.started", "stage.passed", "verify.green", "preflight.passed"):
            self.assertNotIn(quiet, doorbell.MILESTONES, quiet)

    def test_outcomes_and_trouble_do(self) -> None:
        for loud in ("run.ended", "stage.failed", "pr.opened", "awaiting.approval"):
            self.assertIn(loud, doorbell.MILESTONES, loud)


class ComposeTests(unittest.TestCase):
    def test_a_pull_request_links_to_the_pull_request(self) -> None:
        text = doorbell.compose(
            event("pr.opened", url="https://github.com/o/r/pull/7"), BASE
        )
        self.assertIn("XARI-33", text)
        self.assertIn("https://github.com/o/r/pull/7", text)

    def test_a_failure_carries_the_reason_and_a_link(self) -> None:
        text = doorbell.compose(
            event("stage.failed", stage="plan", reason="model reported failure"), BASE
        )
        self.assertIn("failed at plan", text)
        self.assertIn("model reported failure", text)
        self.assertIn(f"{BASE}/task/t_a1b2c3d4", text)

    def test_a_wall_of_build_output_is_cut_down(self) -> None:
        text = doorbell.compose(event("stage.failed", reason="npm error " * 200), BASE)
        first = text.splitlines()[0]
        self.assertLess(len(first), 200, first)
        self.assertTrue(first.endswith("…"))

    def test_an_ended_run_distinguishes_success_from_failure(self) -> None:
        good = doorbell.compose(event("run.ended", outcome="completed"), BASE)
        bad = doorbell.compose(event("run.ended", outcome="failed"), BASE)
        self.assertIn("finished", good)
        self.assertIn("✓", good)
        self.assertIn("failed", bad)
        self.assertIn("✕", bad)

    def test_preflight_has_no_task_page_to_link_to(self) -> None:
        # It is not a run, so /task/<id> would be a dead link.
        text = doorbell.compose(
            {
                "id": 1,
                "task_id": "preflight-crema-connect",
                "kind": "preflight.failed",
                "payload": {"repo": "/repos/crema-connect", "errors": [".cc-verify missing"]},
                "created_at": 1,
            },
            BASE,
        )
        self.assertIn("crema-connect", text)
        self.assertIn(".cc-verify missing", text)
        self.assertNotIn("/task/", text)


class CursorTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.home = Path(scratch.name)
        self.db = self.home / "events.db"
        self.cursor = self.home / "doorbell.cursor"
        for kind in ("run.started", "stage.passed", "pr.opened"):
            events.emit("t_a1b2c3d4", kind, issue_key="XARI-33", path=self.db)

    def test_only_milestones_are_delivered(self) -> None:
        fresh = doorbell.since(0, path=self.db)
        self.assertEqual([e["kind"] for e in fresh], ["run.started", "pr.opened"])

    def test_nothing_is_sent_twice(self) -> None:
        with mock.patch.object(doorbell, "deliver", return_value=True) as sent, \
             mock.patch.object(doorbell, "cursor_path", return_value=self.cursor):
            first = doorbell.ring(BASE, "C1", path=self.db)
            second = doorbell.ring(BASE, "C1", path=self.db)
        self.assertEqual(first, 2)
        self.assertEqual(second, 0, "a milestone was announced twice")
        self.assertEqual(sent.call_count, 2)

    def test_a_failed_send_does_not_skip_the_message(self) -> None:
        # Advancing the cursor past an undelivered milestone would lose it
        # silently, which is the one thing a notifier must not do.
        with mock.patch.object(doorbell, "deliver", return_value=False), \
             mock.patch.object(doorbell, "cursor_path", return_value=self.cursor):
            self.assertEqual(doorbell.ring(BASE, "C1", path=self.db), 0)
        with mock.patch.object(doorbell, "deliver", return_value=True), \
             mock.patch.object(doorbell, "cursor_path", return_value=self.cursor):
            self.assertEqual(doorbell.ring(BASE, "C1", path=self.db), 2)

    def test_events_are_delivered_oldest_first(self) -> None:
        fresh = doorbell.since(0, path=self.db)
        self.assertEqual([e["id"] for e in fresh], sorted(e["id"] for e in fresh))


if __name__ == "__main__":
    unittest.main()


class ApprovalNotificationTest(unittest.TestCase):
    """The notification has to be answerable, not just informative."""

    def event(self, **payload):
        return {
            "kind": "awaiting.approval",
            "task_id": "t_a1b2c3d4",
            "issue_key": "XARI-36",
            "stage": "build",
            "payload": {"what": "Bash: npm run db:migrate", **payload},
        }

    def test_it_says_how_to_answer_and_says_DM(self) -> None:
        # A reply in a channel is not delivered unless it mentions the bot,
        # and a mention puts itself first so the command is never parsed.
        text = doorbell.compose(self.event(id="a1b2"), "http://ris:8787")
        self.assertIn("DM me", text)
        self.assertIn("!ris-approve a1b2", text)
        self.assertIn("!ris-deny a1b2", text)

    def test_it_still_links_to_the_dashboard(self) -> None:
        text = doorbell.compose(self.event(id="a1b2"), "http://ris:8787")
        self.assertIn("http://ris:8787/task/t_a1b2c3d4", text)

    def test_a_missing_id_does_not_produce_a_dangling_command(self) -> None:
        text = doorbell.compose(self.event(), "http://ris:8787")
        self.assertNotIn("!ris-approve  ", text)
