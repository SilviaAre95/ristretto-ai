import io
import json
import unittest
from urllib.error import HTTPError

from ristretto.ops_lane.telegram_api import TelegramClient


class FakeUrlopen:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append((request.full_url, request.data, timeout))
        body = self.responses.pop(0)
        return io.BytesIO(json.dumps(body).encode())


class TelegramClientTest(unittest.TestCase):
    def test_get_updates_parses_result(self):
        fake = FakeUrlopen([{"ok": True, "result": [{"update_id": 5}]}])
        client = TelegramClient("TOKEN", urlopen=fake)
        updates = client.get_updates(offset=None, timeout_s=1)
        self.assertEqual(updates, [{"update_id": 5}])
        self.assertIn("/botTOKEN/getUpdates", fake.calls[0][0])

    def test_send_message_includes_inline_keyboard(self):
        fake = FakeUrlopen([{"ok": True, "result": {"message_id": 9}}])
        client = TelegramClient("TOKEN", urlopen=fake)
        client.send_message(42, "approve?", buttons=[("Approve", "a:1"), ("Deny", "d:1")])
        _, data, _ = fake.calls[0]
        payload = json.loads(data.decode())
        self.assertEqual(payload["chat_id"], 42)
        keyboard = payload["reply_markup"]["inline_keyboard"]
        self.assertEqual(keyboard[0][0], {"text": "Approve", "callback_data": "a:1"})

    def test_api_error_raises(self):
        fake = FakeUrlopen([{"ok": False, "description": "bad"}])
        client = TelegramClient("TOKEN", urlopen=fake)
        with self.assertRaises(RuntimeError):
            client.get_me()


if __name__ == "__main__":
    unittest.main()
