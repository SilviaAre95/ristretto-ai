import unittest

from ristretto.ops_lane.session import SessionStore, resolve_repo


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.repos = {"HOMA OS": "/repos/homa", "kaffecard": "/repos/kaffecard"}

    def test_resolve_exact_name_case_insensitive(self):
        self.assertEqual(resolve_repo("homa os", self.repos), ("HOMA OS", "/repos/homa"))

    def test_resolve_unknown_is_none(self):
        self.assertIsNone(resolve_repo("nope", self.repos))

    def test_store_lifecycle(self):
        store = SessionStore()
        self.assertIsNone(store.get(1))
        session = store.start(1, "kaffecard", "/repos/kaffecard")
        self.assertEqual(session.repo, "kaffecard")
        self.assertEqual(store.get(1).path, "/repos/kaffecard")
        store.clear(1)
        self.assertIsNone(store.get(1))

    def test_active_chats(self):
        store = SessionStore()
        store.start(1, "kaffecard", "/repos/kaffecard")
        store.start(2, "HOMA OS", "/repos/homa")
        self.assertEqual(set(store.active_chats()), {1, 2})


if __name__ == "__main__":
    unittest.main()
