import json
import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.launcher import build_claude_argv, build_mcp_config, write_mcp_config


class LauncherTest(unittest.TestCase):
    def test_mcp_config_registers_approve_server(self):
        cfg = build_mcp_config("/venv/bin/python")
        server = cfg["mcpServers"]["approve"]
        self.assertEqual(server["command"], "/venv/bin/python")
        self.assertEqual(server["args"], ["-m", "ristretto.ops_lane.approval_broker"])
        self.assertEqual(server["type"], "stdio")

    def test_write_mcp_config(self):
        directory = Path(tempfile.mkdtemp())
        path = write_mcp_config(directory, "/venv/bin/python")
        self.assertTrue(path.exists())
        self.assertIn("approve", json.loads(path.read_text())["mcpServers"])

    def test_claude_argv(self):
        argv = build_claude_argv("fix the bug", Path("/tmp/approve.mcp.json"))
        self.assertEqual(argv[0], "claude")
        self.assertIn("-p", argv)
        self.assertIn("--permission-prompt-tool", argv)
        self.assertIn("mcp__approve__ask", argv)
        self.assertIn("--mcp-config", argv)
        self.assertEqual(argv[-1], "fix the bug")


if __name__ == "__main__":
    unittest.main()
