#!/usr/bin/env python3
"""Unit tests for the canonical run module.

These were the fleet view's tests. They moved with the code, because the
question they ask — what is this run, and is it alive — is no longer the
dashboard's to answer. `cuzam_dash_test.py` keeps what is genuinely about the
web surface: binding, routes, same-origin, controls.

`live_runs_contract_test.py` covers the other half, against real processes:
that `scripts/live-runs.sh` and this module agree about which of them are
runs. Here the process table is a fixture, so the cases that would need a real
flow — a dead run, a Claude child, a worktree that does not exist — can be
written at all.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from cuzam import runs

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
        "body": "issue: XARI-33\nrepo: /repos/kaffecard\nflow: full",
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


def staged(task_id: str = "t_a1b2c3d4", pid: int = 4242, flow: str = "full"):
    return runs.Process(
        task_id=task_id, pid=pid, shape="staged", flow=flow,
        command=f"/x/.venv/bin/python3 -m cuzam.runner --task-id {task_id} --flow {flow}",
    )


class HealthTests(unittest.TestCase):
    def test_active_run_with_a_live_process_is_running(self) -> None:
        run = runs.build_run(task(), [event("stage.started", age=30, stage="build")], staged())
        self.assertEqual(run.health, "running")
        self.assertEqual(run.stage, "build")

    def test_a_quiet_run_with_a_live_process_is_not_stalled(self) -> None:
        # A build stage emits nothing between its start and its finish and
        # legitimately runs for the better part of an hour. Judging on event
        # age alone reported healthy builds as stalled.
        quiet = [event("stage.started", age=3600, stage="build")]
        self.assertEqual(runs.build_run(task(), quiet, staged()).health, "running")

    def test_a_claimed_run_with_no_process_is_dead_immediately(self) -> None:
        # The behaviour this module was written for. Before it, a run whose
        # process had died read as `running` for fifteen minutes and only then
        # became the guess `stalled` — so the surface was at its most
        # confident exactly when it was most wrong.
        fresh = runs.build_run(task(), [event("stage.started", age=30, stage="build")])
        self.assertEqual(fresh.health, "dead")
        self.assertFalse(fresh.flow_alive)

    def test_dead_is_only_claimed_for_a_run_that_started(self) -> None:
        # A queued task has no process either, and calling it dead would put a
        # red pill on work that has simply not begun.
        for state in ("todo", "ready", "triage"):
            run = runs.build_run(task(status=state), [event("run.started", age=30)])
            self.assertEqual(run.health, "running", state)

    def test_silence_on_a_task_that_never_started_is_a_stall(self) -> None:
        # `stalled` survives for exactly this: no process ever existed, so its
        # absence proves nothing and only the silence is evidence.
        run = runs.build_run(task(status="ready"), [event("run.started", age=3600)])
        self.assertEqual(run.health, "stalled")

    def test_liveness_cannot_be_set_to_something_ps_disagrees_with(self) -> None:
        # It was a plain field, and a caller that forgot to set it turned every
        # run on the page dead. Deriving it from the pid removes the way to lie.
        run = runs.build_run(task(), [], staged())
        self.assertTrue(run.flow_alive)
        with self.assertRaises(AttributeError):
            run.flow_alive = False

    def test_blocked_beats_signal_age(self) -> None:
        run = runs.build_run(task(status="blocked"), [event("stage.started", age=5)])
        self.assertEqual(run.health, "blocked")

    def test_finished_run_with_a_failure_reads_as_failed(self) -> None:
        run = runs.build_run(
            task(status="done", completed_at=NOW),
            [event("stage.failed", age=60, stage="plan", reason="model reported failure")],
        )
        self.assertEqual(run.health, "failed")
        self.assertEqual(run.failure, "model reported failure")


class ProcessShapeTests(unittest.TestCase):
    """Two shapes, three flows, and everything else left alone."""

    def classify(self, command: str):
        return runs._classify(99, command)

    def test_a_classic_loop_is_recognised_by_its_pinned_path(self) -> None:
        found = self.classify(
            "/bin/bash /x/loop-runner/scripts/run-loop.sh t_classic XARI-1 --flow classic"
        )
        self.assertEqual((found.task_id, found.shape, found.flow), ("t_classic", "classic", "classic"))

    def test_a_classic_loop_reached_by_its_shebang_is_recognised_too(self) -> None:
        found = self.classify("/x/loop-runner/scripts/run-loop.sh t_classic XARI-1")
        self.assertEqual((found.task_id, found.shape, found.flow), ("t_classic", "classic", "classic"))

    def test_the_staged_runner_is_recognised_with_its_flow(self) -> None:
        found = self.classify(
            "/x/.venv/bin/python3 -m cuzam.runner --task-id t_x --issue A-1 --flow short"
        )
        self.assertEqual((found.task_id, found.shape, found.flow), ("t_x", "staged", "short"))

    def test_a_run_started_before_the_rename_still_counts(self) -> None:
        # Its command line says `ristretto.runner` for its whole hour, and a
        # live run read as dead is the inversion this module exists to stop.
        # Drop in 0.3.0.
        found = self.classify("/x/python3 -m ristretto.runner --task-id t_old --flow full")
        self.assertEqual(found.task_id, "t_old")

    def test_a_shell_that_mentions_the_runner_is_not_running_it(self) -> None:
        self.assertIsNone(
            self.classify("/bin/zsh -c pgrep -f 'cuzam.runner --task-id t_faker'")
        )

    def test_a_python_that_mentions_the_runner_is_not_running_it_either(self) -> None:
        # Not a shell, and still not a run: the module name appears inside the
        # source text handed to `-c`, so the command line carries
        # "-m cuzam.runner --task-id" without anything having imported it.
        # Found when this feature's own smoke test reported itself as live.
        self.assertIsNone(
            self.classify("python3 -c import_x -m cuzam.runner --task-id t_fake")
        )

    def test_the_console_script_is_a_run_too(self) -> None:
        # pyproject ships `cuzam-run-flow` and runner.py sets `prog` to it, so
        # it is a supported way to start a run — and it carries no `-m`.
        # Missing it did not merely hide the run: the board still said
        # `running`, so it rendered dead with a relaunch prompt while
        # install-runtime.sh rebuilt the runtime underneath it.
        found = self.classify("/x/.venv/bin/cuzam-run-flow --task-id t_s --issue A-1 --flow full")
        self.assertEqual((found.task_id, found.shape, found.flow), ("t_s", "staged", "full"))

    def test_a_classic_flow_given_positionally_is_read_correctly(self) -> None:
        # run-loop.sh also takes the flow positionally, so guessing `classic`
        # from the absence of a --flow flag labelled a `full` run wrongly on
        # every surface — overriding the task body, which was right.
        found = self.classify("/x/loop-runner/scripts/run-loop.sh t_c A-1 sonnet full")
        self.assertEqual(found.flow, "full")
        bare = self.classify("/x/loop-runner/scripts/run-loop.sh t_c A-1")
        self.assertEqual(bare.flow, "classic")

    def test_the_module_is_found_after_an_earlier_unrelated_dash_m(self) -> None:
        # The awk in live-runs.sh scans every -m; stopping at the first would
        # answer differently from the guard the installer trusts.
        found = self.classify(
            "/x/python3 -m coverage -m cuzam.runner --task-id t_m --flow full"
        )
        self.assertEqual(found.task_id, "t_m")

    def test_one_task_with_two_processes_resolves_to_the_runner(self) -> None:
        # A staged flow started through run-loop.sh leaves the wrapper in the
        # foreground piping the runner through tee, so both match under one
        # task id. Whichever ps emitted last used to win, which could label a
        # `full` run classic and report the shell's pid as its runner.
        wrapper = "/bin/bash /x/loop-runner/scripts/run-loop.sh t_b A-1 --flow full"
        child = "/x/python3 -m cuzam.runner --task-id t_b --issue A-1 --flow full"
        for pairing in ({1: wrapper, 2: child}, {2: child, 1: wrapper}):
            chosen = runs._live_map(pairing)["t_b"]
            self.assertEqual((chosen.shape, chosen.pid), ("staged", 2), pairing)

    def test_a_named_but_unidentified_runner_is_not_a_run(self) -> None:
        # No --task-id means nothing to attribute the process to, and a run
        # that cannot be named cannot be shown.
        self.assertIsNone(self.classify("/x/python3 -m cuzam.runner --flow full"))

    def test_running_flows_is_the_task_ids_of_the_live_processes(self) -> None:
        listing = (
            "  101 /bin/zsh -c pgrep -f 'cuzam.runner --task-id t_faker'\n"
            "  102 /x/.venv/bin/python3 -m cuzam.runner --task-id t_real --issue A --flow full\n"
            "  103 /bin/bash /x/loop-runner/scripts/run-loop.sh t_classic A-1\n"
        )
        with mock.patch.object(
            runs.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, listing, ""),
        ):
            self.assertEqual(runs.running_flows(), {"t_real", "t_classic"})

    def test_an_unreadable_process_table_is_not_a_machine_full_of_dead_runs(self) -> None:
        with mock.patch.object(runs.subprocess, "run", side_effect=OSError("no ps")):
            self.assertEqual(runs.running_flows(), set())


class UnreadableProcessTableTests(unittest.TestCase):
    """An absent answer is not the answer "no".

    `_ps` used to swallow every failure into an empty list, which downstream
    is indistinguishable from a quiet machine. With `dead` derived from that,
    one `ps` timing out under load painted the whole fleet red and told the
    operator to relaunch runs that were working — the 2026-09-10 shape,
    reintroduced by the feature written to prevent it.
    """

    def test_an_unreadable_table_is_none_not_empty(self) -> None:
        with mock.patch.object(runs.subprocess, "run", side_effect=OSError("no ps")):
            self.assertIsNone(runs._ps(10))
        with mock.patch.object(
            runs.subprocess, "run",
            side_effect=subprocess.TimeoutExpired("ps", 10),
        ):
            self.assertIsNone(runs._ps(10))
        with mock.patch.object(
            runs.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 1, "", "ps: cannot"),
        ):
            self.assertIsNone(runs._ps(10))

    def test_a_quiet_machine_is_still_an_empty_list(self) -> None:
        with mock.patch.object(
            runs.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ):
            self.assertEqual(runs._ps(10), [])

    def test_nothing_is_called_dead_on_evidence_that_could_not_be_read(self) -> None:
        run = runs.build_run(task(), [event("stage.started", age=30, stage="build")])
        self.assertEqual(run.health, "dead")
        run.liveness_known = False
        self.assertNotEqual(run.health, "dead")

    def test_an_unread_table_falls_back_to_the_signal_age_guess(self) -> None:
        # Which is what every surface did before there was a `dead` at all.
        quiet = runs.build_run(task(), [event("stage.started", age=3600, stage="build")])
        quiet.liveness_known = False
        self.assertEqual(quiet.health, "stalled")


class SnapshotOrderTests(unittest.TestCase):
    def test_the_board_is_read_before_the_process_table(self) -> None:
        """Reading `ps` first leaves a window a launch fits through.

        `launch` claims the task and spawns the flow between the two reads, so
        the run is `running` on a board read afterwards and absent from a
        snapshot taken before it existed — reported dead, with an invitation
        to relaunch something that had just started.
        """
        order = []
        with mock.patch.object(runs, "board", side_effect=lambda *a, **k: order.append("board") or []), \
             mock.patch.object(runs, "_ps", side_effect=lambda *a, **k: order.append("ps") or []), \
             mock.patch.object(runs.events, "read", return_value=[]):
            runs.fleet()
        self.assertEqual(order, ["board", "ps"])


class LocatorTests(unittest.TestCase):
    """Where a run is, taken from whatever recorded it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worktree = Path(self.tmp.name)

    def test_worktree_and_branch_come_from_the_board(self) -> None:
        run = runs.build_run(task(), [])
        self.assertEqual(str(run.worktree), "/repos/kaffecard/.worktrees/t_a1b2c3d4")
        self.assertEqual(run.branch, "xariprojects/xari-33")

    def test_the_flow_comes_from_the_live_process_before_the_task_body(self) -> None:
        # The body says what was asked for; argv says what is executing. They
        # differ when a run was relaunched on another flow, and the process is
        # the one that can still be wrong about nothing.
        run = runs.build_run(task(), [], staged(flow="short"))
        self.assertEqual(run.flow, "short")

    def test_the_task_body_answers_once_the_process_is_gone(self) -> None:
        self.assertEqual(runs.build_run(task(), []).flow, "full")

    def test_a_log_is_reported_only_when_the_file_exists(self) -> None:
        # A classic run keeps Claude's output in a mktemp file, so printing
        # `<worktree>/.cuzam/runs/<task>/flow.out` because that is where a log
        # would be sends someone after a file nothing ever wrote.
        run = runs.build_run(task(workspace_path=str(self.worktree)), [])
        self.assertIsNone(run.log)

        where = runs.run_dir(self.worktree, "t_a1b2c3d4")
        where.mkdir(parents=True)
        (where / "flow.out").write_text("stage: plan\n")
        self.assertEqual(run.log, where / "flow.out")

    def test_the_staged_log_written_by_run_loop_is_found_too(self) -> None:
        run = runs.build_run(task(workspace_path=str(self.worktree)), [])
        where = runs.run_dir(self.worktree, "t_a1b2c3d4")
        where.mkdir(parents=True)
        (where / "loop.log").write_text("runner\n")
        self.assertEqual(run.log, where / "loop.log")

    def test_an_artifact_directory_is_offered_only_when_it_is_there(self) -> None:
        # The rule that governs the log file was broken one line below it for
        # the directory: `cuzam gc` reclaims a finished worktree, so a run
        # still carded on the board routinely has neither, and both surfaces
        # printed a directory to go and look in that had never existed.
        run = runs.build_run(task(workspace_path=str(self.worktree)), [])
        self.assertIsNone(run.artifact_dir)

        runs.run_dir(self.worktree, "t_a1b2c3d4").mkdir(parents=True)
        self.assertEqual(run.artifact_dir, runs.run_dir(self.worktree, "t_a1b2c3d4"))

    def test_a_reclaimed_worktree_is_still_named_but_marked_gone(self) -> None:
        # Where a run was is the useful answer after gc has reclaimed it —
        # provided nothing pretends it is still somewhere to cd into.
        here = runs.build_run(task(workspace_path=str(self.worktree)), [])
        self.assertFalse(here.worktree_gone)

        reclaimed = runs.build_run(task(workspace_path=str(self.worktree / "gone")), [])
        self.assertTrue(reclaimed.worktree_gone)
        self.assertIsNotNone(reclaimed.worktree)

    def test_a_run_with_no_worktree_is_not_reported_as_reclaimed(self) -> None:
        self.assertFalse(runs.build_run(task(workspace_path=None), []).worktree_gone)

    def test_a_run_with_no_worktree_has_no_locators_rather_than_wrong_ones(self) -> None:
        run = runs.build_run(task(workspace_path=None), [])
        self.assertIsNone(run.worktree)
        self.assertIsNone(run.artifact_dir)
        self.assertIsNone(run.log)

    def test_the_run_directory_is_built_in_one_place(self) -> None:
        # Three copies of this path had drifted: the runner spelled it out
        # beside its own constant, launch spelled it out again, and a reader
        # had to spell it a third time to find either.
        from cuzam import runner

        self.assertEqual(runner.ARTIFACT_DIR_NAME, runs.ARTIFACT_DIR_NAME)
        self.assertEqual(
            runner.artifact_dir("t_x", Path("/w")), runs.run_dir(Path("/w"), "t_x")
        )


class ClaudeChildTests(unittest.TestCase):
    """The pid a classic run is waiting on, shown only when it is still that one."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = mock.patch.object(runs.Path, "home", return_value=Path(self.tmp.name))
        home.start()
        self.addCleanup(home.stop)
        self.record = Path(self.tmp.name) / ".hermes" / "kanban" / "default" / "pids"
        self.record.mkdir(parents=True)

    def write(self, **fields) -> None:
        body = {"pid": 777, "lstart": "Wed Sep 24 09:00:00 2026",
                "worktree": "/w", "runner": "claude"}
        body.update(fields)
        (self.record / "t_a1b2c3d4.json").write_text(json.dumps(body))

    def test_a_verified_child_is_reported(self) -> None:
        self.write()
        with mock.patch.object(
            runs.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, "Wed Sep 24 09:00:00 2026\n", ""),
        ):
            found = runs.claude_child("t_a1b2c3d4", {777: "/x/bin/claude -p --session-id abc"})
        self.assertEqual(found, 777)

    def test_a_reused_pid_is_not_reported(self) -> None:
        # The record outlives the process and the number comes back around.
        # Showing it unverified is how a surface points at somebody else's
        # work — the same reasoning reap.sh refuses to kill on.
        self.write()
        with mock.patch.object(
            runs.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, "Wed Sep 24 11:30:00 2026\n", ""),
        ):
            found = runs.claude_child("t_a1b2c3d4", {777: "/x/bin/claude -p"})
        self.assertIsNone(found)

    def test_a_pid_running_something_else_is_not_reported(self) -> None:
        self.write()
        self.assertIsNone(runs.claude_child("t_a1b2c3d4", {777: "/usr/bin/vim notes.md"}))

    def test_a_dead_pid_is_not_reported(self) -> None:
        self.write()
        self.assertIsNone(runs.claude_child("t_a1b2c3d4", {}))

    def test_no_record_is_not_an_error(self) -> None:
        self.assertIsNone(runs.claude_child("t_nothing", {}))

    def test_a_corrupt_record_is_not_an_error(self) -> None:
        (self.record / "t_a1b2c3d4.json").write_text("{not json")
        self.assertIsNone(runs.claude_child("t_a1b2c3d4", {}))

    def test_only_a_live_classic_run_is_asked_about(self) -> None:
        # A staged flow has no Claude child of its own, and a dead run's
        # record has already been removed by reap.sh — so a surviving one
        # names a pid that belongs to someone else.
        self.assertIsNone(runs._claude_for(None, {}))
        self.assertIsNone(runs._claude_for(staged(), {}))


class ListingTests(unittest.TestCase):
    def test_history_is_hidden_but_live_work_never_is(self) -> None:
        # A fleet view showing every task ever finished is a graveyard: what
        # needs attention gets buried under months of identical archived rows.
        fresh = runs.build_run(task(id="t_fresh", status="archived", started_at=NOW - 60), [])
        old = runs.build_run(task(id="t_old", status="archived", started_at=NOW - 40 * 86400), [])
        quiet_but_live = runs.build_run(
            task(id="t_live", status="running", started_at=NOW - 40 * 86400), []
        )
        keep, hidden = runs.recent([fresh, old, quiet_but_live])
        self.assertEqual({r.task_id for r in keep}, {"t_fresh", "t_live"})
        self.assertEqual(hidden, 1)

    def test_live_projects_sort_first(self) -> None:
        live = runs.build_run(task(id="t_live", workspace_path="/x/aaa/.worktrees/t_live"), [])
        done = runs.build_run(
            task(id="t_done", status="archived", workspace_path="/x/zzz/.worktrees/t_done"), []
        )
        self.assertEqual(list(runs.grouped([done, live])), ["aaa", "zzz"])

    def test_a_run_is_found_by_task_id_or_issue_key(self) -> None:
        fleet = [runs.build_run(task(), [])]
        self.assertIsNotNone(runs.find("t_a1b2c3d4", fleet))
        self.assertIsNotNone(runs.find("xari-33", fleet))
        self.assertIsNone(runs.find("XARI-99", fleet))
        self.assertIsNone(runs.find("", fleet))

    def test_project_comes_from_the_worktree_path(self) -> None:
        self.assertEqual(runs.build_run(task(), []).project, "kaffecard")
        self.assertEqual(runs.build_run(task(workspace_path=None), []).project, "unassigned")

    def test_issue_key_comes_from_the_title(self) -> None:
        self.assertEqual(runs.build_run(task(), []).issue_key, "XARI-33")

    def test_signal_source_is_reported_honestly(self) -> None:
        # Hermes exposes no heartbeat, so no surface may imply one.
        self.assertEqual(runs.build_run(task(), []).signal_source, "start")
        self.assertEqual(runs.build_run(task(), [event("run.started")]).signal_source, "event")
        self.assertEqual(runs.build_run(task(started_at=None), []).signal_source, "none")

    def test_finished_run_without_completion_time_has_unknown_elapsed(self) -> None:
        # Counting from the start would show a number that grows forever and
        # reads as though the work were still in flight.
        run = runs.build_run(task(status="archived", started_at=NOW - 2_500_000), [])
        self.assertIsNone(run.elapsed)
        self.assertEqual(runs.humanise(run.elapsed), "—")

    def test_running_run_elapsed_counts_from_start(self) -> None:
        self.assertGreaterEqual(runs.build_run(task(started_at=NOW - 300), []).elapsed or 0, 300)

    def test_age_is_stated_so_july_is_not_mistaken_for_today(self) -> None:
        self.assertEqual(runs.ago(None), "—")
        self.assertTrue(runs.ago(NOW - 90).endswith("ago"))

    def test_hostile_task_ids_never_reach_a_subprocess(self) -> None:
        # The id reaches here from a URL. argv is not a shell, but that is not
        # a reason to pass request data to another program unchecked.
        with mock.patch.object(runs.subprocess, "run") as spawned:
            for hostile in ("../../etc/passwd", "a b", "$(whoami)", "-rf", "", "x" * 200):
                self.assertEqual(runs.task_detail(hostile), {}, hostile)
            spawned.assert_not_called()


class ReturnShapeTests(unittest.TestCase):
    """The contract every surface renders.

    Pinned by name: a renderer that is not in this repository — a Hermes
    dashboard tab, say — would break silently on a field quietly renamed.
    """

    def test_the_documented_fields_are_all_present(self) -> None:
        shape = runs.build_run(task(), [event("stage.started", stage="build")], staged()).as_dict()
        self.assertEqual(
            set(shape),
            {
                "task_id", "issue_key", "title", "project", "status", "health", "alive",
                "liveness_known",
                "flow", "shape", "stage", "branch", "worktree", "worktree_gone",
                "artifact_dir", "log",
                "runner_pid", "claude_pid", "started_at", "completed_at", "elapsed",
                "last_signal_at", "signal_source", "age_of_signal", "failure",
            },
        )

    def test_it_survives_json(self) -> None:
        # `cuzam runs --json` is a documented surface, so a Path leaking into
        # the shape is a break, not a cosmetic problem.
        shape = runs.build_run(task(), [], staged()).as_dict()
        self.assertEqual(json.loads(json.dumps(shape))["worktree"], shape["worktree"])

    def test_no_surface_asks_the_operating_system_or_the_board_itself(self) -> None:
        """The criterion, made checkable rather than asserted in a doc.

        A renderer that reaches past this module for one fact is how the three
        disagreeing implementations happened the first time: each was added by
        someone who needed an answer the surface in front of them did not have.

        `kanban` verbs that *act* are not covered — `launch` and the stop
        control legitimately claim, create and unblock. What no surface may do
        is read run state for itself.
        """
        surfaces = [
            Path(__file__).resolve().parents[2] / name
            for name in (
                "cuzam/cli.py",
                "cuzam/dash/app.py",
                "cuzam/assistant/tools.py",
            )
        ]
        for surface in surfaces:
            source = surface.read_text()
            for forbidden in ('"ps"', "kanban\", \"list", "kanban\", \"show", "pgrep"):
                self.assertNotIn(
                    forbidden, source,
                    f"{surface.name} asks for run state itself ({forbidden}); "
                    "the answer belongs in cuzam/runs.py so every surface gets it",
                )

    def test_the_module_changes_nothing(self) -> None:
        """Read-only by decision, and the decision is worth a tripwire.

        On 2026-09-10 a surface that could not tell alive from dead restarted
        a healthy run. This one can tell — which makes it more tempting, not
        less, to have it tidy the board up.
        """
        source = Path(runs.__file__).read_text()
        # Parsed, not grepped. The prose here is full of reclaiming and
        # killing, because it explains why this module does neither, and a
        # substring scan reads the explanation as the offence.
        called = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
        for forbidden in (
            "subprocess.Popen", "os.kill", "signal.signal", "os.remove", "shutil.rmtree"
        ):
            self.assertNotIn(forbidden, called, f"{forbidden} in a read-only module")
        self.assertNotIn(
            "write_text", {name.rsplit(".", 1)[-1] for name in called},
            "a read-only module wrote a file",
        )
        # And the only board commands it runs are reads.
        self.assertEqual(
            sorted(set(re.findall(r'"kanban", "(\w+)"', source))), ["list", "show"]
        )

    def test_the_module_holds_no_web_framework(self) -> None:
        # What keeps a second renderer a rendering job. If this module ever
        # imports a request or a template, the CLI and any future surface
        # inherit the dashboard's dependencies along with its assumptions.
        source = (Path(runs.__file__)).read_text()
        for forbidden in ("fastapi", "starlette", "jinja2", "Request", "TemplateResponse"):
            self.assertNotIn(forbidden, source, forbidden)


if __name__ == "__main__":
    unittest.main()
