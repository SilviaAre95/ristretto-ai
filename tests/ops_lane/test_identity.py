import unittest

from ristretto.ops_lane.identity import allowed_user_ids, is_allowed


class IdentityTest(unittest.TestCase):
    def test_parse_csv(self):
        self.assertEqual(allowed_user_ids({"TELEGRAM_ALLOWED_USERS": "10, 20 ,30"}), {10, 20, 30})

    def test_missing_is_empty(self):
        self.assertEqual(allowed_user_ids({}), set())

    def test_non_numeric_entries_skipped(self):
        # An unfilled placeholder must not crash; it's simply not trusted.
        self.assertEqual(
            allowed_user_ids({"TELEGRAM_ALLOWED_USERS": "REPLACE_ME, 42"}), {42}
        )
        self.assertEqual(
            allowed_user_ids({"TELEGRAM_ALLOWED_USERS": "REPLACE_ME_WITH_YOUR_NUMERIC_ID"}),
            set(),
        )

    def test_empty_allowlist_denies_everyone(self):
        self.assertFalse(is_allowed(10, set()))

    def test_allows_listed_only(self):
        self.assertTrue(is_allowed(20, {10, 20}))
        self.assertFalse(is_allowed(99, {10, 20}))


if __name__ == "__main__":
    unittest.main()
