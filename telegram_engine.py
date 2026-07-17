"""
telegram_engine.py
Atlas SMC Engine v3
"""

import requests


class TelegramEngine:

    def format_signal(self, result):

        signal = result["signal"]
        entry = result["entry"]
        risk = result.get("risk")
        rr = result.get("rr")
        confluence = result.get("confluence")

        msg = []

        msg.append("📊 ATLAS SMC SIGNAL")
        msg.append("")

        msg.append(f"🟢 Signal : {signal['signal']}")
        msg.append(f"⭐ Grade : {signal['grade']}")
        msg.append(f"💪 Strength : {signal['strength']}")
        msg.append(f"🎯 Confidence : {signal['confidence']}%")
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

        self.token = "8451423294:AAFJ8gmvKPk23ierRsh4u5sX3SRIXk2uDWY"
        self.chat_id = "6378242540"

    def send(self, message):

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        try:

            response = requests.post(
                url,
                data={
                    "chat_id": self.chat_id,
                    "text": message
                },
                timeout=10
            )

            print("========== TELEGRAM ==========")
            print("Status :", response.status_code)
            print("Response :", response.text)
            print("==============================")

            return response.ok

        except Exception as e:

            print("Telegram Error :", e)
            return False
