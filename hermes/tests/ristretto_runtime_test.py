"""A flow should not run the tree you are editing.

The skills are symlinks into the working checkout and the package is an
editable install, so the runtime was whatever you had open: a flow launched
mid-edit ran half-finished code from whichever branch was out. Twice on
2026-09-10 an experiment needed a `git checkout main` first for its result to
mean anything, and once a fix had to be held back because editing the file
would have swapped code under a live flow.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ristretto import runtime  # noqa: E402
from ristretto.dash import launch  # noqa: E402


class RuntimeResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.home = Path(holder.name)
        self.env = {"RISTRETTO_STATE_HOME": str(self.home)}

    def pin(self) -> Path:
        """Make a runtime that looks installed."""
        venv = self.home / "runtime" / ".venv" / "bin"
        venv.mkdir(parents=True)
        python = venv / "python"
        python.write_text("#!/bin/sh\n", encoding="utf-8")
        python.chmod(0o755)
        return python

    def test_without_a_runtime_it_falls_back_and_says_so(self) -> None:
        # Refusing would be stricter and wrong: an install that has not pinned
        # yet would lose the ability to dispatch at all. Visibly unpinned
        # beats silently unpinned.
        prefix, _, warning = runtime.flow_interpreter(self.env)

        self.assertEqual(prefix, [sys.executable])
        self.assertIn("development checkout", warning)
        self.assertIn("make install-runtime", warning)

    def test_a_pinned_runtime_is_used_without_a_warning(self) -> None:
        python = self.pin()

        # The stub cannot import anything, so runtime_python rejects it — that
        # is the point of finding 2. Patch it to stand for a working install.
        with mock.patch.object(runtime, "runtime_python", return_value=python):
            prefix, env, warning = runtime.flow_interpreter(self.env)

        self.assertEqual(prefix, [str(python), "-P"])
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(warning, "")

    def test_the_identity_says_it_is_unpinned(self) -> None:
        identity = runtime.runtime_identity(self.env)

        self.assertEqual(identity["pinned"], "no")
        self.assertIn("install-runtime", identity["reason"])

    def test_an_edited_runtime_reports_dirty(self) -> None:
        # A pinned checkout somebody edited is not pinned to anything. The
        # whole feature is that a run can state what ran it.
        root = self.home / "runtime"
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@e.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)
        (root / "x.py").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "base"], check=True)
        python = self.pin()
        (root / "x.py").write_text("edited\n", encoding="utf-8")

        with mock.patch.object(runtime, "runtime_python", return_value=python):
            identity = runtime.runtime_identity(self.env)

        self.assertEqual(identity["pinned"], "yes")
        self.assertEqual(identity["tree"], "dirty")


class LaunchUsesTheRuntimeTest(unittest.TestCase):
    """The launcher stays where you invoked it; the flow does not."""

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

    def spawn_with(self, interpreter: str, warning: str = "", env: dict | None = None):
        spawned: list[list[str]] = []
        real_run, real_popen = subprocess.run, subprocess.Popen

        def fake_run(argv, **kwargs):
            if argv[:2] == ["hermes", "kanban"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            return real_run(argv, **kwargs)

        def fake_popen(argv, **kwargs):
            if argv and argv[0] == "git":
                return real_popen(argv, **kwargs)
            spawned.append(list(argv))
            return mock.Mock(pid=1234)

        prefix = [interpreter] if warning else [interpreter, "-P"]
        with mock.patch.object(launch, "flow_interpreter",
                               return_value=(prefix, env or {"PATH": "/usr/bin"}, warning)), \
             mock.patch.object(launch.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(launch.subprocess, "Popen", side_effect=fake_popen):
            launch.start_flow(str(self.repo), "feat/x", "t_abc", "XARI-1", "tier1")
        return spawned

    def test_the_flow_runs_under_the_pinned_interpreter(self) -> None:
        spawned = self.spawn_with("/pinned/.venv/bin/python")

        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0][:3], ["/pinned/.venv/bin/python", "-P", "-m"])
        self.assertEqual(spawned[0][3], "ristretto.runner")

    def test_an_unpinned_launch_still_starts(self) -> None:
        # Losing the ability to dispatch would be a worse failure than a
        # clearly-labelled unpinned run.
        spawned = self.spawn_with(sys.executable, "not pinned")

        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0][0], sys.executable)
        self.assertNotIn("-P", spawned[0], "the dev checkout needs its own sys.path")


class UnpinningEnvironmentTest(unittest.TestCase):
    """A pinned interpreter that inherits PYTHONPATH is not pinned."""

    def test_the_env_that_would_undo_the_pin_is_stripped(self) -> None:
        # Not hypothetical: scripts/check.sh and run-loop.sh both export
        # PYTHONPATH, and `-P` does not cover it — measured 2026-09-20.
        env = runtime.pinned_env({
            "PYTHONPATH": "/somewhere/ristretto-ai",
            "VIRTUAL_ENV": "/somewhere/.venv",
            "PYTHONHOME": "/somewhere",
            "PATH": "/usr/bin",
        })

        for name in runtime.UNPINNING_ENV:
            self.assertNotIn(name, env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_the_pinned_interpreter_is_given_dash_P(self) -> None:
        # A flow's cwd is the worktree, and a worktree of *this* repository
        # contains a ristretto/ package — so without -P the pin was defeated
        # for precisely the repository where it matters most.
        home = Path(tempfile.mkdtemp())
        venv = home / "runtime" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        (venv / "python").chmod(0o755)

        with mock.patch.object(runtime, "runtime_python", return_value=venv / "python"):
            prefix, _, warning = runtime.flow_interpreter({"RISTRETTO_STATE_HOME": str(home)})

        self.assertIn("-P", prefix)
        self.assertEqual(warning, "")


class UnknownProvenanceTest(unittest.TestCase):
    def test_a_runtime_that_is_not_a_git_checkout_says_unknown(self) -> None:
        # git() returns "" for failure, timeout and empty alike, so without a
        # guard a copied or .git-less runtime reported {"tree": "clean"} with
        # no commit — the most misleading record this could produce.
        home = Path(tempfile.mkdtemp())
        venv = home / "runtime" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        (venv / "python").chmod(0o755)

        with mock.patch.object(runtime, "runtime_python", return_value=venv / "python"):
            identity = runtime.runtime_identity({"RISTRETTO_STATE_HOME": str(home)})

        self.assertEqual(identity["pinned"], "yes")
        self.assertEqual(identity["tree"], "unknown")
        self.assertNotIn("commit", identity)


if __name__ == "__main__":
    unittest.main()
