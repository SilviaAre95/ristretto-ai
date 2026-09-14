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

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ristretto import approvals  # noqa: E402
from ristretto.dash import launch  # noqa: E402


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

    def run_start(self, claim_rc: int = 0):
        """Let git run for real; intercept only the board and the flow spawn.

        Patching Popen wholesale would break the real git calls too, since
        subprocess.run goes through it — so git is delegated back to the real
        one and only the runner spawn is caught.
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

        with mock.patch.object(launch.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(launch.subprocess, "Popen", side_effect=fake_popen):
            problem = launch.start_flow(str(self.repo), "feat/x", "t_abc", "XARI-1", "tier1")
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
        self.assertEqual(argv[:3], [sys.executable, "-m", "ristretto.runner"])
        self.assertIn("--task-id", argv)
        self.assertEqual(kwargs["cwd"], self.repo / launch.WORKTREE_DIR / "t_abc")
        self.assertTrue(kwargs["start_new_session"],
                        "the flow must outlive the CLI or Slack request that started it")


if __name__ == "__main__":
    unittest.main()
