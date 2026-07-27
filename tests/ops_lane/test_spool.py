import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.spool import Spool


class SpoolTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.spool = Spool(self.dir)

    def test_request_roundtrip(self):
        self.spool.write_request("r1", {"tool_name": "Bash"})
        pending = self.spool.read_new_requests()
        self.assertEqual(pending, [("r1", {"tool_name": "Bash"})])

    def test_decided_request_not_pending(self):
        self.spool.write_request("r1", {"x": 1})
        self.spool.write_decision("r1", {"permissionDecision": "allow"})
        self.assertEqual(self.spool.read_new_requests(), [])

    def test_await_returns_decision(self):
        self.spool.write_request("r1", {"x": 1})
        self.spool.write_decision("r1", {"permissionDecision": "deny"})
        got = self.spool.await_decision("r1", timeout_s=1)
        self.assertEqual(got, {"permissionDecision": "deny"})

    def test_await_times_out_to_none(self):
        ticks = iter([0.0, 0.5, 1.5])
        got = self.spool.await_decision(
            "missing", timeout_s=1, poll_s=0.1, sleep=lambda _s: None, now=lambda: next(ticks)
        )
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
