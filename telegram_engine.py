"""
telegram_engine.py
Atlas SMC Engine v3
"""

import json
import os

import requests

from config import Config


class TelegramEngine:

    def format_signal(self, result):
        
        symbol = result["symbol"]
        signal = result["signal"]
        entry = result["entry"]
        risk = result.get("risk")
        rr = result.get("rr")
        confluence = result.get("confluence")
        market_phase = result.get("market_phase")
        eqh_eql = result.get("eqh_eql")
        inducement = result.get("inducement")

        msg = []

        msg.append("📊 ATLAS SMC SIGNAL")
        msg.append(f"🪙 Coin : {symbol}")
        msg.append("")

        msg.append(f"🟢 Signal : {signal['signal']}")
        msg.append(f"⭐ Grade : {signal['grade']}")
        msg.append(f"💪 Strength : {signal['strength']}")
        msg.append(f"🎯 Confidence : {signal['confidence']}%")

        if market_phase:
            phase = market_phase["phase"].title()
            msg.append(f"📈 Market Phase : {phase}")

        if eqh_eql and eqh_eql.get("valid"):
            zones = eqh_eql.get("zones", [])[:3]
            zone_text = ", ".join(
                f"{zone['type']} {zone['timeframe']} @ {round(zone['level'], 4)}"
                for zone in zones
            )
            msg.append(f"📏 EQH/EQL : {zone_text}")

        if inducement and inducement.get("valid"):
            direction = inducement["direction"].title()
            confidence = inducement["confidence"]
            msg.append(f"IDM: ✔ {direction} (%{confidence})")

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
            msg.append(f"Entry : {entry['entry']}")
            msg.append(f"Stop Loss : {entry['stop_loss']}")

        msg.append("")

        if risk:

            msg.append("💰 RISK")
            msg.append(f"Capital At Risk : {risk['capital_at_risk']} USDT")
            msg.append(f"Position Size : {risk['position_size']}")
            msg.append(f"Risk : {risk['risk']}")
            msg.append("")

            msg.append(f"TP1 : {risk['tp1']}")
            msg.append(f"TP2 : {risk['tp2']}")
            msg.append(f"TP3 : {risk['tp3']}")
            msg.append(f"RR : {risk['rr']}")
            msg.append("")

        if rr:

            msg.append("📈 RR ANALYSIS")
            msg.append(f"Quality : {rr['quality']}")
            msg.append(f"RR Score : {rr['score']}")

        return "\n".join(msg)


class TelegramBot:

    def __init__(self):

        self.token = Config.TELEGRAM_BOT_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.admin_chat_id = Config.ADMIN_CHAT_ID
        self.chat_ids_file = Config.CHAT_IDS_FILE

    def load_chat_ids(self):

        chat_ids = []

        if self.chat_id:
            chat_ids.append(self.chat_id)

        if self.admin_chat_id:
            chat_ids.append(self.admin_chat_id)

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

        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message
            },
            timeout=10
        )

        print("========== TELEGRAM ==========")
        print("Chat ID :", chat_id)
        print("Status :", response.status_code)
        print("Response :", response.text)
        print("==============================")

        return response.ok

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
