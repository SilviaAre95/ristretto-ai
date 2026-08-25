#!/usr/bin/env python3
"""Unit tests for the read-only fleet view.

Kept separate from the config suite because they need the optional dashboard
dependencies, and skip cleanly when those are absent.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest import mock

from ristretto.dash import data
from ristretto.dash.serve import BindRefused, resolve_host

try:
    from fastapi.testclient import TestClient

    from ristretto.dash.app import app

    WEB = True
except ImportError:  # pragma: no cover - exercised only without the extra
    WEB = False


NOW = int(time.time())


def task(**overrides):
    base = {
        "id": "t_a1b2c3d4",
        "title": "XARI-33 · loop-dev",
        "status": "running",
        "started_at": NOW - 600,
        "completed_at": None,
        "branch_name": "xariprojects/xari-33",
        "workspace_path": "/Users/x/code/kaffecard/.worktrees/t_a1b2c3d4",
    }
    base.update(overrides)
    return base


def event(kind: str, age: int = 10, **payload):
    return {
        "task_id": "t_a1b2c3d4",
        "kind": kind,
        "stage": payload.pop("stage", None),
        "payload": payload or None,
        "created_at": NOW - age,
    }


class BindTests(unittest.TestCase):
    """A dashboard that reads your board must not be trivially exposed."""

    def test_public_addresses_are_refused(self) -> None:
        for address in ("0.0.0.0", "::", "*"):
            with self.assertRaises(BindRefused, msg=address):
                resolve_host(address)

    def test_explicit_private_address_is_allowed(self) -> None:
        self.assertEqual(resolve_host("127.0.0.1"), ("127.0.0.1", "requested"))

    def test_tailnet_is_preferred_when_available(self) -> None:
        with mock.patch("ristretto.dash.serve.tailnet_address", return_value="100.64.0.1"):
            self.assertEqual(resolve_host(), ("100.64.0.1", "tailnet"))

    def test_falls_back_to_loopback_not_all_interfaces(self) -> None:
        with mock.patch("ristretto.dash.serve.tailnet_address", return_value=None):
            host, _ = resolve_host()
        self.assertEqual(host, "127.0.0.1")


class RunTests(unittest.TestCase):
    def test_active_run_with_recent_signal_is_running(self) -> None:
        run = data.build_run(task(), [event("stage.started", age=30, stage="build")])
        self.assertEqual(run.health, "running")
        self.assertEqual(run.stage, "build")

    def test_active_run_gone_quiet_is_stalled(self) -> None:
        run = data.build_run(task(), [event("stage.started", age=3600, stage="build")])
        self.assertEqual(run.health, "stalled")

    def test_blocked_beats_signal_age(self) -> None:
        run = data.build_run(task(status="blocked"), [event("stage.started", age=5)])
        self.assertEqual(run.health, "blocked")

    def test_finished_run_with_a_failure_reads_as_failed(self) -> None:
        run = data.build_run(
            task(status="done", completed_at=NOW),
            [event("stage.failed", age=60, stage="plan", reason="model reported failure")],
        )
        self.assertEqual(run.health, "failed")
        self.assertEqual(run.failure, "model reported failure")

    def test_finished_run_without_completion_time_has_unknown_elapsed(self) -> None:
        # Counting from the start would show a number that grows forever and
        # reads as though the work were still in flight.
        run = data.build_run(task(status="archived", started_at=NOW - 2_500_000), [])
        self.assertIsNone(run.elapsed)
        self.assertEqual(data.humanise(run.elapsed), "—")

    def test_running_run_elapsed_counts_from_start(self) -> None:
        run = data.build_run(task(started_at=NOW - 300), [])
        self.assertGreaterEqual(run.elapsed or 0, 300)

    def test_signal_source_is_reported_honestly(self) -> None:
        # Hermes exposes no heartbeat, so the view must not imply one.
        self.assertEqual(data.build_run(task(), []).signal_source, "start")
        self.assertEqual(data.build_run(task(), [event("run.started")]).signal_source, "event")
        self.assertEqual(data.build_run(task(started_at=None), []).signal_source, "none")

    def test_project_comes_from_the_worktree_path(self) -> None:
        self.assertEqual(data.build_run(task(), []).project, "kaffecard")
        self.assertEqual(data.build_run(task(workspace_path=None), []).project, "unassigned")

    def test_issue_key_comes_from_the_title(self) -> None:
        self.assertEqual(data.build_run(task(), []).issue_key, "XARI-33")

    def test_live_projects_sort_first(self) -> None:
        live = data.build_run(task(id="t_live", workspace_path="/x/aaa/.worktrees/t_live"), [])
        done = data.build_run(
            task(id="t_done", status="archived", workspace_path="/x/zzz/.worktrees/t_done"), []
        )
        self.assertEqual(list(data.grouped([done, live])), ["aaa", "zzz"])


@unittest.skipUnless(WEB, "dashboard extras not installed")
class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        patcher = mock.patch.object(data, "board", return_value=[task()])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fleet_renders(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("XARI-33", response.text)
        self.assertIn("kaffecard", response.text)

    def test_unknown_task_is_404(self) -> None:
        with mock.patch.object(data, "task_detail", return_value={}):
            self.assertEqual(self.client.get("/task/t_nope").status_code, 404)

    def test_task_detail_renders(self) -> None:
        with mock.patch.object(data, "task_detail", return_value={"task": task(), "runs": []}):
            response = self.client.get("/task/t_a1b2c3d4")
        self.assertEqual(response.status_code, 200)
        self.assertIn("xariprojects/xari-33", response.text)

    def test_there_are_no_mutating_routes(self) -> None:
        # Phase 2 observes and nothing else; controls arrive with the
        # privilege split that should accompany them.
        methods = {
            method
            for route in app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertFalse(methods & {"POST", "PUT", "PATCH", "DELETE"}, methods)


if __name__ == "__main__":
    unittest.main()
