import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.approval_broker import build_permission_result, decide
from ristretto.ops_lane.spool import Spool


class ApprovalBrokerTest(unittest.TestCase):
    def setUp(self):
        self.spool = Spool(Path(tempfile.mkdtemp()))

    def test_permission_result_allow_shape(self):
        out = build_permission_result("allow", updated_input={"command": "ls"})
        self.assertEqual(out, {"behavior": "allow", "updatedInput": {"command": "ls"}})

    def test_permission_result_deny_shape(self):
        out = build_permission_result("deny", message="nope")
        self.assertEqual(out, {"behavior": "deny", "message": "nope"})

    def test_permission_result_deny_default_message(self):
        out = build_permission_result("deny")
        self.assertEqual(out, {"behavior": "deny", "message": "Denied."})

    def test_decide_relays_approval(self):
        payload = {
            "tool_use_id": "u1",
            "tool_name": "Bash",
            "input": {"command": "ls"},
            "session": "7",
        }
        self.spool.write_decision("u1", {"permissionDecision": "allow"})
        out = decide(payload, self.spool, timeout_s=1)
        self.assertEqual(out, {"behavior": "allow", "updatedInput": {"command": "ls"}})
        # The request must have been recorded for the daemon to render.
        self.assertTrue((self.spool.dir / "u1.request.json").exists())

    def test_decide_relays_denial(self):
        payload = {"tool_use_id": "u2", "tool_name": "Bash", "input": {"command": "ls"}, "session": "7"}
        self.spool.write_decision("u2", {"permissionDecision": "deny", "reason": "no thanks"})
        out = decide(payload, self.spool, timeout_s=1)
        self.assertEqual(out, {"behavior": "deny", "message": "no thanks"})

    def test_decide_times_out_to_deny(self):
        payload = {"tool_use_id": "u3", "tool_name": "Bash", "input": {"command": "ls"}, "session": "7"}
        out = decide(payload, self.spool, timeout_s=0)
        self.assertEqual(out["behavior"], "deny")
        self.assertIn("parked", out["message"].lower())


if __name__ == "__main__":
    unittest.main()
