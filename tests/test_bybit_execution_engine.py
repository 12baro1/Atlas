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


def test_decision_skip_includes_reason_and_execution_context():
    engine = BybitExecutionEngine.__new__(BybitExecutionEngine)
    engine.enabled = True
    engine.exchange = _FakeExchange()
    engine.testnet = False
    engine.demo_trading = True
    engine.api_key = "k"
    engine.api_secret = "s"
    engine.min_confidence = 85.0
    engine.allow_execute_with_caution = False
    engine.preflight_status = {"ok": True, "steps": {}, "errors": []}
    engine.logger = __import__("logging").getLogger("test.exec")

    result = engine.process(
        "BTC/USDT:USDT",
        {
            "decision": {"action": "WAIT", "reason": "Decision Score: 60"},
            "signal": {"signal": "LONG", "confidence": 90},
            "risk": {"position_size": 1, "risk_setup_valid": True},
        },
    )

    assert result["executed"] is False
    assert result["reason"] == "decision_blocked"
    assert result["decision_action"] == "WAIT"
    assert result["decision_reason"] == "Decision Score: 60"
    assert result["execution_context"]["demo_trading"] is True
    assert result["execution_context"]["key_set"] is True


def test_extract_ret_fields_from_order_info_payload():
    engine = BybitExecutionEngine.__new__(BybitExecutionEngine)

    order = {
        "id": "abc-123",
        "info": {
            "retCode": 0,
            "retMsg": "OK",
        },
    }

    assert engine._extract_ret_code(order) == 0
    assert engine._extract_ret_msg(order) == "OK"


def test_log_exchange_exception_extracts_ret_fields_from_body(monkeypatch):
    engine = BybitExecutionEngine.__new__(BybitExecutionEngine)
    engine.logger = __import__("logging").getLogger("test.exec")

    class _ExchangeError(Exception):
        def __init__(self):
            super().__init__("bybit error")
            self.body = '{"retCode":110001,"retMsg":"Insufficient balance"}'

    details = engine._log_exchange_exception("Order failed", _ExchangeError(), context={"symbol": "BTC/USDT:USDT"})

    assert details.get("retCode") == 110001
    assert details.get("retMsg") == "Insufficient balance"


def test_log_exchange_exception_extracts_ret_fields_from_prefixed_message():
    engine = BybitExecutionEngine.__new__(BybitExecutionEngine)
    engine.logger = __import__("logging").getLogger("test.exec")

    class _ExchangeError(Exception):
        def __init__(self):
            super().__init__('bybit {"retCode":10003,"retMsg":"API key is invalid.","result":{}}')

    details = engine._log_exchange_exception("Order failed", _ExchangeError(), context={"symbol": "BTC/USDT:USDT"})

    assert details.get("retCode") == 10003
    assert details.get("retMsg") == "API key is invalid."
