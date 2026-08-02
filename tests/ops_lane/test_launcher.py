import json
import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.launcher import build_claude_argv, build_mcp_config, write_mcp_config


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.spool_dir = Path("/tmp/ops-spool")

    def test_mcp_config_registers_approve_server(self):
        cfg = build_mcp_config("/venv/bin/python", "5", self.spool_dir, 600)
        server = cfg["mcpServers"]["approve"]
        self.assertEqual(server["command"], "/venv/bin/python")
        self.assertEqual(server["args"], ["-m", "ristretto.ops_lane.approval_broker"])
        self.assertEqual(server["type"], "stdio")

    def test_mcp_config_env_block(self):
        cfg = build_mcp_config("/venv/bin/python", "5", self.spool_dir, 600)
        env = cfg["mcpServers"]["approve"]["env"]
        self.assertEqual(env["RISTRETTO_OPS_SESSION"], "5")
        self.assertEqual(env["RISTRETTO_OPS_SPOOL"], str(self.spool_dir))
        self.assertEqual(env["RISTRETTO_OPS_APPROVAL_TIMEOUT"], "600")

    def test_mcp_config_custom_broker_module(self):
        cfg = build_mcp_config("/venv/bin/python", "5", self.spool_dir, 600, broker_module="pkg.mod")
        self.assertEqual(cfg["mcpServers"]["approve"]["args"], ["-m", "pkg.mod"])

    def test_write_mcp_config(self):
        directory = Path(tempfile.mkdtemp())
        path = write_mcp_config(directory, "/venv/bin/python", "5", self.spool_dir, 600)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "approve-5.mcp.json")
        self.assertIn("approve", json.loads(path.read_text())["mcpServers"])

    def test_claude_argv_defaults(self):
        argv = build_claude_argv("fix the bug", Path("/tmp/approve.mcp.json"))
        self.assertEqual(
            argv,
            [
                "claude", "-p", "--output-format", "json",
                "--mcp-config", "/tmp/approve.mcp.json",
                "--permission-prompt-tool", "mcp__approve__ask",
                "fix the bug",
            ],
        )

    def test_claude_argv_with_resume(self):
        argv = build_claude_argv("fix the bug", Path("/tmp/a.mcp.json"), resume_session_id="sid-1")
        idx = argv.index("--resume")
        self.assertEqual(argv[idx + 1], "sid-1")

    def test_claude_argv_settings_path(self):
        argv = build_claude_argv(
            "fix the bug", Path("/tmp/a.mcp.json"), settings_path=Path("/etc/strict.json")
        )
        idx = argv.index("--settings")
        self.assertEqual(argv[idx + 1], "/etc/strict.json")

    def test_claude_argv_setting_sources_all_is_omitted(self):
        argv = build_claude_argv("fix the bug", Path("/tmp/a.mcp.json"), setting_sources="all")
        self.assertNotIn("--setting-sources", argv)

    def test_claude_argv_setting_sources_project_is_included(self):
        argv = build_claude_argv("fix the bug", Path("/tmp/a.mcp.json"), setting_sources="project")
        idx = argv.index("--setting-sources")
        self.assertEqual(argv[idx + 1], "project")

    def test_claude_argv_strict_mcp(self):
        argv = build_claude_argv("fix the bug", Path("/tmp/a.mcp.json"), strict_mcp=True)
        self.assertIn("--strict-mcp-config", argv)

    def test_claude_argv_strict_mcp_omitted_by_default(self):
        argv = build_claude_argv("fix the bug", Path("/tmp/a.mcp.json"))
        self.assertNotIn("--strict-mcp-config", argv)

    def test_claude_argv_custom_tool_and_bin(self):
        argv = build_claude_argv(
            "fix the bug", Path("/tmp/a.mcp.json"), tool="mcp__other__ask", claude_bin="/x/claude"
        )
        self.assertEqual(argv[0], "/x/claude")
        idx = argv.index("--permission-prompt-tool")
        self.assertEqual(argv[idx + 1], "mcp__other__ask")

    def test_claude_argv_prompt_is_last(self):
        argv = build_claude_argv("fix the bug", Path("/tmp/a.mcp.json"))
        self.assertEqual(argv[-1], "fix the bug")


if __name__ == "__main__":
    unittest.main()
