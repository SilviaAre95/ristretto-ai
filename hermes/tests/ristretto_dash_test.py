#!/usr/bin/env python3
"""Unit tests for the read-only fleet view.

Kept separate from the config suite because they need the optional dashboard
dependencies, and skip cleanly when those are absent.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ristretto import approvals, events
from ristretto.dash import chat, control, data, serve
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
        "workspace_path": "/repos/kaffecard/.worktrees/t_a1b2c3d4",
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

    def test_a_quiet_run_with_a_live_flow_is_not_stalled(self) -> None:
        # A build stage emits nothing between its start and its finish and
        # legitimately runs for the better part of an hour. Judging on event
        # age alone reported healthy builds as stalled.
        run = data.build_run(task(), [event("stage.started", age=3600, stage="build")])
        self.assertEqual(run.health, "stalled")
        run.flow_alive = True
        self.assertEqual(run.health, "running")

    def test_silence_with_nothing_running_is_still_a_stall(self) -> None:
        run = data.build_run(task(), [event("stage.started", age=3600, stage="build")])
        run.flow_alive = False
        self.assertEqual(run.health, "stalled")

    def test_a_shell_mentioning_the_runner_is_not_a_live_flow(self) -> None:
        # A pattern search matches the command line of whatever runs the
        # search, so a monitor watching for a runner reported itself as one.
        listing = (
            "/bin/zsh -c pgrep -f 'ristretto.runner --task-id t_faker'\n"
            "/x/.venv/bin/python3 -m ristretto.runner --task-id t_real --issue A --flow tier1\n"
        )
        with mock.patch.object(
            data.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, listing, ""),
        ):
            self.assertEqual(data.running_flows(), {"t_real"})

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

    def test_history_is_hidden_but_live_work_never_is(self) -> None:
        # A fleet view showing every task ever finished is a graveyard: what
        # needs attention gets buried under months of identical archived rows.
        fresh = data.build_run(task(id="t_fresh", status="archived", started_at=NOW - 60), [])
        old = data.build_run(task(id="t_old", status="archived", started_at=NOW - 40 * 86400), [])
        quiet_but_live = data.build_run(
            task(id="t_live", status="running", started_at=NOW - 40 * 86400), []
        )
        keep, hidden = data.recent([fresh, old, quiet_but_live])
        self.assertEqual({r.task_id for r in keep}, {"t_fresh", "t_live"})
        self.assertEqual(hidden, 1)

    def test_age_is_stated_so_july_is_not_mistaken_for_today(self) -> None:
        self.assertEqual(data.ago(None), "—")
        self.assertTrue(data.ago(NOW - 90).endswith("ago"))

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

    def test_hostile_task_ids_never_reach_a_subprocess(self) -> None:
        # The id comes from a URL and crosses a process boundary. argv is not
        # a shell, but that is not a reason to pass request data unchecked.
        with mock.patch.object(data.subprocess, "run") as spawned:
            for hostile in ("../../etc/passwd", "a b", "$(whoami)", "-rf", "", "x" * 200):
                self.assertEqual(data.task_detail(hostile), {}, hostile)
            spawned.assert_not_called()

    def test_the_post_surface_is_exactly_what_we_intend(self) -> None:
        # Every POST here is a deliberate decision, so the set is pinned:
        #   stop/unblock change running work,
        #   chat spends a model turn but changes nothing and has no acting tools.
        # Launching work is absent — it writes code to a branch and must not
        # arrive as another route added by analogy to these.
        posting = {
            route.path
            for route in app.routes
            if "POST" in getattr(route, "methods", set())
        }
        self.assertEqual(
            posting,
            {
                "/task/{task_id}/stop",
                "/task/{task_id}/unblock",
                # Answering a flow that is blocked waiting on a person. The
                # store decides the winner, so these race safely with Slack.
                "/approval/{request_id}/approve",
                "/approval/{request_id}/deny",
                "/chat",
            },
        )
        others = {
            m
            for route in app.routes
            for m in getattr(route, "methods", set())
        } & {"PUT", "PATCH", "DELETE"}
        self.assertFalse(others, others)


class CrossSiteTests(unittest.TestCase):
    """There is no login, so a mutating route must know who is asking.

    Without this, any page visited while on the tailnet could post to the
    dashboard from the browser and stop a running agent.
    """

    def setUp(self) -> None:
        if not WEB:
            self.skipTest("dashboard extras not installed")
        self.client = TestClient(app)
        patcher = mock.patch.object(control, "stop", return_value=control.Outcome(True, "stopped"))
        self.stop = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, headers):
        return self.client.post(
            "/task/t_a1b2c3d4/stop", headers=headers, follow_redirects=False
        )

    def test_same_origin_form_post_is_accepted(self) -> None:
        response = self.post({"sec-fetch-site": "same-origin"})
        self.assertEqual(response.status_code, 303)
        self.stop.assert_called_once()

    def test_cross_site_post_is_refused(self) -> None:
        response = self.post({"sec-fetch-site": "cross-site"})
        self.assertEqual(response.status_code, 403)
        self.stop.assert_not_called()

    def test_same_site_is_not_good_enough(self) -> None:
        # A sibling subdomain is still not this page.
        self.assertEqual(self.post({"sec-fetch-site": "same-site"}).status_code, 403)
        self.stop.assert_not_called()

    def test_direct_navigation_is_refused(self) -> None:
        # "none" means no page triggered it, which a form post cannot be.
        self.assertEqual(self.post({"sec-fetch-site": "none"}).status_code, 403)
        self.stop.assert_not_called()

    def test_header_absent_falls_back_to_origin(self) -> None:
        ok = self.post({"origin": "http://testserver", "host": "testserver"})
        self.assertEqual(ok.status_code, 303)

    def test_header_absent_and_origin_mismatched_is_refused(self) -> None:
        bad = self.post({"origin": "http://evil.example", "host": "testserver"})
        self.assertEqual(bad.status_code, 403)
        self.stop.assert_not_called()

    def test_no_headers_at_all_is_refused(self) -> None:
        self.assertEqual(self.post({}).status_code, 403)
        self.stop.assert_not_called()

    def test_chat_is_same_origin_too(self) -> None:
        # It spends a model turn, and an endpoint anyone can drive is one
        # anyone can drain.
        with mock.patch.object(chat, "ask") as asked:
            refused = self.client.post(
                "/chat", json={"message": "hi"}, headers={"sec-fetch-site": "cross-site"}
            )
            self.assertEqual(refused.status_code, 403)
            asked.assert_not_called()


class ChatTests(unittest.TestCase):
    """Ris in the dashboard is Ris with its dangerous tools taken away."""

    def test_toolset_excludes_everything_that_can_act(self) -> None:
        # Unrestricted, asked to run a shell command, Ris runs it and reports
        # the output. On a page with no login that is remote code execution.
        forbidden = {"terminal", "file", "code_execution", "browser", "delegation", "cronjob"}
        self.assertFalse(forbidden & set(chat.TOOLSETS.split(",")), chat.TOOLSETS)

    def test_the_restriction_reaches_the_command_line(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "answer", "")
        with mock.patch.object(chat.subprocess, "run", return_value=completed) as spawned, \
             mock.patch.object(chat, "fleet_context", return_value="none"):
            chat.ask("hello")
        argv = spawned.call_args.args[0]
        self.assertIn("-t", argv)
        self.assertEqual(argv[argv.index("-t") + 1], chat.TOOLSETS)

    def test_empty_and_oversized_questions_never_spawn(self) -> None:
        with mock.patch.object(chat.subprocess, "run") as spawned:
            self.assertFalse(chat.ask("   ").ok)
            self.assertFalse(chat.ask("x" * (chat.MAX_MESSAGE + 1)).ok)
            spawned.assert_not_called()

    def test_a_timeout_is_reported_not_raised(self) -> None:
        with mock.patch.object(chat, "fleet_context", return_value="none"), \
             mock.patch.object(
                 chat.subprocess, "run",
                 side_effect=subprocess.TimeoutExpired("hermes", 180)):
            reply = chat.ask("hello")
        self.assertFalse(reply.ok)
        self.assertIn("did not answer", reply.text)

    def test_the_fleet_is_handed_over_not_looked_up(self) -> None:
        # Context is injected precisely so Ris needs no tools to fetch it.
        completed = subprocess.CompletedProcess([], 0, "answer", "")
        with mock.patch.object(chat, "fleet_context", return_value="RUN-A is stalled"), \
             mock.patch.object(chat.subprocess, "run", return_value=completed) as spawned:
            chat.ask("what is stalled?")
        prompt = spawned.call_args.args[0][2]
        self.assertIn("RUN-A is stalled", prompt)
        self.assertIn("what is stalled?", prompt)


class ControlActionTests(unittest.TestCase):
    def test_invalid_task_id_never_shells_out(self) -> None:
        with mock.patch.object(control.subprocess, "run") as spawned:
            for hostile in ("../../etc/passwd", "$(whoami)", "a b", ""):
                self.assertFalse(control.stop(hostile).ok, hostile)
                self.assertFalse(control.unblock(hostile).ok, hostile)
            spawned.assert_not_called()

    def test_stop_reports_failure_verbatim(self) -> None:
        # ris-stop.sh exits non-zero with NOT STOPPED when the kill did not
        # take. That must not be translated into a cheerful success.
        completed = subprocess.CompletedProcess([], 1, "NOT STOPPED: worker still alive", "")
        with tempfile.NamedTemporaryFile(suffix=".sh") as script, \
             mock.patch.object(control, "STOP_SCRIPT", Path(script.name)), \
             mock.patch.object(control.subprocess, "run", return_value=completed), \
             mock.patch.object(control.events, "emit"):
            outcome = control.stop("t_a1b2c3d4")
        self.assertFalse(outcome.ok)
        self.assertIn("NOT STOPPED", outcome.message)

    def test_actions_are_recorded_in_the_timeline(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "Unblocked t_a1b2c3d4", "")
        with mock.patch.object(control.subprocess, "run", return_value=completed), \
             mock.patch.object(control.events, "emit") as emitted:
            control.unblock("t_a1b2c3d4", actor="dashboard")
        emitted.assert_called_once()
        self.assertEqual(emitted.call_args.args[1], "control.unblock")
        self.assertTrue(emitted.call_args.kwargs["payload"]["ok"])

    def test_missing_kill_switch_is_reported_not_crashed(self) -> None:
        absent = Path(tempfile.gettempdir()) / "ris-stop-does-not-exist.sh"
        with mock.patch.object(control, "STOP_SCRIPT", absent):
            outcome = control.stop("t_a1b2c3d4")
        self.assertFalse(outcome.ok)
        self.assertIn("not installed", outcome.message)


if __name__ == "__main__":
    unittest.main()


class ApprovalRouteTests(unittest.TestCase):
    """Approving is the most consequential thing this page can do."""

    def setUp(self) -> None:
        if not WEB:
            self.skipTest("dashboard extras not installed")
        self.client = TestClient(app)
        self.dir = Path(tempfile.mkdtemp())
        self.store = self.dir / "approvals.db"
        patcher = mock.patch.object(approvals, "store_path", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        events_patch = mock.patch.object(events, "store_path", return_value=self.dir / "events.db")
        events_patch.start()
        self.addCleanup(events_patch.stop)
        approvals.request("r1", "t_a1b2c3d4", "Bash", {"command": "git push --force"})

    def post(self, path, site="same-origin"):
        return self.client.post(path, headers={"sec-fetch-site": site}, follow_redirects=False)

    def test_approving_records_the_decision(self) -> None:
        response = self.post("/approval/r1/approve")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(approvals.get("r1", path=self.store)["decision"], approvals.ALLOW)

    def test_denying_records_the_decision(self) -> None:
        self.post("/approval/r1/deny")
        self.assertEqual(approvals.get("r1", path=self.store)["decision"], approvals.DENY)

    def test_a_cross_site_post_cannot_approve(self) -> None:
        # The whole gate is worthless if a page you happened to visit can
        # answer it for you.
        self.assertEqual(self.post("/approval/r1/approve", site="cross-site").status_code, 403)
        self.assertIsNone(approvals.get("r1", path=self.store)["decision"])

    def test_losing_to_slack_is_reported_not_hidden(self) -> None:
        approvals.decide("r1", approvals.DENY, actor="slack", path=self.store)
        response = self.post("/approval/r1/approve")
        self.assertEqual(response.status_code, 303)
        self.assertIn("failed=", response.headers["location"])
        # And the standing decision is untouched.
        self.assertEqual(approvals.get("r1", path=self.store)["decision"], approvals.DENY)

    def test_the_task_page_offers_the_pending_request(self) -> None:
        with mock.patch.object(data, "task_detail", return_value={"task": task(), "runs": []}):
            page = self.client.get("/task/t_a1b2c3d4").text
        self.assertIn("git push --force", page)
        self.assertIn("/approval/r1/approve", page)


class LinkHostTests(unittest.TestCase):
    """What a phone can resolve is not what this process binds to.

    The doorbell wrote a bare 100.x address into every Slack link. That is
    opaque on a phone and dies the moment the machine is re-added to the
    tailnet and gets a new address — taking every link already sent with it.
    """

    def test_the_magicdns_name_wins(self) -> None:
        with mock.patch.object(serve, "tailnet_name", return_value="mac.tailnet.ts.net"), \
             mock.patch.object(serve, "tailnet_address", return_value="100.1.2.3"):
            self.assertEqual(serve.link_host(), "mac.tailnet.ts.net")

    def test_it_falls_back_to_the_address(self) -> None:
        with mock.patch.object(serve, "tailnet_name", return_value=None), \
             mock.patch.object(serve, "tailnet_address", return_value="100.1.2.3"):
            self.assertEqual(serve.link_host(), "100.1.2.3")

    def test_it_falls_back_to_loopback(self) -> None:
        with mock.patch.object(serve, "tailnet_name", return_value=None), \
             mock.patch.object(serve, "tailnet_address", return_value=None):
            self.assertEqual(serve.link_host(), "127.0.0.1")

    def test_a_bare_hostname_is_not_used(self) -> None:
        # Resolvable here, meaningless on the phone that receives the link.
        with mock.patch.object(serve.shutil, "which", return_value="/usr/bin/tailscale"), \
             mock.patch.object(serve.subprocess, "run") as run:
            run.return_value = serve.subprocess.CompletedProcess(
                [], 0, '{"Self": {"DNSName": "macstudio"}}', ""
            )
            self.assertIsNone(serve.tailnet_name())

    def test_the_trailing_dot_is_stripped(self) -> None:
        with mock.patch.object(serve.shutil, "which", return_value="/usr/bin/tailscale"), \
             mock.patch.object(serve.subprocess, "run") as run:
            run.return_value = serve.subprocess.CompletedProcess(
                [], 0, '{"Self": {"DNSName": "mac.tailnet.ts.net."}}', ""
            )
            self.assertEqual(serve.tailnet_name(), "mac.tailnet.ts.net")

    def test_tailscale_being_down_is_not_fatal(self) -> None:
        with mock.patch.object(serve.shutil, "which", return_value=None):
            self.assertIsNone(serve.tailnet_name())
