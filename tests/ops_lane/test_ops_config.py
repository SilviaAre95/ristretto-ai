import unittest
from pathlib import Path

from ristretto.ops_lane.config import load_ops_config


class OpsConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = load_ops_config({})
        self.assertEqual(cfg.approval_timeout_s, 600.0)
        self.assertEqual(cfg.spool_dir, Path("~/.hermes/ops-spool").expanduser())
        self.assertEqual(cfg.claude_bin, "claude")

    def test_overrides(self):
        cfg = load_ops_config(
            {"RISTRETTO_OPS_APPROVAL_TIMEOUT": "30", "RISTRETTO_OPS_CLAUDE_BIN": "/x/claude"}
        )
        self.assertEqual(cfg.approval_timeout_s, 30.0)
        self.assertEqual(cfg.claude_bin, "/x/claude")


if __name__ == "__main__":
    unittest.main()
