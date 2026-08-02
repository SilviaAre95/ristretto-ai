import unittest
from ristretto.config import repositories


class RepositoriesTest(unittest.TestCase):
    def test_expands_user(self):
        result = repositories({"repositories": {"kaffecard": "~/code/kaffecard"}})
        self.assertFalse(result["kaffecard"].startswith("~"))
        self.assertTrue(result["kaffecard"].endswith("/code/kaffecard"))

    def test_empty(self):
        self.assertEqual(repositories({}), {})


if __name__ == "__main__":
    unittest.main()
