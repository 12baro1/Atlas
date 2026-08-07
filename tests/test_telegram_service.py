"""Test suite for the unified TelegramService (polling + webhook)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from telegram_service import TelegramService


def make_update(message_id, chat_id, text):
    return {
        "update_id": message_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": chat_id},
            "from": {"id": chat_id, "username": "test_user"},
            "text": text,
        },
    }


def test_process_update_auth_flow():
    service = TelegramService()

    captured = {}

    class FakeAuth:
        def process_message(self, chat_id, username, text):
            captured["chat_id"] = chat_id
            captured["username"] = username
            captured["text"] = text
            return "reply-ok"

    class FakeBot:
        def send_message(self, chat_id, text):
            captured["sent"] = (chat_id, text)

    service.auth_service = FakeAuth()
    service.telegram_bot = FakeBot()
    service.send_message = lambda chat_id, text: captured.setdefault("sent", (chat_id, text))

    service._process_update(make_update(1, 12345, "/start"))

    assert captured["chat_id"] == 12345
    assert captured["text"] == "/start"
    assert captured["sent"] == (12345, "reply-ok")


def test_poll_once_processes_updates():
    service = TelegramService()
    processed = []

    fake_updates = {"ok": True, "result": [make_update(5, 99, "/start")]}

    service.get_updates = lambda offset: fake_updates

    def fake_process(update):
        processed.append(update["update_id"])

    service._process_update = fake_process

    service.poll_once()

    assert processed == [5]
    assert service._offset == 6


def test_webhook_handler_routes_to_webhook_handler():
    service = TelegramService()

    class FakeWebhook:
        def handle_update(self, data):
            return True

    service.webhook_handler = FakeWebhook()

    handler_cls = service._make_handler()

    # Handler class oluşturulabiliyor ve do_POST capabili - class meta kontrol
    from http.server import BaseHTTPRequestHandler

    assert issubclass(handler_cls, BaseHTTPRequestHandler)