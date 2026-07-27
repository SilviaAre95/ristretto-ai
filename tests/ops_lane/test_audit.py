import json
import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.audit import audit


class AuditTest(unittest.TestCase):
    def test_appends_jsonl_with_ts(self):
        path = Path(tempfile.mkdtemp()) / "ops-audit.log"
        audit(path, {"event": "request", "tool": "Bash"}, now=lambda: 123.0)
        audit(path, {"event": "decision", "decision": "allow"}, now=lambda: 124.0)
        lines = path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["ts"], 123.0)
        self.assertEqual(first["event"], "request")


if __name__ == "__main__":
    unittest.main()
