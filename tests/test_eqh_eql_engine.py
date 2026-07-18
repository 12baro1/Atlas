from core.candle import Candle
from confluence_engine import ConfluenceEngine
from eqh_eql_engine import EQHEQLEngine
import pytest


def candle(index, high, low, close=None):
    close = close if close is not None else (high + low) / 2
    return Candle(index, close, high, low, close, 1)


def test_detects_unswept_equal_high_zone():
    engine = EQHEQLEngine(tolerance=0.001, min_touches=2, min_separation=2)

    result = engine.detect({
        "15m": {
            "structure": [
                {"index": 1, "price": 100.0, "kind": "HIGH"},
                {"index": 4, "price": 100.05, "kind": "HIGH"},
                {"index": 7, "price": 95.0, "kind": "LOW"},
            ],
            "candles": [candle(i, 99.0, 90.0) for i in range(10)]
        }
    })

    assert result["valid"] is True
    assert result["summary"]["eqh"] == 1
    assert result["zones"][0]["type"] == "EQH"
    assert result["zones"][0]["liquidity"] == "BUY_SIDE"
    assert result["zones"][0]["swept"] is False


def test_reduces_confidence_for_swept_equal_low_zone():
    engine = EQHEQLEngine(tolerance=0.001, min_touches=2, min_separation=2)
    candles = [candle(i, 110.0, 99.0) for i in range(8)]
    candles.append(candle(8, 108.0, 98.5, close=100.0))

    result = engine.detect({
        "15m": {
            "structure": [
                {"index": 1, "price": 99.0, "kind": "LOW"},
                {"index": 4, "price": 99.04, "kind": "LOW"},
            ],
            "candles": candles
        }
    })

    assert result["zones"][0]["type"] == "EQL"
    assert result["zones"][0]["swept"] is True
    assert result["valid"] is False


def test_eqh_eql_contributes_to_confluence_checks():
    confluence = ConfluenceEngine().evaluate(
        mtf={"valid": False},
        trend={"trend": "RANGE"},
        entry={"direction": "WAIT", "valid": False},
        confirmation={"confirmed": False},
        premium_discount={"valid": False},
        liquidity_sweep={"buy_side": False, "sell_side": False},
        ote={"valid": False},
        htf_orderblock={"valid": False},
        htf_fvg={"valid": False},
        killzone=False,
        session=False,
        eqh_eql={"valid": True}
    )

    assert confluence["score"] == 6
    assert "✔ EQH/EQL Liquidity" in confluence["checks"]


def test_telegram_formats_eqh_eql_summary():
    pytest.importorskip("requests")
    from telegram_engine import TelegramEngine

    message = TelegramEngine().format_signal({
        "symbol": "BTC/USDT",
        "signal": {
            "signal": "LONG",
            "grade": "S+",
            "strength": "ELITE",
            "confidence": 92,
        },
        "entry": {"direction": "LONG", "valid": True, "entry": None},
        "eqh_eql": {
            "valid": True,
            "zones": [
                {"type": "EQH", "timeframe": "15m", "level": 100.12345}
            ]
        }
    })

    assert "📏 EQH/EQL : EQH 15m @ 100.1235" in message
