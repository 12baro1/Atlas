import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atlas_assistant import AtlasAssistant


class DummyRuntime:
    def __init__(self):
        self.last = None

    def normalize_symbol(self, raw):
        raw = str(raw or "").strip().upper()
        if not raw:
            return None
        if "/" in raw and ":" in raw:
            return raw
        return f"{raw}/USDT:USDT"

    def symbol_exists(self, symbol):
        return symbol in {"BTC/USDT:USDT", "ETH/USDT:USDT"}

    def analyze_symbol(self, symbol, force_refresh=False):
        self.last = symbol
        return {
            "ok": True,
            "symbol": symbol,
            "result": {
                "symbol": symbol,
                "signal": {
                    "signal": "LONG",
                    "signal_reason": "Entry valid and confirmed",
                    "confidence": 91,
                    "grade": "A+",
                    "learning": {"historical_edge": 0.42, "reliability": 0.81, "expected_r": 0.61},
                },
                "decision": {"action": "EXECUTE", "reason": "Quality high", "critical_blockers": []},
                "analysis": {
                    "mtf": {"h4": "BULLISH", "entry": "BULLISH"},
                    "liquidity_sweep": {"is_sweep": True},
                    "fvg": [{"type": "BULLISH"}],
                    "confluence": {"checks": ["x"]},
                    "setup_quality": {
                        "score": 91,
                        "setup_fingerprint": "fvg|liquidity_sweep",
                        "learning": {"historical_edge": 0.42, "reliability": 0.81, "expected_r": 0.61},
                    },
                },
            },
        }

    def latest_analysis(self, symbol=None):
        return None

    def current_signal(self):
        return {
            "signal_id": "ATL-1",
            "symbol": "BTC/USDT:USDT",
            "direction": "LONG",
            "rr": 3.1,
            "stop_loss": 99.0,
            "tp1": 101.0,
            "tp2": 102.0,
            "tp3": 103.0,
            "decision": "EXECUTE",
            "confidence": 91,
            "manual_status": "OPEN",
            "manual_result": None,
            "historical_edge": 0.42,
        }

    def learning_panel(self):
        return {
            "closed_manual_trades": 10,
            "wins": 6,
            "losses": 4,
            "win_rate": 60.0,
            "average_r": 0.3,
            "expectancy": 0.3,
            "profit_factor": 1.4,
            "historical_edge": 0.42,
            "reliability": 0.81,
            "matched_setups": 4,
            "learning_adjustment": 0.5,
        }

    def journal_summary(self):
        return [
            {"status": "CLOSED", "result": "WIN", "pnl_rr": 1.5},
            {"status": "CLOSED", "result": "LOSS", "pnl_rr": -1.0},
        ]

    def signal_outcomes(self):
        return [{"symbol": "BTC/USDT:USDT", "direction": "LONG", "rr": 3.1}]

    def manual_performance(self):
        return {"total": 2}

    def signal_performance(self):
        return {"closed": 3}

    def open_manual_trades(self, symbol=None):
        return []

    def learning_records(self, source="manual"):
        return [
            {"setup_fingerprint": "fvg|liquidity_sweep", "result": "WIN", "r": 1.2, "win": True},
            {"setup_fingerprint": "fvg|liquidity_sweep", "result": "LOSS", "r": -1.0, "win": False},
            {"setup_fingerprint": "fvg|liquidity_sweep", "result": "LOSS", "r": -0.4, "win": False},
        ]


def test_assistant_runs_analysis_from_natural_language():
    runtime = DummyRuntime()
    assistant = AtlasAssistant(runtime)

    payload = assistant.handle_user_message("BTC analiz et")
    text = "\n".join(payload["responses"])

    assert runtime.last == "BTC/USDT:USDT"
    assert "Analiz tamamlandi" in text
    assert "Decision: EXECUTE" in text


def test_assistant_why_uses_previous_context():
    runtime = DummyRuntime()
    assistant = AtlasAssistant(runtime)
    assistant.handle_user_message("BTC analiz et")

    payload = assistant.handle_user_message("Neden?")
    text = "\n".join(payload["responses"])

    assert "Az onceki BTC/USDT:USDT analizine gore" in text


def test_assistant_rejects_order_requests():
    runtime = DummyRuntime()
    assistant = AtlasAssistant(runtime)
    payload = assistant.handle_user_message("BTC emir gonder")
    assert "otomatik emir" in "\n".join(payload["responses"])


def test_assistant_returns_manual_actions():
    runtime = DummyRuntime()
    assistant = AtlasAssistant(runtime)

    entered = assistant.handle_user_message("Bu sinyale girdim")
    assert entered["action"]["type"] == "open_trade_prompt"

    sl = assistant.handle_user_message("SL oldum")
    assert sl["action"]["type"] == "close_trade_prompt"
    assert sl["action"]["result"] == "SL"
