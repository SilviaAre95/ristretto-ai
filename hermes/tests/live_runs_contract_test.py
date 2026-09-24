#!/usr/bin/env python3
"""The contract between the two answers to "what is a live run".

`cuzam/runs.py` answers it for every Python surface. `scripts/live-runs.sh`
answers it for `install-runtime.sh` and `update.sh`, and stays standalone
deliberately: it is consulted while the Python environment is being rebuilt,
and a guard that imports the package to decide whether it may replace the
package is the circularity it exists to prevent.

Two implementations that cannot share code can still be pinned to each other,
which is what this does. Shaped after `seam_contract_test.py`, for the same
reason: a rename or a tightened pattern on one side is otherwise silent until
`make update` restarts the gateway over a live run.

Liveness keys on process *shape* — a foreground `run-loop.sh` and a detached
`cuzam.runner` — so two shapes cover three flows. The flows are nonetheless
asserted here **by name**, so that adding a fourth without thinking about this
file fails a test rather than quietly falling outside both implementations.
"""

from __future__ import annotations

import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cuzam import runs

REPO = Path(__file__).resolve().parents[2]
LIVE_RUNS = REPO / "scripts" / "live-runs.sh"

# Long enough to outlive the slowest assertion, short enough that a fixture
# leaked by a crashed test is gone before anyone notices it.
FIXTURE_SECONDS = 45


def spawn_staged(task_id: str, flow: str, module: str = "cuzam.runner") -> subprocess.Popen:
    """A process whose command line is a staged runner's.

    `exec -a` rather than a real runner: this is about what the process table
    says, and starting an actual flow would cut a worktree and spend money.
    """
    argv = f"python3 -m {module} --task-id {task_id} --issue ABC-1 --flow {flow}"
    return subprocess.Popen(["bash", "-c", f"exec -a '{argv}' sleep {FIXTURE_SECONDS}"])


def spawn_classic(directory: Path, task_id: str) -> subprocess.Popen:
    """A foreground run-loop.sh, matched by its pinned path."""
    script = directory / "loop-runner" / "scripts" / "run-loop.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f"#!/usr/bin/env bash\nsleep {FIXTURE_SECONDS}\n")
    script.chmod(0o755)
    return subprocess.Popen(
        ["bash", str(script), task_id, "ABC-1", "--flow", "classic"]
    )


def bash_pids() -> set[int]:
    """What `live-runs.sh` reports, as pids. Exit 1 means nothing is live."""
    result = subprocess.run(
        ["bash", str(LIVE_RUNS)], capture_output=True, text=True, check=False, timeout=60
    )
    found = set()
    for line in result.stdout.splitlines():
        head = line.strip().split(" ", 1)[0]
        if head.isdigit():
            found.add(int(head))
    return found


class LiveRunContractTest(unittest.TestCase):
    """Both implementations, one set of fixtures, the same verdict."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = TemporaryDirectory()
        directory = Path(cls.workspace.name)
        cls.processes: dict[str, subprocess.Popen] = {}

        # All three flows by name. `classic` and the two staged ones are only
        # two shapes, which is the point — but naming them individually is
        # what makes a fourth flow visible as a gap here.
        cls.processes["classic"] = spawn_classic(directory, "t_classic0")
        cls.processes["full"] = spawn_staged("t_full000", "full")
        cls.processes["short"] = spawn_staged("t_short00", "short")
        # A run that predates the rename still has to count: its command line
        # says `ristretto.runner` for its whole hour. Drop in 0.3.0.
        cls.processes["legacy"] = spawn_staged("t_legacy0", "full", "ristretto.runner")

        # The negatives. Both are processes that merely *mention* the runner,
        # which is the failure `pgrep -f` had: it matched the command line of
        # whatever ran the search.
        cls.processes["shell"] = subprocess.Popen(
            ["bash", "-c",
             "while :; do sleep 1; done # -m cuzam.runner --task-id t_shell00"]
        )
        # Not a shell, and it still is not a run: a `python -c` whose source
        # text names the module has "-m cuzam.runner --task-id" on its command
        # line. Both implementations were fooled by this until 2026-09-24,
        # when a run-visibility smoke test reported itself as a live run.
        cls.processes["mention"] = subprocess.Popen(
            ["bash", "-c",
             "exec -a 'python3 -c import_x -m cuzam.runner --task-id t_menti0' "
             f"sleep {FIXTURE_SECONDS}"]
        )
        # ps has to have caught up before either implementation is asked.
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls) -> None:
        for process in cls.processes.values():
            process.kill()
            process.wait()
        cls.workspace.cleanup()

    def setUp(self) -> None:
        self.bash = bash_pids()
        self.python = {process.pid for process in runs.live_processes()}

    def assert_agree(self, name: str, live: bool) -> None:
        pid = self.processes[name].pid
        self.assertEqual(
            pid in self.bash, live,
            f"live-runs.sh disagrees: {name} (pid {pid}) should be "
            f"{'live' if live else 'ignored'}",
        )
        self.assertEqual(
            pid in self.python, live,
            f"cuzam.runs disagrees: {name} (pid {pid}) should be "
            f"{'live' if live else 'ignored'}",
        )

    def test_a_classic_run_is_live_in_both(self) -> None:
        self.assert_agree("classic", True)

    def test_the_full_flow_is_live_in_both(self) -> None:
        self.assert_agree("full", True)

    def test_the_short_flow_is_live_in_both(self) -> None:
        self.assert_agree("short", True)

    def test_a_pre_rename_run_is_live_in_both(self) -> None:
        self.assert_agree("legacy", True)

    def test_a_shell_that_mentions_the_runner_is_ignored_by_both(self) -> None:
        self.assert_agree("shell", False)

    def test_a_python_that_mentions_the_runner_is_ignored_by_both(self) -> None:
        self.assert_agree("mention", False)

    def test_every_configured_flow_is_covered_by_a_fixture(self) -> None:
        """A fourth flow must not be able to fall outside this file.

        Reads the shipped configuration rather than a list written here, so
        adding a flow to cuzam.yaml and nothing else fails here.
        """
        from cuzam.config import load_config

        configured = set(load_config()[0].get("flows") or {})
        # `classic` is the loop-runner path and is not a configured flow entry.
        missing = configured - set(self.processes)
        self.assertEqual(
            missing, set(),
            f"flows with no contract fixture: {sorted(missing)}. "
            "Add one above, or this flow is invisible to one of the two "
            "implementations and nothing will say so.",
        )

    def test_the_python_side_reads_the_locators_off_the_command_line(self) -> None:
        """Agreement on *which* processes is not agreement on what they are.

        Only the Python side extracts a task id, a shape and a flow, so only
        it can be asserted here — but if it read them wrongly, every surface
        would point at the wrong run while both implementations still agreed
        on the pid set.
        """
        by_pid = {process.pid: process for process in runs.live_processes()}

        classic = by_pid[self.processes["classic"].pid]
        self.assertEqual(
            (classic.task_id, classic.shape, classic.flow),
            ("t_classic0", "classic", "classic"),
        )
        staged = by_pid[self.processes["full"].pid]
        self.assertEqual(
            (staged.task_id, staged.shape, staged.flow), ("t_full000", "staged", "full")
        )
        short = by_pid[self.processes["short"].pid]
        self.assertEqual(
            (short.task_id, short.shape, short.flow), ("t_short00", "staged", "short")
        )

    def test_running_flows_is_the_task_ids_of_those_processes(self) -> None:
        """The set every caller of `running_flows` actually consumes."""
        live = runs.running_flows()
        self.assertTrue({"t_classic0", "t_full000", "t_short00"} <= live)
        self.assertNotIn("t_shell00", live)
        self.assertNotIn("t_menti0", live)


if __name__ == "__main__":
    unittest.main()
