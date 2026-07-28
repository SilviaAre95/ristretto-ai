import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.config import load_ops_config
from ristretto.ops_lane.daemon import OpsDaemon
from ristretto.ops_lane.spool import Spool


class FakeClient:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.acks = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text, buttons))
        return {"message_id": len(self.sent)}

    def answer_callback(self, callback_query_id, text=""):
        self.acks.append((callback_query_id, text))

    def edit_message_text(self, chat_id, message_id, text):
        self.edits.append((chat_id, message_id, text))


def make_daemon(tmp, run_claude, allowed={7, 100, 200}):
    root = tmp / "root"
    root.mkdir(exist_ok=True)
    cfg = load_ops_config({
        "RISTRETTO_OPS_SPOOL": str(tmp / "spool"),
        "RISTRETTO_OPS_AUDIT": str(tmp / "a.log"),
        "RISTRETTO_OPS_ROOT": str(root),
        "RISTRETTO_OPS_SESSIONS": str(tmp / "sessions.json"),
    })
    client = FakeClient()
    daemon = OpsDaemon(client, cfg, allowed, run_claude=run_claude, background=False)
    return daemon, client, cfg


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    # --- identity gating --------------------------------------------------

    def test_ignores_unlisted_user(self):
        calls = []
        daemon, client, _ = make_daemon(self.tmp, lambda argv, cwd: calls.append(argv))
        daemon.handle_message({"chat": {"id": 1}, "from": {"id": 999}, "text": "hi"})
        self.assertEqual(calls, [])
        self.assertEqual(client.sent, [])

    # --- built-in commands --------------------------------------------------

    def test_ls_lists_root_dirs(self):
        (self.tmp / "root" / "kaffecard").mkdir(parents=True)
        (self.tmp / "root" / "homa-os").mkdir(parents=True)
        daemon, client, _ = make_daemon(self.tmp, lambda argv, cwd: {})
        daemon.handle_message({"chat": {"id": 7}, "from": {"id": 7}, "text": "/ls"})
        chat_id, text, _buttons = client.sent[-1]
        self.assertEqual(chat_id, 7)
        self.assertIn("kaffecard", text)
        self.assertIn("homa-os", text)

    def test_new_clears_session_and_replies(self):
        daemon, client, _ = make_daemon(
            self.tmp, lambda argv, cwd: {"session_id": "sid1", "result": "r", "is_error": False}
        )
        daemon.handle_message({"chat": {"id": 7}, "from": {"id": 7}, "text": "hello"})
        self.assertEqual(daemon.sessions.get(7).claude_session_id, "sid1")
        daemon.handle_message({"chat": {"id": 7}, "from": {"id": 7}, "text": "/new"})
        self.assertIsNone(daemon.sessions.get(7))
        self.assertIn("fresh", client.sent[-1][1].lower())

    # --- conversational turns --------------------------------------------------

    def test_normal_message_runs_turn_relays_reply_and_persists_session(self):
        daemon, client, _ = make_daemon(
            self.tmp, lambda argv, cwd: {"session_id": "sid1", "result": "done", "is_error": False}
        )
        daemon.handle_message({"chat": {"id": 7}, "from": {"id": 7}, "text": "fix the bug"})
        chat_id, text, buttons = client.sent[-1]
        self.assertEqual(chat_id, 7)
        self.assertEqual(text, "done")
        self.assertIsNone(buttons)
        self.assertEqual(daemon.sessions.get(7).claude_session_id, "sid1")

    def test_second_turn_resumes_prior_session(self):
        captured = []
        results = iter([
            {"session_id": "sid1", "result": "r1", "is_error": False},
            {"session_id": "sid2", "result": "r2", "is_error": False},
        ])

        def run_claude(argv, cwd):
            captured.append(argv)
            return next(results)

        daemon, client, _ = make_daemon(self.tmp, run_claude)
        daemon.handle_message({"chat": {"id": 7}, "from": {"id": 7}, "text": "first"})
        self.assertEqual(daemon.sessions.get(7).claude_session_id, "sid1")
        self.assertNotIn("--resume", captured[0])

        daemon.handle_message({"chat": {"id": 7}, "from": {"id": 7}, "text": "second"})
        self.assertEqual(daemon.sessions.get(7).claude_session_id, "sid2")
        self.assertIn("--resume", captured[1])
        idx = captured[1].index("--resume")
        self.assertEqual(captured[1][idx + 1], "sid1")

    def test_run_claude_error_reports_to_chat(self):
        def boom(argv, cwd):
            raise FileNotFoundError("no claude binary")

        daemon, client, _ = make_daemon(self.tmp, boom)
        daemon.handle_message({"chat": {"id": 7}, "from": {"id": 7}, "text": "do it"})
        self.assertIn("couldn't run", client.sent[-1][1].lower())

    def test_is_error_reply_is_flagged(self):
        daemon, client, _ = make_daemon(
            self.tmp, lambda argv, cwd: {"session_id": "sid1", "result": "boom", "is_error": True}
        )
        daemon.handle_message({"chat": {"id": 7}, "from": {"id": 7}, "text": "do it"})
        self.assertIn("boom", client.sent[-1][1])
        self.assertTrue(client.sent[-1][1].startswith("⚠️"))

    # --- spool pumping --------------------------------------------------

    def test_pump_spool_routes_to_owning_chat(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "input": {"command": "ls -la"}, "session": "7"})
        daemon.pump_spool()
        self.assertEqual(len(client.sent), 1)
        chat_id, text, buttons = client.sent[-1]
        self.assertEqual(chat_id, 7)
        self.assertIn("ls -la", text)
        self.assertEqual({b[1] for b in buttons}, {"a:req1", "d:req1"})

    def test_pump_spool_does_not_cross_route_to_another_chat(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        spool = Spool(cfg.spool_dir)
        spool.write_request("req7", {"tool_name": "Bash", "input": {"command": "x"}, "session": "7"})
        spool.write_request("req100", {"tool_name": "Bash", "input": {"command": "y"}, "session": "100"})
        daemon.pump_spool()
        self.assertEqual({chat_id for chat_id, _t, _b in client.sent}, {7, 100})
        for chat_id, text, _buttons in client.sent:
            if chat_id == 7:
                self.assertIn("x", text)
            else:
                self.assertIn("y", text)

    def test_pump_spool_skips_unstamped_request(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "input": {"command": "x"}})
        daemon.pump_spool()
        self.assertEqual(client.sent, [])

    # --- callbacks --------------------------------------------------

    def test_callback_writes_allow_decision_for_owning_chat(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "input": {"command": "x"}, "session": "7"})
        daemon.handle_callback(
            {"id": "cb", "from": {"id": 7}, "data": "a:req1", "message": {"chat": {"id": 7}, "message_id": 1}}
        )
        decision = spool.await_decision("req1", timeout_s=1)
        self.assertEqual(decision["permissionDecision"], "allow")
        self.assertEqual(len(client.edits), 1)

    def test_callback_writes_deny_decision(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "input": {"command": "x"}, "session": "7"})
        daemon.handle_callback(
            {"id": "cb", "from": {"id": 7}, "data": "d:req1", "message": {"chat": {"id": 7}, "message_id": 1}}
        )
        decision = spool.await_decision("req1", timeout_s=1)
        self.assertEqual(decision["permissionDecision"], "deny")

    def test_callback_rejected_from_non_owner(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        spool = Spool(cfg.spool_dir)
        # Request is owned by chat 100's session.
        spool.write_request("reqA", {"tool_name": "Bash", "input": {"command": "x"}, "session": "100"})
        # Chat 200 (also an allowed identity) taps it.
        daemon.handle_callback(
            {"id": "cb", "from": {"id": 200}, "data": "a:reqA", "message": {"chat": {"id": 200}, "message_id": 1}}
        )
        self.assertIsNone(spool.await_decision("reqA", timeout_s=0))
        self.assertEqual(client.edits, [])

    def test_ignores_unlisted_callback(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "input": {"command": "x"}, "session": "7"})
        daemon.handle_callback(
            {"id": "cb", "from": {"id": 999}, "data": "a:req1", "message": {"chat": {"id": 7}, "message_id": 1}}
        )
        self.assertEqual(client.acks, [])
        self.assertIsNone(spool.await_decision("req1", timeout_s=0.1))

    def test_malformed_callback_data_does_not_raise(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        daemon.handle_callback({"id": "cb", "from": {"id": 7}, "data": "", "message": {"chat": {"id": 7}}})
        self.assertEqual(client.acks, [("cb", "ignored")])

    def test_empty_callback_dict_does_not_raise(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        daemon.handle_callback({})  # no from/data/message at all

    def test_callback_for_missing_request_does_not_raise(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda argv, cwd: {})
        daemon.handle_callback(
            {"id": "cb", "from": {"id": 7}, "data": "a:nosuchrequest", "message": {"chat": {"id": 7}, "message_id": 1}}
        )
        self.assertEqual(client.acks, [("cb", "expired")])


if __name__ == "__main__":
    unittest.main()
