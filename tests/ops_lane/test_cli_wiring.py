import os
import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.cli import _parse_env_file, ops_daemon_check


class CliWiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_check_fails_without_token(self):
        code, msg = ops_daemon_check({})
        self.assertEqual(code, 1)
        self.assertIn("TELEGRAM_BOT_TOKEN", msg)

    def test_check_fails_without_allowlist(self):
        code, msg = ops_daemon_check({"TELEGRAM_BOT_TOKEN": "t"})
        self.assertEqual(code, 1)
        self.assertIn("TELEGRAM_ALLOWED_USERS", msg)

    def test_check_fails_without_root_dir(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_ALLOWED_USERS": "7",
            "RISTRETTO_OPS_ROOT": str(self.tmp / "nowhere"),
        }
        code, msg = ops_daemon_check(env)
        self.assertEqual(code, 1)
        self.assertIn(str(self.tmp / "nowhere"), msg)

    def test_check_ok(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_ALLOWED_USERS": "7",
            "RISTRETTO_OPS_ROOT": str(self.tmp),
        }
        code, msg = ops_daemon_check(env)
        self.assertEqual(code, 0)
        self.assertIn("ready", msg.lower())
        self.assertIn(str(self.tmp), msg)


class ParseEnvFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._added_keys: list[str] = []

    def tearDown(self):
        for key in self._added_keys:
            os.environ.pop(key, None)

    def _load(self, contents: str) -> None:
        path = self.tmp / ".env"
        path.write_text(contents)
        _parse_env_file(path)

    def test_plain_assignment(self):
        self._added_keys.append("RIS_TEST_PLAIN")
        self._load("RIS_TEST_PLAIN=hello\n")
        self.assertEqual(os.environ["RIS_TEST_PLAIN"], "hello")

    def test_inline_comment_is_stripped(self):
        self._added_keys.append("RIS_TEST_COMMENT")
        self._load("RIS_TEST_COMMENT=hello # trailing comment\n")
        self.assertEqual(os.environ["RIS_TEST_COMMENT"], "hello")

    def test_full_line_comment_is_skipped(self):
        self._added_keys.append("RIS_TEST_UNSET")
        self._load("# RIS_TEST_UNSET=hello\n")
        self.assertNotIn("RIS_TEST_UNSET", os.environ)

    def test_double_quoted_value_keeps_hash(self):
        self._added_keys.append("RIS_TEST_DQUOTE")
        self._load('RIS_TEST_DQUOTE="hello # not a comment"\n')
        self.assertEqual(os.environ["RIS_TEST_DQUOTE"], "hello # not a comment")

    def test_single_quoted_value_keeps_hash(self):
        self._added_keys.append("RIS_TEST_SQUOTE")
        self._load("RIS_TEST_SQUOTE='hello # still not a comment'\n")
        self.assertEqual(os.environ["RIS_TEST_SQUOTE"], "hello # still not a comment")

    def test_existing_env_var_is_not_overridden(self):
        os.environ["RIS_TEST_EXISTING"] = "keep-me"
        self._added_keys.append("RIS_TEST_EXISTING")
        self._load("RIS_TEST_EXISTING=overwritten\n")
        self.assertEqual(os.environ["RIS_TEST_EXISTING"], "keep-me")

    def test_blank_and_malformed_lines_are_skipped(self):
        self._added_keys.append("RIS_TEST_AFTER_BLANK")
        self._load("\n   \nnoequalsatall\nRIS_TEST_AFTER_BLANK=ok\n")
        self.assertEqual(os.environ["RIS_TEST_AFTER_BLANK"], "ok")


if __name__ == "__main__":
    unittest.main()
