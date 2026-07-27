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

    def test_naming_repo_launches_claude(self):
        spawned = []

        def spawn(argv, **kwargs):
            spawned.append((argv, kwargs))
            class P:  # minimal Popen stand-in
                pass
            return P()

        daemon, client, cfg = make_daemon(self.tmp, spawn)
        daemon.handle_message({"chat": {"id": 5}, "from": {"id": 7}, "text": "kaffecard"})
        self.assertEqual(len(spawned), 1)
        argv, kwargs = spawned[0]
        self.assertIn("--permission-prompt-tool", argv)
        self.assertEqual(kwargs["cwd"], str(self.tmp / "repo"))

    def test_pump_spool_renders_pending(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda *a, **k: None)
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "tool_input": {"command": "gcloud ..."}})
        daemon.pump_spool(chat_id=5)
        chat_id, text, buttons = client.sent[-1]
        self.assertEqual(chat_id, 5)
        self.assertIn("gcloud", text)
        self.assertEqual({b[1] for b in buttons}, {"a:req1", "d:req1"})

    def test_callback_writes_decision(self):
        daemon, client, cfg = make_daemon(self.tmp, lambda *a, **k: None)
        spool = Spool(cfg.spool_dir)
        spool.write_request("req1", {"tool_name": "Bash", "tool_input": {"command": "x"}})
        daemon.handle_callback({"id": "cb", "from": {"id": 7}, "data": "a:req1", "message": {"chat": {"id": 5}}})
        decision = spool.await_decision("req1", timeout_s=1)
        self.assertEqual(decision["permissionDecision"], "allow")


if __name__ == "__main__":
    unittest.main()
