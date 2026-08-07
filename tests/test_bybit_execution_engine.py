"""BybitExecutionEngine ve ExecutionEngine alias testleri."""

import pytest
from bybit_execution_engine import BybitExecutionEngine, OrderResult
from execution_engine import ExecutionEngine


class _FakeClient:
    def __init__(self):
        self.calls = []

    def create_order(self, symbol, type, side, amount, price, params=None):
        self.calls.append(
            {"symbol": symbol, "type": type, "side": side, "amount": amount, "price": price, "params": params}
        )
        return {
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": symbol,
            "price": price,
            "amount": amount,
            "filled": amount,
            "average": price,
            "status": "closed",
        }

    def set_leverage(self, leverage, symbol):
        return {"leverage": leverage, "symbol": symbol}

    def fetch_balance(self):
        return {"total": {"USDT": 5000.0}}

    def fetch_positions(self, symbols):
        return [
            {
                "symbol": symbols[0],
                "contracts": 1.0,
                "contractSize": 1.0,
                "unrealizedPnl": 0.0,
                "initialMargin": 100.0,
            }
        ]


class _ConfigStub:
    AUTO_TRADING_ENABLED = True
    AUTO_TRADING_MIN_LEVERAGE = 1
    AUTO_TRADING_MAX_LEVERAGE = 20
    BYBIT_API_KEY = "k"
    BYBIT_API_SECRET = "s"
    BYBIT_TESTNET = True
    BYBIT_DEMO_TRADING = False


def _engine():
    return BybitExecutionEngine(exchange=_FakeClient(), config=_ConfigStub)


def test_validate_blocks_without_autotrading(monkeypatch):
    class Disabled(_ConfigStub):
        AUTO_TRADING_ENABLED = False

    engine = BybitExecutionEngine(exchange=_FakeClient(), config=Disabled)
    issues = engine.validate(symbol="BTC/USDT:USDT", side="buy", amount=10)
    assert any("AUTO_TRADING_ENABLED" in i for i in issues)


def test_validate_rejects_bad_symbol_and_side():
    engine = _engine()
    issues = engine.validate(symbol="BTC", side="bogus", amount=10)
    assert any("sembol" in i.lower() or "Sembol" in i for i in issues)
    assert any("yön" in i.lower() or "Yön" in i.lower() for i in issues)


def test_create_order_success():
    engine = _engine()
    result = engine.create_order("BTC/USDT:USDT", "buy", 0.5, order_type="market")
    assert result.success is True
    assert result.order_id == "order-1"
    assert result.filled == 0.5


def test_create_order_blocked_when_disabled():
    class Disabled(_ConfigStub):
        AUTO_TRADING_ENABLED = False

    engine = BybitExecutionEngine(exchange=_FakeClient(), config=Disabled)
    result = engine.create_order("BTC/USDT:USDT", "buy", 0.5)
    assert result.success is False
    assert result.error


def test_open_position_clamps_leverage():
    engine = _engine()
    # max leverage 20; 999 -> clamp
    result = engine.open_position("BTC/USDT:USDT", "buy", 0.5, leverage=999)
    assert result.success is True
    assert engine._clamp_leverage(999) == 20


def test_clamp_leverage_bounds():
    engine = _engine()
    assert engine._clamp_leverage(0) == 1
    assert engine._clamp_leverage(-5) == 1
    assert engine._clamp_leverage(5) == 5
    assert engine._clamp_leverage(9999) == 20


def test_total_equity():
    engine = _engine()
    assert engine.total_equity() == 5000.0


def test_has_credentials():
    engine = _engine()
    assert engine.has_credentials() is True


def test_execution_engine_alias_is_subclass():
    assert issubclass(ExecutionEngine, BybitExecutionEngine)


def test_order_result_dataclass_defaults():
    r = OrderResult(success=False)
    assert r.order_id is None
    assert r.symbol is None
    assert r.info == {}