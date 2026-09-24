"""Starting a flow without a worker, and approvals you can actually read.

Two defects found by running a real tier1 flow on 2026-09-11:

* every approval the local coder raised rendered as a tool name and nothing
  else, because the stored JSON was clipped mid-string and no longer parsed —
  five blank cheques in a row, in the flow the gate matters most for;
* the dispatched path always hands the task to an agent profile, so a language
  model was the thing running a script and waiting for it. It killed three
  healthy runs.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cuzam import approvals  # noqa: E402
from cuzam.dash import launch  # noqa: E402


class StoredInputTest(unittest.TestCase):
    """What is stored must parse, or the card shows a blank cheque."""

    def test_a_small_call_is_stored_whole(self) -> None:
        stored = approvals.stored_input({"command": "ls -la"})

        self.assertEqual(json.loads(stored), {"command": "ls -la"})

    def test_a_heredoc_bigger_than_the_cap_still_parses(self) -> None:
        # The exact shape that broke it: one enormous string value. Clipping
        # the serialised document cut it mid-string.
        huge = "cat > /tmp/x.py << 'EOF'\n" + ("x = 1\n" * 4000)

        stored = approvals.stored_input({"command": huge})

        self.assertLessEqual(len(stored), approvals.MAX_STORED_INPUT)
        parsed = json.loads(stored)
        self.assertTrue(parsed["command"].startswith("cat > /tmp/x.py"))
        self.assertIn("more characters", parsed["command"])

    def test_the_opening_of_the_command_survives(self) -> None:
        # The question a person answers is "what is this trying to do", and
        # the first line answers it.
        huge = "rm -rf /important/path && " + ("echo padding; " * 2000)

        parsed = json.loads(approvals.stored_input({"command": huge}))

        self.assertIn("rm -rf /important/path", parsed["command"])

    def test_a_call_with_very_many_keys_degrades_to_something_true(self) -> None:
        wide = {f"key_{i}": "v" * 300 for i in range(400)}

        parsed = json.loads(approvals.stored_input(wide))

        self.assertTrue(parsed["_clipped"])
        self.assertGreater(parsed["_bytes"], approvals.MAX_STORED_INPUT)

    def test_a_clipped_call_still_describes_itself(self) -> None:
        huge = "psql -c 'DROP TABLE customers' " + ("-v x=1 " * 2000)
        stored = approvals.stored_input({"command": huge})

        described = approvals.describe("Bash", json.loads(stored))

        self.assertIn("DROP TABLE customers", described)


class UnreadableRowTest(unittest.TestCase):
    """Rows written before the fix are still in the store, still corrupt."""

    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "approvals.db"

    def test_a_corrupt_row_says_so_instead_of_looking_empty(self) -> None:
        with approvals.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO approvals (id, task_id, tool_name, tool_input, "
                "requested_at, expires_at) VALUES (?,?,?,?,?,?)",
                ("r1", "t_x", "Bash", '{"command": "cat > /tmp/x <<EOF\\nunterminat',
                 1, 2 ** 31),
            )

        row = approvals.get("r1", path=self.path)

        self.assertIn("unreadable", row["what"])
        self.assertNotEqual(row["what"], "Bash")


FIXTURE_CONFIG = {
    "default_flow": "full",
    "base_branch": "main",
    "flows": {
        "classic": {"description": "existing loop", "builtin": "classic"},
        "full": {"description": "plan, build, review, repair, verify, PR", "stages": []},
    },
}


class StartFlowTest(unittest.TestCase):
    """Claim the task, cut the worktree, run a process — never an agent."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@e.com"),
                     ("config", "user.name", "T")):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        (self.repo / "README.md").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "base"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "branch", "feat/x"], check=True)
        self.addCleanup(self.tmp.cleanup)
        # A real file, because start_flow refuses to claim a task it cannot
        # start and checks that the script is there. A fake path would make
        # every classic case here assert the refusal instead of the spawn.
        self.script = (
            self.repo / "pinned" / "hermes" / "skills" / "loop-runner" / "scripts" / "run-loop.sh"
        )
        self.script.parent.mkdir(parents=True)
        self.script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        self.script.chmod(0o755)

    def run_start(self, claim_rc: int = 0, flow: str = "full", model: str = "",
                  script: Path | None = None):
        """Let git run for real; intercept only the board and the flow spawn.

        Patching Popen wholesale would break the real git calls too, since
        subprocess.run goes through it — so git is delegated back to the real
        one and only the runner spawn is caught.

        The config is a fixture rather than this machine's: what counts as
        `classic` decides which of two programs is spawned, and a test whose
        answer depends on the developer's own cuzam.yaml proves nothing.
        """
        calls: list[list[str]] = []
        spawned: list[tuple[list[str], dict]] = []
        real_run, real_popen = subprocess.run, subprocess.Popen

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            if argv[:2] == ["hermes", "kanban"]:
                return subprocess.CompletedProcess(argv, claim_rc, "", "lease held")
            return real_run(argv, **kwargs)

        def fake_popen(argv, **kwargs):
            if argv and argv[0] == "git":
                return real_popen(argv, **kwargs)
            spawned.append((list(argv), kwargs))
            return mock.Mock(pid=4242)

        # Pinned explicitly: exercising the real flow_interpreter would make
        # the result depend on whether this machine has a runtime installed.
        with mock.patch.object(launch, "flow_interpreter",
                               return_value=([sys.executable, "-P"], {"PATH": "/usr/bin"}, "")), \
             mock.patch.object(launch, "flow_script",
                               return_value=(self.script if script is None else script, "")), \
             mock.patch.object(launch, "load_config",
                               return_value=(FIXTURE_CONFIG, Path("fixture.yaml"))), \
             mock.patch.object(launch.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(launch.subprocess, "Popen", side_effect=fake_popen):
            problem = launch.start_flow(
                str(self.repo), "feat/x", "t_abc", "XARI-1", flow, model
            )
        return problem, calls, spawned

    def test_it_claims_before_starting_anything(self) -> None:
        problem, calls, _s = self.run_start()

        self.assertEqual(problem, "")
        self.assertIn(["hermes", "kanban", "claim", "t_abc", "--ttl",
                       str(launch.CLAIM_TTL_SECONDS)], calls)

    def test_it_never_dispatches_a_worker(self) -> None:
        _, calls, _ = self.run_start()

        for argv in calls:
            self.assertNotIn("dispatch", argv)

    def test_a_refused_claim_stops_before_the_worktree(self) -> None:
        # Otherwise two runners could share one worktree, which is the failure
        # the board's lease exists to prevent.
        problem, _, spawned = self.run_start(claim_rc=1)

        self.assertIn("could not claim", problem)
        self.assertEqual(spawned, [], "nothing may be started without the claim")
        self.assertFalse((self.repo / launch.WORKTREE_DIR / "t_abc").exists())

    def test_it_cuts_the_worktree_at_the_run_branch(self) -> None:
        self.run_start()

        worktree = self.repo / launch.WORKTREE_DIR / "t_abc"
        self.assertTrue(worktree.exists())
        head = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(head.stdout.strip(), "feat/x")

    def test_the_flow_runs_detached_in_the_worktree(self) -> None:
        _, _, spawned = self.run_start()

        self.assertEqual(len(spawned), 1, "exactly one flow process")
        argv, kwargs = spawned[0]
        # Not sys.executable: the flow runs from the pinned runtime when one
        # is installed, which is the whole point of separating them. What this
        # guards is the invocation shape, not which copy answers.
        self.assertEqual(argv[:2], [sys.executable, "-P"])
        self.assertEqual(argv[2:4], ["-m", "cuzam.runner"])
        self.assertIn("--task-id", argv)
        self.assertEqual(kwargs["cwd"], self.repo / launch.WORKTREE_DIR / "t_abc")
        self.assertTrue(kwargs["start_new_session"],
                        "the flow must outlive the CLI or Slack request that started it")

    def test_classic_spawns_the_loop_and_never_the_multi_stage_runner(self) -> None:
        # The defect this change exists to fix, verified against the pinned
        # runtime before it was written: `-m cuzam.runner --flow classic` exits 2
        # with "classic is executed by run-loop.sh, not the multi-stage runner".
        # Popen had already returned a pid, so `launch` reported the run started
        # while the task sat claimed and `running` with nothing running it — and
        # `active_runs` counted it, refusing the next launch until the TTL lapsed.
        problem, _, spawned = self.run_start(flow="classic")

        self.assertEqual(problem, "")
        argv, kwargs = spawned[0]
        self.assertNotIn("cuzam.runner", argv, "classic is not the staged runner")
        self.assertNotIn("-m", argv)
        self.assertEqual(argv[0], "bash")
        self.assertTrue(argv[1].endswith("loop-runner/scripts/run-loop.sh"))
        self.assertEqual(argv[2:4], ["t_abc", "XARI-1"],
                         "run-loop.sh reads the task id and issue positionally")
        self.assertEqual(argv[-2:], ["--flow", "classic"])
        self.assertEqual(kwargs["cwd"], self.repo / launch.WORKTREE_DIR / "t_abc")
        self.assertTrue(kwargs["start_new_session"])

    def test_the_classic_argv_is_one_both_liveness_matchers_can_read(self) -> None:
        # Not a restatement of the assertions above: this states the *reason* the
        # shape is what it is. `runs._classify` scans argv positions 0 and 1 for
        # the script and reads the task id at position+1; the awk in live-runs.sh
        # checks fields $2 and $3. A run spawned in a shape neither reads is a
        # run reported dead while it works, with an invitation to relaunch it.
        from cuzam import runs

        _, _, spawned = self.run_start(flow="classic")
        argv, _ = spawned[0]

        process = runs._classify(4242, " ".join(argv))
        self.assertIsNotNone(process, "the launcher spawned a shape runs.py cannot see")
        self.assertEqual(process.shape, "classic")
        self.assertEqual(process.task_id, "t_abc")
        self.assertEqual(process.flow, "classic")

    def test_a_model_tier_reaches_the_loop_the_way_it_parses_it(self) -> None:
        # run-loop.sh only enters flag parsing when its first argument after the
        # shift is --model or --flow, so the order here is load-bearing.
        _, _, spawned = self.run_start(flow="classic", model="sonnet")
        argv, _ = spawned[0]

        self.assertEqual(argv[4:], ["--model", "sonnet", "--flow", "classic"])

        from cuzam import runs

        process = runs._classify(4242, " ".join(argv))
        self.assertEqual(process.flow, "classic",
                         "a positional-looking argv must not read as another flow")

    def test_an_invalid_tier_is_refused_before_the_board_is_touched(self) -> None:
        # run-loop.sh exits 2 on an unknown tier. Through the launcher that is a
        # run reported as started and dead a moment later.
        problem, calls, spawned = self.run_start(flow="classic", model="gpt-9")

        self.assertIn("unknown model tier", problem)
        self.assertEqual(spawned, [])
        for argv in calls:
            self.assertNotIn("claim", argv, "nothing may be claimed for a run that cannot start")

    def test_a_retired_tier_still_runs_rather_than_blocking_a_relaunch(self) -> None:
        # A task queued before 2026-09-23 carries `model: local` in its body, and
        # relaunch reads the body. Rejecting it would block the task rather than
        # run it on the Claude default, which is the point of retiring the local
        # coder. run-loop.sh accepts and drops it; so does the launcher.
        problem, _, spawned = self.run_start(flow="classic", model="local")

        self.assertEqual(problem, "")
        argv, _ = spawned[0]
        self.assertNotIn("--model", argv, "the retired tier is dropped, not forwarded")
        self.assertNotIn("local", argv)
        self.assertEqual(argv[4:], ["--flow", "classic"])

    def test_a_staged_flow_refuses_a_tier_instead_of_ignoring_it(self) -> None:
        # Accepting it and dropping it would read as honoured by whoever asked.
        problem, _, spawned = self.run_start(flow="full", model="sonnet")

        self.assertIn("takes its models from its stages", problem)
        self.assertEqual(spawned, [])

    def test_a_missing_run_loop_script_is_refused_before_the_claim(self) -> None:
        # `bash` exists whatever happens, so spawning it at a script that is not
        # there returns a pid and reports success — the same false success as
        # `-m cuzam.runner --flow classic` exiting 2. Reachable in a real
        # install: the unpinned fallback is this package's own directory, which
        # holds no `hermes/` tree when the package was installed rather than
        # checked out.
        missing = self.repo / "gone" / "loop-runner" / "scripts" / "run-loop.sh"
        problem, calls, spawned = self.run_start(flow="classic", script=missing)

        self.assertIn("no run-loop.sh at", problem)
        self.assertIn("make install-runtime", problem)
        self.assertEqual(spawned, [], "nothing may be spawned at a script that is absent")
        for argv in calls:
            self.assertNotIn("claim", argv, "and nothing may be claimed for it either")

    def test_a_flow_no_longer_in_the_config_fails_before_the_claim(self) -> None:
        # The relaunch case: a task queued on a flow later deleted from
        # cuzam.yaml. Spawning it left the board claimed with a dead child.
        problem, calls, spawned = self.run_start(flow="tier3")

        self.assertIn("unknown flow", problem)
        self.assertEqual(spawned, [])
        for argv in calls:
            self.assertNotIn("claim", argv)


if __name__ == "__main__":
    unittest.main()


class ClaimReleaseTest(unittest.TestCase):
    """A failure after the claim must not leave the board saying "running"."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_failed_worktree_releases_the_claim(self) -> None:
        # Without this, one failed launch refuses every later launch for the
        # whole TTL (active_runs counts "running"), and the dead-but-claimed
        # task is exactly what makes a run unrelaunchable.
        board: list[list[str]] = []

        def fake_run(argv, **kwargs):
            if argv[:2] == ["hermes", "kanban"]:
                board.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "", "")
            # git worktree add against a directory that is not a repo
            return subprocess.CompletedProcess(argv, 128, "", "not a git repository")

        with mock.patch.object(launch.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(launch.subprocess, "Popen") as popen:
            problem = launch.start_flow(str(self.repo), "feat/x", "t_abc", "XARI-1", "full")

        self.assertIn("could not create the worktree", problem)
        popen.assert_not_called()
        self.assertTrue(
            any(argv[:3] == ["hermes", "kanban", "reclaim"] for argv in board),
            "the claim must be released before reporting the failure",
        )


class FlowIsRunningTest(unittest.TestCase):
    """Alive and dead have to be told apart by something that cannot lie."""

    @contextlib.contextmanager
    def listing(self, text: str):
        """A fake process list, plus a record of how it was asked for.

        Lines carry a pid, because the snapshot does: `ps -eo pid=,command=`.
        The pid is what the contract test compares the two implementations on,
        and what a surface shows so a run can be found without one.

        Both halves matter. `pgrep -f` matches the command line of whatever
        runs the search, so the search reports itself — which is why the
        calls are recorded and asserted on, not just their result: an
        implementation that went back to pgrep would return "no match" here
        and quietly pass every assertion below.
        """
        from cuzam import runs

        calls: list[list[str]] = []

        def fake(argv, *args, **kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, text, "")

        with mock.patch.object(runs.subprocess, "run", side_effect=fake):
            yield calls

    def test_a_shell_mentioning_the_task_is_not_a_live_flow(self) -> None:
        # This asked `pgrep -f` until 2026-09-24, so any command line
        # carrying the task id counted — including the search itself.
        # `stalled_runs` then found nothing stalled and `relaunch` refused to
        # restart a run that had already died.
        with self.listing(
            "  101 /bin/zsh -c pgrep -f 'cuzam.runner --task-id t_aaa111'\n"
        ) as calls:
            self.assertFalse(launch.flow_is_running("t_aaa111"))

        self.assertEqual(calls, [["ps", "-eo", "pid=,command="]])

    def test_a_real_runner_is_a_live_flow(self) -> None:
        with self.listing(
            "  102 /x/.venv/bin/python3 -m cuzam.runner --task-id t_aaa111 "
            "--issue XARI-1 --flow full\n"
        ) as calls:
            self.assertTrue(launch.flow_is_running("t_aaa111"))

        self.assertTrue(
            all("pgrep" not in argv[0] for argv in calls),
            f"liveness was decided by a pattern search: {calls}",
        )

    def test_a_malformed_task_id_never_reaches_the_process_list(self) -> None:
        with self.listing("") as calls:
            self.assertFalse(launch.flow_is_running("; rm -rf /"))

        self.assertEqual(calls, [])


class RelaunchTest(unittest.TestCase):
    """A run that dies stays dead — so restarting it has to actually work."""

    def setUp(self) -> None:
        # Relaunch asks `gh` whether the branch already has a pull request. The
        # tests below are not about that question, and letting them ask it for
        # real makes their result depend on the machine's gh auth.
        patcher = mock.patch.object(launch, "open_pull_request", return_value="")
        self.no_pr = patcher.start()
        self.addCleanup(patcher.stop)

    def stalled(self, **kwargs):
        return mock.patch.object(launch, "stalled_runs", return_value=[kwargs])

    def test_it_refuses_to_restart_something_still_running(self) -> None:
        # The failure this exists to prevent: on 2026-09-10 a healthy run was
        # restarted from a surface that could not tell alive from dead.
        with mock.patch.object(launch, "stalled_runs", return_value=[]), \
             mock.patch.object(launch, "active_runs", return_value=["t_live01"]), \
             mock.patch.object(launch, "flow_is_running", return_value=True):
            outcome = launch.relaunch()

        self.assertFalse(outcome.ok)
        self.assertIn("still running", outcome.message)

    def test_nothing_at_all_is_a_different_answer(self) -> None:
        with mock.patch.object(launch, "stalled_runs", return_value=[]), \
             mock.patch.object(launch, "active_runs", return_value=[]):
            outcome = launch.relaunch()

        self.assertFalse(outcome.ok)
        self.assertIn("no run to relaunch", outcome.message)

    def test_several_stalled_runs_are_named_rather_than_guessed(self) -> None:
        # Same rule the approvals CLI follows: acting without an id is only
        # safe when there is exactly one thing it could mean.
        with mock.patch.object(launch, "stalled_runs", return_value=[
            {"task_id": "t_aaa111", "issue": "XARI-1", "status": "running"},
            {"task_id": "t_bbb222", "issue": "XARI-2", "status": "blocked"},
        ]):
            outcome = launch.relaunch()

        self.assertFalse(outcome.ok)
        self.assertIn("XARI-1", outcome.message)
        self.assertIn("XARI-2", outcome.message)

    def test_it_can_be_named_by_issue_key(self) -> None:
        # What you remember is the issue, not that it became t_2741d851.
        with self.stalled(task_id="t_aaa111", issue="XARI-123", status="running"), \
             mock.patch.object(launch, "_task_body", return_value={
                 "repo": "/tmp/r", "issue": "XARI-123",
                 "flow": "full", "branch": "xariprojects/xari-123"}), \
             mock.patch.object(launch, "start_flow", return_value="") as started, \
             mock.patch.object(launch.subprocess, "run") as board, \
             mock.patch.object(launch.events, "emit"):
            board.return_value = subprocess.CompletedProcess([], 0, "", "")
            outcome = launch.relaunch("xari-123")

        self.assertTrue(outcome.ok)
        started.assert_called_once()
        self.assertEqual(started.call_args.args[0], "/tmp/r")

    def test_it_reuses_the_existing_branch_and_worktree(self) -> None:
        # Resuming the flow, not the stage: anything preserve_work committed
        # is on that branch, and cutting a fresh one would orphan it.
        with self.stalled(task_id="t_aaa111", issue="XARI-9", status="running"), \
             mock.patch.object(launch, "_task_body", return_value={
                 "repo": "/tmp/r", "issue": "XARI-9",
                 "flow": "full", "branch": "xariprojects/xari-9"}), \
             mock.patch.object(launch, "start_flow", return_value="") as started, \
             mock.patch.object(launch.subprocess, "run") as board, \
             mock.patch.object(launch.events, "emit"):
            board.return_value = subprocess.CompletedProcess([], 0, "", "")
            launch.relaunch()

        self.assertEqual(started.call_args.args[1], "xariprojects/xari-9")

    def test_it_carries_the_model_tier_the_first_attempt_used(self) -> None:
        # Without this a classic run queued as `sonnet` came back on the Claude
        # default and nothing said so — a silent change of model mid-issue.
        with self.stalled(task_id="t_aaa111", issue="XARI-9", status="running"), \
             mock.patch.object(launch, "_task_body", return_value={
                 "repo": "/tmp/r", "issue": "XARI-9", "model": "sonnet",
                 "flow": "classic", "branch": "xariprojects/xari-9"}), \
             mock.patch.object(launch, "start_flow", return_value="") as started, \
             mock.patch.object(launch.subprocess, "run") as board, \
             mock.patch.object(launch.events, "emit"):
            board.return_value = subprocess.CompletedProcess([], 0, "", "")
            launch.relaunch()

        self.assertEqual(started.call_args.args[5], "sonnet")

    def test_it_refuses_when_the_branch_already_has_a_pull_request(self) -> None:
        # The loop opens its PR as its final act, so an open PR means the run
        # finished and died before reporting. The retired loop-runner skill made
        # this check as its step 2; nothing did after the agent went away, and a
        # relaunch would pay for the whole flow again and let a fresh `finish`
        # stage push over work that is already up.
        self.no_pr.return_value = "https://github.com/o/r/pull/7"
        with self.stalled(task_id="t_aaa111", issue="XARI-9", status="running"), \
             mock.patch.object(launch, "_task_body", return_value={
                 "repo": "/tmp/r", "issue": "XARI-9",
                 "flow": "classic", "branch": "xariprojects/xari-9"}), \
             mock.patch.object(launch, "start_flow") as started, \
             mock.patch.object(launch.subprocess, "run") as board:
            board.return_value = subprocess.CompletedProcess([], 0, "", "")
            outcome = launch.relaunch()

        self.assertFalse(outcome.ok)
        self.assertIn("https://github.com/o/r/pull/7", outcome.message)
        started.assert_not_called()
        # And the board is left exactly as it was: reclaiming or unblocking a
        # task whose work is done would move a card for no reason.
        for call in board.call_args_list:
            self.assertNotIn("reclaim", call.args[0])
            self.assertNotIn("unblock", call.args[0])

    def test_an_unanswerable_pr_check_lets_the_relaunch_proceed(self) -> None:
        # One-directional on purpose. `gh` missing, unauthenticated or offline
        # must not block a restart: refusing to relaunch on an unanswered
        # question is the worse of the two failures.
        with mock.patch.object(launch.subprocess, "run", side_effect=OSError("no gh")):
            self.assertEqual(launch.open_pull_request("/tmp/r", "xariprojects/xari-9"), "")

    def test_a_pr_check_that_prints_nothing_is_not_a_url(self) -> None:
        # `--jq '.[0].url'` prints an empty line when there are no pull
        # requests, and "null" when the field is absent. Neither is a PR, and
        # treating either as one would make every relaunch refuse.
        for output in ("", "\n", "null\n", "  \n"):
            with self.subTest(output=output), \
                 mock.patch.object(launch.subprocess, "run") as gh:
                gh.return_value = subprocess.CompletedProcess([], 0, output, "")
                self.assertEqual(launch.open_pull_request("/tmp/r", "b"), "")

    def test_an_unreadable_task_body_is_not_guessed_at(self) -> None:
        with self.stalled(task_id="t_aaa111", issue="XARI-9", status="running"), \
             mock.patch.object(launch, "_task_body", return_value={"issue": "XARI-9"}), \
             mock.patch.object(launch, "start_flow") as started:
            outcome = launch.relaunch()

        self.assertFalse(outcome.ok)
        self.assertIn("does not say what to run", outcome.message)
        started.assert_not_called()


class ClippedDescriptionTest(unittest.TestCase):
    def test_a_clipped_call_does_not_render_as_a_bare_tool_name(self) -> None:
        # The wide-call fallback keeps no values, so without a guard it fell
        # through to "Bash" and nothing else — the blank cheque again, this
        # time reintroduced by the fix's own safety net.
        wide = {f"key_{i}": "v" * 300 for i in range(400)}
        stored = json.loads(approvals.stored_input(wide))

        described = approvals.describe("Bash", stored)

        self.assertNotEqual(described, "Bash")
        self.assertIn("too large", described)
