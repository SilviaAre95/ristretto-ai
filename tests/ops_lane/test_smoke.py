import unittest


class SmokeTest(unittest.TestCase):
    def test_package_imports(self):
        import ristretto.ops_lane  # noqa: F401

        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
