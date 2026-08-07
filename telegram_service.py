"""
telegram_service.py
Atlas Telegram Runtime Service (Webhook - Polling)

Hem webhook HTTP sunucusunu hem de getUpdates polling dongusunu tek bir
service altinda yonetir. Engine.analyze() ciktilari TelegramBot.send ile
dogrudan gonderilirken, kullanici giris/buton mesajlari buradan islenir.
"""

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import Config

LOGGER = logging.getLogger("atlas.telegram.service")


class TelegramService:
    """Polling ve webhook akisini birlikte barindiran runtime servisi."""

    def __init__(self, telegram_bot=None, auth_service=None, webhook_handler=None):
        Config.refresh_from_env()
        self.telegram_bot = telegram_bot
        self.auth_service = auth_service
        self.webhook_handler = webhook_handler
        self.stop_flag = threading.Event()
        self._offsets = {}
        self.logger = LOGGER

    # ---------------- Polling ----------------
    def _build_url(self, method):
        token = str(getattr(Config, "TELEGRAM_BOT_TOKEN", "")).strip()
        return f"https://api.telegram.org/bot{token}/{method}"

    def get_updates(self, offset=None):
        import requests
        url = self._build_url("getUpdates")
        params = {"timeout": 10}
        if offset is not None:
            params["offset"] = offset
        response = requests.get(url, params=params, timeout=12)
        return response.json()

    def send_message(self, chat_id, text):
        import requests
        try:
            requests.post(
                self._build_url("sendMessage"),
                data={"chat_id": chat_id, "text": text},
                timeout=10,
            )
        except Exception as exc:
            self.logger.exception("Telegram send_message hatasi: %s", exc)

    def _process_update(self, update):
        message = update.get("message")
        if not message:
            return
        text = message.get("text")
        if text is None:
            return
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        username = sender.get("username") or sender.get("first_name")

        if self.auth_service is not None:
            reply = self.auth_service.process_message(chat_id, username, text)
            if reply:
                self.send_message(chat_id, reply)

    def poll_once(self):
        offset = getattr(self, "_offset", None)
        try:
            updates = self.get_updates(offset)
        except Exception as exc:
            self.logger.exception("getUpdates hatasi: %s", exc)
            return
        if not updates.get("ok"):
            return
        for update in updates.get("result", []):
            self._offset = update["update_id"] + 1
            try:
                self._process_update(update)
            except Exception as exc:
                self.logger.exception("update isleme hatasi: %s", exc)

    def run_polling(self):
        interval = float(getattr(Config, "TELEGRAM_POLLING_INTERVAL_SECONDS", "2"))
        self.logger.info("Telegram polling basladi (interval=%ss)", interval)
        while not self.stop_flag.is_set():
            try:
                self.poll_once()
            except Exception:
                self.logger.exception("poll dongu hatasi")
            self.stop_flag.wait(interval)

    # ------------------------------------------------------------------- webhook
    def run_webhook(self):
        host = str(getattr(Config, "TELEGRAM_WEBHOOK_HOST", "0.0.0.0"))
        port = int(getattr(Config, "TELEGRAM_WEBHOOK_PORT", "8080"))
        handler = self._make_handler()
        server = ThreadingHTTPServer((host, port), handler)
        self.logger.info("Telegram webhook basladi: %s:%s", host, port)
        server.serve_forever()

    def _make_handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    data = json.loads(body.decode("utf-8"))
                except Exception:
                    data = None
                ok = False
                if data is not None:
                    if service.webhook_handler is not None:
                        ok = service.webhook_handler.handle_update(data)
                    else:
                        service._process_update(data)
                        ok = True
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok" if ok else "error"}).encode("utf-8"))

            def log_message(self, *args):
                pass

        return Handler

    # --------------------------- lifecycle
    def start(self, daemon=True):
        """Polling ve/veya webhook servisini background thread'lerde baslatir."""
        threads = []
        if bool(getattr(Config, "TELEGRAM_POLLING_ENABLED", True)):
            thread = threading.Thread(target=self.run_polling, daemon=daemon)
            thread.start()
            threads.append(thread)
        if bool(getattr(Config, "TELEGRAM_WEBHOOK_ENABLED", False)):
            thread = threading.Thread(target=self.run_webhook, daemon=daemon)
            thread.start()
            threads.append(thread)
        return threads

    def stop(self):
        self.stop_flag.set()