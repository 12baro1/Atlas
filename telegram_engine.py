"""
telegram_engine.py
Atlas SMC Engine
"""

class TelegramEngine:

    def format_signal(self, state):

        lines = []

        lines.append("📊 ATLAS SIGNAL")
        lines.append("")
        lines.append(f"Symbol : {state.symbol}")
        lines.append(f"Timeframe : {state.timeframe}")
        lines.append(f"Signal : {state.signal}")
        lines.append(f"Confidence : %{state.confidence}")

        if state.entry is not None:
            lines.append(f"Entry : {state.entry}")

        if state.stop_loss is not None:
            lines.append(f"Stop Loss : {state.stop_loss}")

        if state.take_profit is not None:
            lines.append(f"Take Profit : {state.take_profit}")

        if state.notes:
            lines.append("")
            lines.append("Reasons:")
            for note in state.notes:
                lines.append(f"- {note}")

        return "\n".join(lines)
