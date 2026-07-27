import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.approval_broker import build_hook_output, decide
from ristretto.ops_lane.spool import Spool


class ApprovalBrokerTest(unittest.TestCase):
    def setUp(self):
        self.spool = Spool(Path(tempfile.mkdtemp()))

    def test_hook_output_shape(self):
        out = build_hook_output("allow", "ok")
        self.assertEqual(
            out,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "ok",
                }
            },
        )

    def test_decide_relays_approval(self):
        payload = {"tool_use_id": "u1", "tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.spool.write_decision("u1", {"permissionDecision": "allow", "reason": "tapped"})
        out = decide(payload, self.spool, timeout_s=1)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "allow")
        # The request must have been recorded for the daemon to render.
        self.assertTrue((self.spool.dir / "u1.request.json").exists())

    def test_decide_times_out_to_deny(self):
        payload = {"tool_use_id": "u2", "tool_name": "Bash", "tool_input": {"command": "ls"}}
        out = decide(payload, self.spool, timeout_s=0)
        decision = out["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("parked", decision["permissionDecisionReason"].lower())


if __name__ == "__main__":
    unittest.main()
