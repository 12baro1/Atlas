"""
telegram_engine.py
Atlas SMC Engine v2
"""

class TelegramEngine:

    def format_signal(self, result):

        signal = result["signal"]
        entry = result["entry"]
        risk = result.get("risk")
        rr = result.get("rr")
        confluence = result.get("confluence")

        msg = []

        msg.append("📊 ATLAS SIGNAL")
        msg.append("")
        msg.append(f"Signal : {signal['signal']}")
        msg.append(f"Strength : {signal['strength']}")
        msg.append(f"Grade : {signal['grade']}")
        msg.append(f"Stars : {signal['stars']}")
        msg.append(f"Confidence : {signal['confidence']}%")

        msg.append("")

        if confluence:

            msg.append("SMC CHECKS")

            for item in confluence["checks"]:
                msg.append(item)

            msg.append("")

        if entry["entry"] is not None:

            msg.append(f"Entry : {entry['entry']}")
            msg.append(f"Stop : {entry['stop_loss']}")

            msg.append("")

        if risk:

            msg.append(f"TP1 : {risk['tp1']}")
            msg.append(f"TP2 : {risk['tp2']}")
            msg.append(f"TP3 : {risk['tp3']}")

            msg.append("")

        if rr:

            msg.append(f"RR : {rr['rr']}")
            msg.append(f"Quality : {rr['quality']}")
            msg.append(f"RR Score : {rr['score']}")

        return "\n".join(msg)
