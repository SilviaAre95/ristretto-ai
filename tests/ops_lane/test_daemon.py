import tempfile
import unittest
from pathlib import Path

from ristretto.ops_lane.config import load_ops_config
from ristretto.ops_lane.daemon import OpsDaemon
from ristretto.ops_lane.spool import Spool


class FakeClient:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text, buttons))
        return {"message_id": len(self.sent)}

    def answer_callback(self, callback_query_id, text=""):
        self.sent.append(("ack", callback_query_id, text))


def make_daemon(tmp, spawn):
    cfg = load_ops_config({"RISTRETTO_OPS_SPOOL": str(tmp / "spool"), "RISTRETTO_OPS_AUDIT": str(tmp / "a.log")})
    client = FakeClient()
    daemon = OpsDaemon(
        client=client,
        repos={"kaffecard": str(tmp / "repo")},
        ops_config=cfg,
        allowed={7},
        spawn=spawn,
    )
    return daemon, client, cfg


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "repo").mkdir()

    def test_ignores_unlisted_user(self):
        spawned = []
        daemon, client, _ = make_daemon(self.tmp, lambda *a, **k: spawned.append(a))
        daemon.handle_message({"chat": {"id": 1}, "from": {"id": 999}, "text": "kaffecard"})
        self.assertEqual(spawned, [])
        self.assertEqual(client.sent, [])

    def test_first_message_must_name_known_repo(self):
        spawned = []
        daemon, client, _ = make_daemon(self.tmp, lambda *a, **k: spawned.append(a))
        daemon.handle_message({"chat": {"id": 5}, "from": {"id": 7}, "text": "nonsense"})
        self.assertEqual(spawned, [])
        self.assertIn("name a repo", client.sent[-1][1].lower())

    def test_naming_repo_pins_without_launch(self):
        spawned = []
        daemon, client, _ = make_daemon(self.tmp, lambda *a, **k: spawned.append(a))
        daemon.handle_message({"chat": {"id": 5}, "from": {"id": 7}, "text": "kaffecard"})
        self.assertEqual(spawned, [])  # naming does NOT launch
        self.assertIn("session pinned", client.sent[-1][1].lower())

    def test_task_after_naming_launches(self):
        spawned = []

        def spawn(argv, **kwargs):
            spawned.append((argv, kwargs))
            class P:
                pass
            return P()

        daemon, client, cfg = make_daemon(self.tmp, spawn)
        daemon.handle_message({"chat": {"id": 5}, "from": {"id": 7}, "text": "kaffecard"})   # pin
        daemon.handle_message({"chat": {"id": 5}, "from": {"id": 7}, "text": "fix the bug"})  # task
        self.assertEqual(len(spawned), 1)
        argv, kwargs = spawned[0]
        self.assertIn("--permission-prompt-tool", argv)
        self.assertEqual(kwargs["cwd"], str(self.tmp / "repo"))
        self.assertEqual(argv[-1], "fix the bug")  # the task text, not the repo name, is the prompt

    def test_pump_spool_renders_pending(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda *a, **k: None)
        daemon.sessions.start(5, "kaffecard", str(self.tmp / "repo"))
        spool = Spool(cfg.spool_dir)
        spool.write_request(
            "req1",
            {
                "tool_name": "Bash",
                "tool_input": {"command": "gcloud ..."},
                "cwd": str(self.tmp / "repo"),
            },
        )
        daemon.pump_spool()
        chat_id, text, buttons = client.sent[-1]
        self.assertEqual(chat_id, 5)
        self.assertIn("gcloud", text)
        self.assertEqual({b[1] for b in buttons}, {"a:req1", "d:req1"})

    def test_pump_spool_routes_to_owning_chat(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda *a, **k: None)
        (self.tmp / "a").mkdir()
        (self.tmp / "b").mkdir()
        daemon.sessions.start(100, "A", str(self.tmp / "a"))
        daemon.sessions.start(200, "B", str(self.tmp / "b"))
        spool = Spool(cfg.spool_dir)
        spool.write_request(
            "req1",
            {
                "tool_name": "Bash",
                "tool_input": {"command": "gcloud ..."},
                "cwd": str(self.tmp / "b"),
            },
        )
        daemon.pump_spool()
        self.assertTrue(client.sent)
        for chat_id, _text, _buttons in client.sent:
            self.assertEqual(chat_id, 200)

    def test_pump_spool_skips_unowned(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda *a, **k: None)
        spool = Spool(cfg.spool_dir)
        spool.write_request(
            "req1",
            {
                "tool_name": "Bash",
                "tool_input": {"command": "gcloud ..."},
                "cwd": str(self.tmp / "nowhere"),
            },
        )
        daemon.pump_spool()
        self.assertEqual(client.sent, [])

    def test_callback_writes_decision(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda *a, **k: None)
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "tool_input": {"command": "x"}})
        daemon.handle_callback({"id": "cb", "from": {"id": 7}, "data": "a:req1", "message": {"chat": {"id": 5}}})
        decision = spool.await_decision("req1", timeout_s=1)
        self.assertEqual(decision["permissionDecision"], "allow")

    def test_ignores_unlisted_callback(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda *a, **k: None)
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "tool_input": {"command": "x"}})
        daemon.handle_callback({"id": "cb", "from": {"id": 999}, "data": "a:req1", "message": {"chat": {"id": 5}}})
        self.assertEqual(client.sent, [])
        decision = spool.await_decision("req1", timeout_s=0.1)
        self.assertIsNone(decision)

    def test_malformed_callback_no_crash(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda *a, **k: None)
        spool = Spool(cfg.spool_dir)
        daemon.handle_callback({"id": "cb", "from": {"id": 7}, "data": "", "message": {"chat": {"id": 5}}})
        self.assertEqual(len(client.sent), 1)
        kind, callback_id, text = client.sent[-1]
        self.assertEqual(kind, "ack")
        self.assertEqual(text, "ignored")
        decision = spool.await_decision("req1", timeout_s=0.1)
        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
