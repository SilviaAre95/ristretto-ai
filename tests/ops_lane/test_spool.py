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

    def test_rejects_unsafe_request_id(self):
        for bad in ["../evil", "a/b", "..", "", "with\x00null"]:
            with self.assertRaises(ValueError):
                self.spool.write_request(bad, {"x": 1})

    def test_accepts_normal_id(self):
        self.spool.write_request("abc123DEF-_.", {"x": 1})
        self.assertEqual(self.spool.read_new_requests()[0][0], "abc123DEF-_.")

    def test_read_new_requests_skips_malformed(self):
        (self.spool.dir / "good.request.json").write_text('{"ok": true}')
        (self.spool.dir / "bad.request.json").write_text("{ this is not json")
        pending = dict(self.spool.read_new_requests())
        self.assertIn("good", pending)
        self.assertNotIn("bad", pending)


if __name__ == "__main__":
    unittest.main()
