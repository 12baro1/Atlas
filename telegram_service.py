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
from manual_trade_service import ManualTradeService

LOGGER = logging.getLogger("atlas.telegram.service")


class TelegramService:
    """Polling ve webhook akisini birlikte barindiran runtime servisi."""

    def __init__(self, telegram_bot=None, auth_service=None, webhook_handler=None, trade_command_handler=None, manual_trade_service=None):
        Config.refresh_from_env()
        self.telegram_bot = telegram_bot
        self.auth_service = auth_service
        self.webhook_handler = webhook_handler
        self.trade_command_handler = trade_command_handler or TelegramTradeCommandHandler(manual_trade_service=manual_trade_service)
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
        callback_query = update.get("callback_query")
        if callback_query:
            self._process_callback_query(callback_query)
            return

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

    def _process_callback_query(self, callback_query):
        callback_data = callback_query.get("data")
        callback_id = callback_query.get("id")
        chat_id = (callback_query.get("message") or {}).get("chat", {}).get("id")

        if not callback_data:
            return

        if self.trade_command_handler is None or not self.trade_command_handler.enabled():
            self._answer_callback_query(callback_id, "Manual trade komutlari kapali.")
            return

        reply = self.trade_command_handler.handle_callback(callback_data)
        if callback_id:
            self._answer_callback_query(callback_id, (reply or "Islem alindi")[:180])
        if chat_id and reply:
            self.send_message(chat_id, reply)

    def _answer_callback_query(self, callback_query_id, text):
        if not callback_query_id:
            return
        try:
            import requests

            requests.post(
                self._build_url("answerCallbackQuery"),
                data={"callback_query_id": callback_query_id, "text": text},
                timeout=10,
            )
        except Exception:
            self.logger.exception("answerCallbackQuery hatasi")

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
                        try:
                            ok = bool(service.webhook_handler.handle_update(data))
                        except Exception:
                            service.logger.exception("webhook_handler hatasi")
                            ok = False
                    if not ok:
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

    def __init__(self, journal=None, manual_trade_service=None):
        self.manual_service = manual_trade_service
        if self.manual_service is None and journal is not None:
            self.manual_service = ManualTradeService(journal)
        self.journal = journal or (self.manual_service.journal if self.manual_service is not None else None)
        if self.manual_service is None and self.journal is not None:
            self.manual_service = ManualTradeService(self.journal)

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
        if normalized == "skip":
            return self._skip(parts)
        if normalized == "tp":
            return self._close_with_result(parts, "TP")
        if normalized == "sl":
            return self._close_with_result(parts, "SL")
        if normalized == "early":
            return self._close_with_result(parts, "EARLY_EXIT")
        if normalized == "close":
            return self._close(parts)
        if normalized == "status":
            return self._status()
        if normalized == "performance":
            return self._performance()
        return self._help()

    def handle_callback(self, callback_data):
        parts = str(callback_data or "").split("|")
        if not parts:
            return "Gecersiz callback"
        action = parts[0].replace("trade_", "")
        signal_id = None
        symbol = None
        direction = None

        if len(parts) >= 4 and parts[1].startswith("ATL-"):
            signal_id = parts[1]
            symbol = parts[2]
            direction = parts[3]
        elif len(parts) >= 3:
            symbol = parts[1]
            direction = parts[2]

        if signal_id is None and self.manual_service is not None:
            signal_id = self.manual_service.resolve_signal_id(symbol=symbol, direction=direction)
        if signal_id is None:
            return "Signal ID bulunamadi"

        if action == "entered":
            _manual, code = self.manual_service.open_trade(signal_id=signal_id)
            if code == "opened":
                return f"Islem acildi: {signal_id}"
            if code == "already_open":
                return f"Islem zaten kayitli: {signal_id}"
            return f"Islem acilamadi: {code}"
        if action == "skipped":
            _manual, code = self.manual_service.mark_not_traded(signal_id=signal_id)
            if code == "not_traded":
                return f"NOT_TRADED kaydi alindi: {signal_id}"
            if code == "already_open":
                return f"Bu sinyal zaten kayitli: {signal_id}"
            return f"NOT_TRADED kaydedilemedi: {code}"
        if action == "tp":
            _manual, code = self.manual_service.close_trade(signal_id=signal_id, result="TP")
            if code == "closed":
                return f"TP kaydedildi: {signal_id}"
            return f"TP kaydedilemedi: {code}"
        if action == "sl":
            _manual, code = self.manual_service.close_trade(signal_id=signal_id, result="SL")
            if code == "closed":
                return f"SL kaydedildi: {signal_id}"
            return f"SL kaydedilemedi: {code}"
        if action == "exit_early":
            _manual, code = self.manual_service.close_trade(signal_id=signal_id, result="EARLY_EXIT")
            if code == "closed":
                return f"EARLY_EXIT kaydedildi: {signal_id}"
            return f"EARLY_EXIT kaydedilemedi: {code}"
        return "Bilinmeyen callback aksiyonu"

    def _help(self):
        lines = [
            "🧰 /trade komutları",
            "/trade open <signal_id> [entry] [stop] [tp]",
            "/trade skip <signal_id>",
            "/trade tp <signal_id> [exit]",
            "/trade sl <signal_id> [exit]",
            "/trade early <signal_id> [exit]",
            "/trade close <signal_id> [exit] [WIN|LOSS|BREAKEVEN]",
            "/trade status",
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
        manual, code = self.manual_service.open_trade(
            signal_id=signal_id,
            actual_entry=entry,
            actual_stop=stop,
            actual_tp=tp,
        )
        if code == "signal_not_found":
            return "❌ Sinyal bulunamadı. Önce canlı bir sinyal üretilmeli."
        if code == "already_open":
            return "ℹ Bu sinyale ait işlem zaten açık."
        if code != "opened":
            return f"❌ İşlem açılamadı: {code}"
        lines = [
            "✅ İşlem kaydedildi (manuel)",
            f"Sinyal: {manual.get('signal_id')}",
            f"{manual.get('symbol')} {manual.get('side')}",
            f"Entry: {self._fmt(manual.get('entry'))}  SL: {self._fmt(manual.get('stop_loss'))}",
        ]
        return "\n".join(lines)

    def _skip(self, parts):
        if len(parts) < 3:
            return "ℹ Kullanim: /trade skip <signal_id>"
        signal_id = parts[2]
        _manual, code = self.manual_service.mark_not_traded(signal_id=signal_id)
        if code == "not_traded":
            return "✅ NOT_TRADED kaydedildi"
        if code == "already_open":
            return "ℹ Bu sinyal zaten kayitli"
        if code == "signal_not_found":
            return "❌ Sinyal bulunamadi"
        return f"❌ NOT_TRADED kaydedilemedi: {code}"

    def _close_with_result(self, parts, result):
        if len(parts) < 3:
            return f"ℹ Kullanim: /trade {result.lower()} <signal_id> [exit]"
        signal_id = parts[2]
        exit_price = self._num(parts[3]) if len(parts) > 3 else None
        manual, code = self.manual_service.close_trade(signal_id=signal_id, result=result, actual_exit=exit_price)
        if code == "closed":
            return (
                f"✅ İşlem kapatıldı\n"
                f"{manual.get('symbol')} {manual.get('side')} | {manual.get('result')} | {self._fmt(manual.get('pnl_rr'))}R"
            )
        if code == "already_closed":
            return "ℹ️ İşlem zaten kapanmış."
        if code == "manual_not_found":
            return "❌ Açık işlem bulunamadı."
        return f"❌ İşlem kapatılamadı: {code}"

    def _close(self, parts):
        if len(parts) < 3:
            return "ℹ Kullanım: /trade close <signal_id> [exit] [WIN|LOSS|BREAKEVEN]"
        signal_id = parts[2]
        exit_price = self._num(parts[3]) if len(parts) > 3 else None
        result = parts[4].upper() if len(parts) > 4 else None
        manual, code = self.manual_service.close_trade(
            signal_id=signal_id,
            actual_exit=exit_price,
            result=result,
        )
        if code == "manual_not_found":
            return "❌ Açık işlem bulunamadı."
        if code == "already_closed":
            return "ℹ️ İşlem zaten kapanmış."
        if code != "closed":
            return f"❌ İşlem kapatılamadı: {code}"
        return (
            f"✅ İşlem kapatıldı\n"
            f"{manual.get('symbol')} {manual.get('side')} | {manual.get('result')} | {self._fmt(manual.get('pnl_rr'))}R"
        )

    def _status(self):
        open_trades = self.journal.open_manual_trades()
        not_traded = self.journal.not_traded_manual_trades()
        lines = [
            "📌 MANUAL TRADE STATUS",
            f"Open: {len(open_trades)}",
            f"Not traded: {len(not_traded)}",
        ]
        for item in open_trades[:5]:
            lines.append(f"- {item.get('signal_id')} {item.get('symbol')} {item.get('side')} OPEN")
        return "\n".join(lines)

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
