"""
telegram_engine.py
Atlas SMC Engine v3
"""

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config
from telegram_auth_store import TelegramAuthStore


class TelegramEngine:

    @staticmethod
    def _fmt(value):
        if value is None:
            return "None"
        if isinstance(value, float):
            return f"{value:.8f}".rstrip("0").rstrip(".")
        return str(value)

    def format_signal(self, result):
        
        symbol = result["symbol"]
        signal = result["signal"]
        entry = result["entry"]
        risk = result.get("risk")
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

        msg.append(f"🟢 Signal : {signal['signal']}")
        msg.append(f"⭐ Grade : {signal['grade']}")
        msg.append(f"💪 Strength : {signal['strength']}")
        msg.append(f"🎯 Confidence : {signal['confidence']}%")
        msg.append("")
        
        # Market Phase Info
        if market_phase:
            msg.append("📈 MARKET PHASE")
            msg.append(f"Phase : {market_phase.get('phase', 'Unknown')}")
            msg.append(f"Phase Quality : {market_phase.get('phase_confidence', 0)}%")
            msg.append(f"MTF Alignment : {market_phase.get('mtf_alignment', 0)}%")
            msg.append("")

        if confluence:

            msg.append("✅ SMC CHECKS")

            for item in confluence["checks"]:
                msg.append(item)

            msg.append("")

        msg.append("📍 ENTRY")
        msg.append(f"Direction : {entry['direction']}")
        msg.append(f"Valid : {entry['valid']}")

        if entry["entry"] is not None:
            msg.append(f"Entry : {self._fmt(entry['entry'])}")
            msg.append(f"Stop Loss : {self._fmt(entry['stop_loss'])}")

        msg.append("")

        if risk:

            msg.append("💰 RISK")
            msg.append(f"Capital At Risk : {self._fmt(risk['capital_at_risk'])} USDT")
            msg.append(f"Position Size : {self._fmt(risk['position_size'])}")
            msg.append(f"Risk : {self._fmt(risk['risk'])}")
            msg.append("")

            msg.append(f"TP1 : {self._fmt(risk['tp1'])}")
            msg.append(f"TP2 : {self._fmt(risk['tp2'])}")
            msg.append(f"TP3 : {self._fmt(risk['tp3'])}")
            msg.append(f"RR : {self._fmt(risk['rr'])}")
            msg.append("")

        elif dynamic_tp:

            msg.append("🎯 TARGETS")
            msg.append(f"TP1 : {self._fmt(dynamic_tp.get('tp1'))}")
            msg.append(f"TP2 : {self._fmt(dynamic_tp.get('tp2'))}")
            msg.append(f"TP3 : {self._fmt(dynamic_tp.get('tp3'))}")
            msg.append("")

        if rr:

            msg.append("📈 RR ANALYSIS")
            msg.append(f"Quality : {rr['quality']}")
            msg.append(f"RR Score : {rr['score']}")

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
            msg.append("")
            msg.append("🧭 CISD")
            msg.append(f"Direction : {cisd.get('direction', 'NONE')}")
            msg.append(f"Confidence : {cisd.get('confidence', 0)}%")
            best = cisd.get("best") or {}
            msg.append(f"Timeframe : {best.get('timeframe', '-')}")

        if decision:
            msg.append("")
            msg.append("🧠 DECISION")
            msg.append(f"Action : {decision.get('action', 'WAIT')}")
            msg.append(f"Reason : {decision.get('reason', '-')}")

        return "\n".join(msg)


class TelegramBot:

    def __init__(self, auth_store=None):

        self.token = Config.TELEGRAM_BOT_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.admin_chat_id = Config.ADMIN_CHAT_ID
        self.chat_ids_file = Config.CHAT_IDS_FILE
        self.auth_store = auth_store or TelegramAuthStore(Config.TELEGRAM_AUTH_DB_FILE)

    def load_chat_ids(self):

        chat_ids = []

        if self.chat_id:
            chat_ids.append(self.chat_id)

        if self.admin_chat_id:
            chat_ids.append(self.admin_chat_id)

        db_chat_ids = self.auth_store.list_authorized_chat_ids()
        chat_ids.extend(db_chat_ids)

        if os.path.exists(self.chat_ids_file):
            with open(self.chat_ids_file, "r") as f:
                saved_chat_ids = json.load(f)

            chat_ids.extend(saved_chat_ids)

        unique_chat_ids = []

        for chat_id in chat_ids:
            if chat_id not in unique_chat_ids:
                unique_chat_ids.append(chat_id)

        return unique_chat_ids

    def send_to_chat(self, chat_id, message):

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        payload = urlencode(
            {
                "chat_id": chat_id,
                "text": message,
            }
        ).encode("utf-8")
        request = Request(url, data=payload, method="POST")

        status_code = 0
        body = ""
        ok = False

        try:
            with urlopen(request, timeout=10) as response:
                status_code = getattr(response, "status", 0) or 0
                raw_body = response.read()
                body = raw_body.decode("utf-8", errors="replace")
                ok = 200 <= status_code < 300
        except Exception as exc:
            body = str(exc)
            ok = False

        print("========== TELEGRAM ==========")
        print("Chat ID :", chat_id)
        print("Status :", status_code)
        print("Response :", body)
        print("==============================")

        return ok

    def send(self, message):

        try:
            chat_ids = self.load_chat_ids()

            if not chat_ids:
                print("Telegram Error : Kayıtlı chat id bulunamadı.")
                return False

            results = []

            for chat_id in chat_ids:
                results.append(self.send_to_chat(chat_id, message))

            return all(results)

        except Exception as e:

            print("Telegram Error :", e)
            return False
