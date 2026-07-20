"""Telegram mesaj formatlama ve gonderim modulu."""

import json
import logging
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config
from telegram_auth_store import TelegramAuthStore


LOGGER = logging.getLogger("atlas.telegram")


class TelegramEngine:
    @staticmethod
    def _fmt(value):
        if value is None:
            return "None"
        if isinstance(value, float):
            return f"{value:.8f}".rstrip("0").rstrip(".")
        return str(value)

    @staticmethod
    def _truncate(value, max_len):
        text = str(value)
        if max_len <= 3 or len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."

    def format_signal(self, result):
        symbol = result["symbol"]
        signal = result.get("signal") or {}
        entry = result.get("entry") or {}
        risk = result.get("risk") or {}
        rr = result.get("rr")
        dynamic_tp = result.get("dynamic_tp")
        confluence = result.get("confluence")
        market_phase = result.get("market_phase")
        unicorn = result.get("unicorn")
        cisd = result.get("cisd")
        decision = result.get("decision")

        msg = []
        msg.append("📊 ATLAS SMC SIGNAL")
        msg.append(f"🪙 Coin : {symbol}")
        msg.append("")

        msg.append(f"🟢 Signal : {signal.get('signal', 'WAIT')}")
        msg.append(f"⭐ Grade : {signal.get('grade', '-')}")
        msg.append(f"💪 Strength : {signal.get('strength', '-')}")
        msg.append(f"🎯 Confidence : {signal.get('confidence', 0)}%")
        msg.append("")

        if market_phase:
            msg.append("📈 MARKET PHASE")
            msg.append(f"Phase : {market_phase.get('phase', 'Unknown')}")
            msg.append(f"Phase Quality : {market_phase.get('phase_confidence', 0)}%")
            msg.append(f"MTF Alignment : {market_phase.get('mtf_alignment', 0)}%")
            msg.append("")

        if confluence:
            msg.append("✅ SMC CHECKS")
            checks = confluence.get("checks", [])
            compact_mode = bool(getattr(Config, "TELEGRAM_COMPACT_MODE", True))

            if compact_mode:
                passed = [item for item in checks if isinstance(item, str) and item.startswith("✔")]
                partial = [item for item in checks if isinstance(item, str) and item.startswith("◐")]
                failed = [item for item in checks if isinstance(item, str) and item.startswith("✘")]

                msg.append(f"Passed: {len(passed)} | Partial: {len(partial)} | Failed: {len(failed)}")
                for item in partial[:2]:
                    msg.append(item)
                for item in failed[:4]:
                    msg.append(item)
            else:
                for item in checks:
                    msg.append(item)

            msg.append("")

        msg.append("📍 ENTRY")
        msg.append(f"Direction : {entry.get('direction', 'WAIT')}")
        msg.append(f"Valid : {entry.get('valid', False)}")

        entry_is_valid = bool(entry.get("valid"))
        if entry_is_valid and entry.get("entry") is not None and entry.get("stop_loss") is not None:
            msg.append(f"Entry : {self._fmt(entry.get('entry'))}")
            msg.append(f"Stop Loss : {self._fmt(entry.get('stop_loss'))}")
        elif not entry_is_valid:
            msg.append("Entry levels : withheld (invalid entry)")

        msg.append("")

        if entry_is_valid and risk and risk.get("risk") is not None:
            display_rr = risk.get("selected_rr")
            if display_rr is None:
                display_rr = risk.get("rr")

            msg.append("💰 RISK")
            msg.append(f"Capital At Risk : {self._fmt(risk.get('capital_at_risk'))} USDT")
            msg.append(f"Position Size : {self._fmt(risk.get('position_size'))}")
            msg.append(f"Risk : {self._fmt(risk.get('risk'))}")
            msg.append("")
            msg.append(f"TP1 : {self._fmt(risk.get('tp1'))}")
            msg.append(f"TP2 : {self._fmt(risk.get('tp2'))}")
            msg.append(f"TP3 : {self._fmt(risk.get('tp3'))}")
            msg.append(f"RR1 : {self._fmt(risk.get('rr1'))}")
            msg.append(f"RR2 : {self._fmt(risk.get('rr2'))}")
            msg.append(f"RR3 : {self._fmt(risk.get('rr3'))}")
            msg.append(f"Selected TP : {self._fmt(risk.get('selected_tp'))}")
            msg.append(f"Selected RR : {self._fmt(display_rr)}")
            msg.append(f"RR : {self._fmt(display_rr)}")
            msg.append("")
        elif entry_is_valid and dynamic_tp:
            msg.append("🎯 TARGETS")
            msg.append(f"TP1 : {self._fmt(dynamic_tp.get('tp1'))}")
            msg.append(f"TP2 : {self._fmt(dynamic_tp.get('tp2'))}")
            msg.append(f"TP3 : {self._fmt(dynamic_tp.get('tp3'))}")
            msg.append("")

        if rr:
            msg.append("📈 RR ANALYSIS")
            msg.append(f"Quality : {rr.get('quality', '-')}")
            msg.append(f"RR Score : {rr.get('score', '-')}")

        if unicorn and unicorn.get("active"):
            best = unicorn.get("best") or {}
            msg.append("")
            msg.append("🦄 UNICORN SETUP")
            msg.append(f"Direction : {best.get('direction', 'NONE')}")
            msg.append(f"Timeframe : {best.get('timeframe', '-')}")
            msg.append(f"Confidence : {unicorn.get('confidence', 0)}%")
            msg.append(f"Entry : {self._fmt(best.get('entry'))}")
            msg.append(f"Stop Loss : {self._fmt(best.get('stop_loss'))}")
            msg.append(f"TP1 : {self._fmt(best.get('tp1'))}")
            msg.append(f"TP2 : {self._fmt(best.get('tp2'))}")
            msg.append(f"TP3 : {self._fmt(best.get('tp3'))}")

        if cisd and cisd.get("active"):
            best = cisd.get("best") or {}
            msg.append("")
            msg.append("🧭 CISD")
            msg.append(f"Direction : {cisd.get('direction', 'NONE')}")
            msg.append(f"Confidence : {cisd.get('confidence', 0)}%")
            msg.append(f"Timeframe : {best.get('timeframe', '-')}")

        if decision:
            msg.append("")
            msg.append("🧠 DECISION")
            msg.append(f"Action : {decision.get('action', 'WAIT')}")
            max_len = int(getattr(Config, "TELEGRAM_MAX_DECISION_REASON_LENGTH", 140))
            reason = self._truncate(decision.get("reason", "-"), max_len)
            msg.append(f"Reason : {reason}")

        return "\n".join(msg)


class TelegramBot:
    def __init__(self, auth_store=None, token=None, chat_id=None):
        Config.refresh_from_env()
        self.token = str(token if token is not None else Config.TELEGRAM_BOT_TOKEN).strip()
        self.chat_id = self._normalize_chat_id(chat_id if chat_id is not None else Config.TELEGRAM_CHAT_ID)
        self.admin_chat_id = self._normalize_chat_id(Config.ADMIN_CHAT_ID)
        self.chat_ids_file = Config.CHAT_IDS_FILE
        self.auth_store = auth_store or TelegramAuthStore(Config.TELEGRAM_AUTH_DB_FILE)

    @staticmethod
    def _normalize_chat_id(value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return text

    def _load_file_chat_ids(self):
        if not os.path.exists(self.chat_ids_file):
            return []

        try:
            with open(self.chat_ids_file, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception:
            LOGGER.exception("Telegram chat_ids file okunamadi")
            return []

        if not isinstance(raw, list):
            return []

        normalized = []
        for item in raw:
            chat_id = self._normalize_chat_id(item)
            if chat_id is not None:
                normalized.append(chat_id)
        return normalized

    def load_chat_ids(self):
        chat_ids = []

        if self.chat_id is not None:
            chat_ids.append(self.chat_id)
        if self.admin_chat_id not in [None, 0]:
            chat_ids.append(self.admin_chat_id)

        try:
            chat_ids.extend(self.auth_store.list_authorized_chat_ids())
        except Exception:
            LOGGER.exception("Telegram auth db chat id okunamadi")

        chat_ids.extend(self._load_file_chat_ids())

        unique_chat_ids = []
        for chat_id in chat_ids:
            if chat_id not in unique_chat_ids:
                unique_chat_ids.append(chat_id)
        return unique_chat_ids

    def send_to_chat(self, chat_id, message):
        if not self.token:
            LOGGER.warning("Telegram token missing; send_to_chat skip")
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
        request = Request(url, data=payload, method="POST")

        status_code = 0
        body = ""
        ok = False

        try:
            timeout_seconds = float(getattr(Config, "TELEGRAM_HTTP_TIMEOUT_SECONDS", 3))
            with urlopen(request, timeout=timeout_seconds) as response:
                status_code = getattr(response, "status", 0) or 0
                body = response.read().decode("utf-8", errors="replace")
                ok = 200 <= status_code < 300
        except Exception as exc:
            body = str(exc)

        print("========== TELEGRAM ==========")
        print("Chat ID :", chat_id)
        print("Status :", status_code)
        print("Response :", body)
        print("==============================")

        return ok

    def send(self, message):
        try:
            if not self.token:
                print("Telegram Error : Bot token yok.")
                return False

            chat_ids = self.load_chat_ids()
            if not chat_ids:
                print("Telegram Error : Kayıtlı chat id bulunamadı.")
                return False

            results = []
            for chat_id in chat_ids:
                results.append(self.send_to_chat(chat_id, message))

            return all(results)
        except Exception as exc:
            print("Telegram Error :", exc)
            return False
