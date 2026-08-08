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

    def __init__(self, telegram_bot=None, auth_service=None, webhook_handler=None, trade_command_handler=None):
        Config.refresh_from_env()
        self.telegram_bot = telegram_bot
        self.auth_service = auth_service
        self.webhook_handler = webhook_handler
        self.trade_command_handler = trade_command_handler or TelegramTradeCommandHandler()
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
                return

        if text.strip().startswith("/trade"):
            if self.trade_command_handler is not None and self.trade_command_handler.enabled():
                reply = self.trade_command_handler.handle(chat_id, text)
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


class TelegramTradeCommandHandler:
    """/trade komutlarını trade_journal ile bağlar.

    Kullanım:
      /trade help                     → kullanım rehberi
      /trade open <signal_id> [entry] [stop] [tp]
      /trade close <signal_id> [exit] [WIN|LOSS|BREAKEVEN|MANUAL_CLOSE]
      /trade status                 -> açık + performans özeti
      /trade performance            -> sinyal + manuel istatistikler
    """

    def __init__(self, journal=None):
        self.journal = journal

    def enabled(self):
        return bool(getattr(Config, "MANUAL_TRADE_COMMAND_ENABLED", True))

    def handle(self, chat_id, text):
        parts = (text or "").split()
        if not parts:
            return None
        subcommand = parts[1] if len(parts) > 1 else "help"
        normalized = subcommand.lower()

        if self.journal is None:
            return "⚠️ Trade journal erişimi yok (signal tracking kapalı olabilir)."

        if normalized in ("help", ""):
            return self._help()
        if normalized == "open":
            return self._open(parts)
        if normalized == "close":
            return self._close(parts)
        if normalized == "performance":
            return self._performance()
        return self._help()

    def _help(self):
        lines = [
            "🧰 /trade komutları",
            "/trade open <signal_id> [entry] [stop] [tp]",
            "/trade close <signal_id> [exit] [WIN|LOSS|BREAKEVEN]",
            "/trade performance",
        ]
        return "\n".join(lines)

    def _open(self, parts):
        if len(parts) < 3:
            return "ℹ Kullanım: /trade open <signal_id> [entry] [stop] [tp]"
        signal_id = parts[2]
        entry = self._num(parts[3]) if len(parts) > 3 else None
        stop = self._num(parts[4]) if len(parts) > 4 else None
        tp = self._num(parts[5]) if len(parts) > 5 else None
        manual, code = self.journal.open_manual_trade(
            signal_id=signal_id,
            actual_entry=entry,
            actual_stop=stop,
            actual_tp=tp,
        )
        if code == "signal_not_found":
            return "❌ Sinyal bulunamadı. Önce canlı bir sinyal üretilmeli."
        if code == "already_open":
            return "ℹ Bu sinyale ait işlem zaten açık."
        lines = [
            "✅ İşlem kaydedildi (manuel)",
            f"Sinyal: {manual.get('signal_id')}",
            f"{manual.get('symbol')} {manual.get('side')}",
            f"Entry: {self._fmt(manual.get('entry'))}  SL: {self._fmt(manual.get('stop_loss'))}",
        ]
        return "\n".join(lines)

    def _close(self, parts):
        if len(parts) < 3:
            return "ℹ Kullanım: /trade close <signal_id> [exit] [WIN|LOSS|BREAKEVEN]"
        signal_id = parts[2]
        exit_price = self._num(parts[3]) if len(parts) > 3 else None
        result = parts[4].upper() if len(parts) > 4 else None
        manual, code = self.journal.close_manual_trade(
            signal_id=signal_id,
            actual_exit=exit_price,
            result=result,
        )
        if code == "manual_not_found":
            return "❌ Açık işlem bulunamadı."
        if code == "already_closed":
            return "ℹ️ İşlem zaten kapanmış."
        return (
            f"✅ İşlem kapatıldı\n"
            f"{manual.get('symbol')} {manual.get('side')} | {manual.get('result')} | {self._fmt(manual.get('pnl_rr'))}R"
        )

    def _performance(self):
        signal_perf = self.journal.signal_performance()
        manual_perf = self.journal.manual_trade_performance()
        lines = [
            "📊 ATLAS PERFORMANS",
            f"🎯 Sinyal | n={signal_perf.get('closed')} w={signal_perf.get('wins')} l={signal_perf.get('losses')} "
            f"| win%={signal_perf.get('winrate')} exp={signal_perf.get('expectancy')}R pf={signal_perf.get('profit_factor')}",
            f"🏦 Manuel | açık={manual_perf.get('open')} win%={manual_perf.get('winrate')} "
            f"exp={manual_perf.get('expectancy')}R pf={manual_perf.get('profit_factor')}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _fmt(value):
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    @staticmethod
    def _num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None