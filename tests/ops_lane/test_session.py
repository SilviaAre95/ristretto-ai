import json
import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.session import Session, SessionStore


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_get_missing_is_none(self):
        store = SessionStore()
        self.assertIsNone(store.get(1))

    def test_ensure_creates_fresh_session(self):
        store = SessionStore()
        session = store.ensure(1)
        self.assertIsInstance(session, Session)
        self.assertIsNone(session.claude_session_id)
        self.assertIs(store.ensure(1), session)  # same object on repeat calls

    def test_set_claude_id(self):
        store = SessionStore()
        store.ensure(1)
        store.set_claude_id(1, "abc")
        self.assertEqual(store.get(1).claude_session_id, "abc")

    def test_clear(self):
        store = SessionStore()
        store.set_claude_id(1, "abc")
        store.clear(1)
        self.assertIsNone(store.get(1))

    def test_active_chats(self):
        store = SessionStore()
        store.ensure(1)
        store.ensure(2)
        self.assertEqual(set(store.active_chats()), {1, 2})

    def test_no_path_does_not_persist(self):
        store = SessionStore()
        store.set_claude_id(1, "abc")  # must not raise without a path

    def test_persists_to_path_as_json(self):
        path = self.tmp / "sessions.json"
        store = SessionStore(path)
        store.set_claude_id(1, "abc")
        store.set_claude_id(2, "def")
        data = json.loads(path.read_text())
        self.assertEqual(data, {"1": "abc", "2": "def"})

    def test_reloads_from_path_on_construction(self):
        path = self.tmp / "sessions.json"
        store = SessionStore(path)
        store.set_claude_id(5, "sid-5")
        reloaded = SessionStore(path)
        self.assertEqual(reloaded.get(5).claude_session_id, "sid-5")

    def test_clear_persists(self):
        path = self.tmp / "sessions.json"
        store = SessionStore(path)
        store.set_claude_id(1, "abc")
        store.clear(1)
        reloaded = SessionStore(path)
        self.assertIsNone(reloaded.get(1))

    def test_load_tolerates_missing_or_bad_file(self):
        path = self.tmp / "missing.json"
        store = SessionStore(path)  # file doesn't exist yet; must not raise
        self.assertIsNone(store.get(1))
        path.write_text("not json")
        store.load()  # must not raise, leaves state as-is on bad data


if __name__ == "__main__":
    unittest.main()
