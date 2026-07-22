import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bybit_execution_engine import BybitExecutionEngine
from config import Config


class _FakeExchange:
    def set_leverage(self, leverage, symbol, params=None):
        return {"ok": True, "leverage": leverage, "symbol": symbol, "params": params or {}}


def test_resolve_leverage_within_1_20_range():
    engine = BybitExecutionEngine.__new__(BybitExecutionEngine)
    engine.min_leverage = 1
    engine.max_leverage = 20
    engine.logger = __import__("logging").getLogger("test.exec")

    leverage = engine._resolve_leverage(
        {
            "signal": {"confidence": 98, "strength": "ELITE", "grade": "S+"},
            "decision": {"action": "EXECUTE"},
            "risk": {"selected_rr": 4.2},
        }
    )

    assert 1 <= leverage <= 20
    assert leverage >= 14


def test_resolve_leverage_reduces_on_caution():
    engine = BybitExecutionEngine.__new__(BybitExecutionEngine)
    engine.min_leverage = 1
    engine.max_leverage = 20
    engine.logger = __import__("logging").getLogger("test.exec")

    exec_lev = engine._resolve_leverage(
        {
            "signal": {"confidence": 90, "strength": "STRONG", "grade": "A+"},
            "decision": {"action": "EXECUTE"},
            "risk": {"selected_rr": 3.2},
        }
    )
    caution_lev = engine._resolve_leverage(
        {
            "signal": {"confidence": 90, "strength": "STRONG", "grade": "A+"},
            "decision": {"action": "EXECUTE_WITH_CAUTION"},
            "risk": {"selected_rr": 3.2},
        }
    )

    assert caution_lev <= exec_lev


def test_auto_enable_with_keys(monkeypatch):
    monkeypatch.setattr(Config, "AUTO_TRADING_ENABLED", False)
    monkeypatch.setattr(Config, "AUTO_TRADING_AUTO_ENABLE_WITH_KEYS", True)
    monkeypatch.setattr(Config, "BYBIT_API_KEY", "k")
    monkeypatch.setattr(Config, "BYBIT_API_SECRET", "s")
    monkeypatch.setattr(Config, "AUTO_TRADING_MIN_LEVERAGE", 1)
    monkeypatch.setattr(Config, "AUTO_TRADING_MAX_LEVERAGE", 20)

    monkeypatch.setattr(BybitExecutionEngine, "_build_exchange", lambda self: _FakeExchange())

    engine = BybitExecutionEngine()

    assert engine.enabled is True
    assert engine.exchange is not None


def test_demo_trading_mode_uses_ccxt_demo_method(monkeypatch):
    import bybit

    class DemoExchange:
        def __init__(self):
            self.demo_enabled = False
            self.sandbox_enabled = None

        def enable_demo_trading(self, enabled):
            self.demo_enabled = enabled

        def set_sandbox_mode(self, enabled):
            self.sandbox_enabled = enabled

    exchange = DemoExchange()
    monkeypatch.setattr(bybit.ccxt, "bybit", lambda config: exchange)

    built = bybit.create_private_swap_exchange(
        api_key="k",
        api_secret="s",
        testnet=True,
        demo_trading=True,
    )

    assert built is exchange
    assert exchange.demo_enabled is True
    assert exchange.sandbox_enabled is None


def test_execution_engine_passes_demo_trading_flag(monkeypatch):
    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        exchange = _FakeExchange()
        exchange.verbose = False
        return exchange

    monkeypatch.setattr(Config, "AUTO_TRADING_ENABLED", True)
    monkeypatch.setattr(Config, "AUTO_TRADING_AUTO_ENABLE_WITH_KEYS", False)
    monkeypatch.setattr(Config, "BYBIT_TESTNET", True)
    monkeypatch.setattr(Config, "BYBIT_DEMO_TRADING", True)
    monkeypatch.setattr(Config, "BYBIT_API_KEY", "k")
    monkeypatch.setattr(Config, "BYBIT_API_SECRET", "s")
    monkeypatch.setattr(Config, "AUTO_TRADING_MIN_LEVERAGE", 1)
    monkeypatch.setattr(Config, "AUTO_TRADING_MAX_LEVERAGE", 20)
    monkeypatch.setattr(BybitExecutionEngine, "_preflight_exchange", lambda self, exchange: None)
    monkeypatch.setattr("bybit_execution_engine.create_private_swap_exchange", fake_builder)

    BybitExecutionEngine()

    assert captured["demo_trading"] is True
    assert captured["testnet"] is True
