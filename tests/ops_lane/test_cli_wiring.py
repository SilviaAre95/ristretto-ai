import unittest

from ristretto.ops_lane.cli import ops_daemon_check


class CliWiringTest(unittest.TestCase):
    def test_check_fails_without_token(self):
        code, msg = ops_daemon_check(environ={}, repos={"kaffecard": "/x"})
        self.assertEqual(code, 1)
        self.assertIn("TELEGRAM_BOT_TOKEN", msg)

    def test_check_fails_without_allowlist(self):
        code, msg = ops_daemon_check(environ={"TELEGRAM_BOT_TOKEN": "t"}, repos={"kaffecard": "/x"})
        self.assertEqual(code, 1)
        self.assertIn("TELEGRAM_ALLOWED_USERS", msg)

    def test_check_ok(self):
        env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ALLOWED_USERS": "7"}
        code, msg = ops_daemon_check(environ=env, repos={"kaffecard": "/x"})
        self.assertEqual(code, 0)
        self.assertIn("ready", msg.lower())


if __name__ == "__main__":
    unittest.main()
