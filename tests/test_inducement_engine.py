from confluence_engine import ConfluenceEngine
from inducement_engine import InducementEngine
import pytest


def bullish_payload():
    return {
        "timeframes": {
            "15m": {
                "structure": [
                    {"index": 1, "price": 98.0, "kind": "LOW", "bos": False, "choch": False},
                    {"index": 5, "price": 105.0, "kind": "HIGH", "bos": True, "choch": False, "direction": "BULLISH"},
                ],
                "candles": [],
                "fvg": [{"type": "BULLISH", "filled": False}],
                "orderblocks": [{"type": "BULLISH", "mitigated": False}],
                "breaker": [{"type": "BULLISH"}],
            }
        },
        "trend": {"trend": "BULLISH"},
        "liquidity_sweep": {"buy_side": False, "sell_side": True},
        "eqh_eql": {
            "valid": True,
            "zones": [{"type": "EQL", "timeframe": "15m", "level": 98.0}],
        },
        "market_phase": {"phase": "ACCUMULATION"},
    }


def test_detects_professional_bullish_inducement():
    payload = bullish_payload()
    result = InducementEngine().detect(**payload)

    assert result["valid"] is True
    assert result["direction"] == "BULLISH"
    assert result["price"] == 98.0
    assert result["timeframe"] == "15m"
    assert result["confidence"] == 100
    assert "EQH/EQL" in result["reason"]
    assert result["summary"] == "Bullish IDM @ 98.0 on 15m (100%)"


def test_filters_low_confidence_inducement_false_positive():
    result = InducementEngine().detect(
        timeframes={
            "15m": {
                "structure": [
                    {"index": 1, "price": 98.0, "kind": "LOW"},
                    {"index": 5, "price": 105.0, "kind": "HIGH", "bos": True, "direction": "BULLISH"},
                ],
                "candles": [],
                "fvg": [],
                "orderblocks": [],
                "breaker": [],
            }
        },
        trend={"trend": "RANGE"},
        liquidity_sweep={"buy_side": False, "sell_side": False},
        eqh_eql={"valid": False, "zones": []},
        market_phase={"phase": "DISTRIBUTION"},
    )

    assert result["valid"] is False
    assert result["confidence"] == 0
    assert result["idms"] == []


def test_inducement_contributes_to_confluence_checks():
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
        inducement={"valid": True},
    )

    assert confluence["score"] == 7
    assert "✔ Inducement" in confluence["checks"]


def test_telegram_formats_inducement_summary():
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
        "inducement": {
            "valid": True,
            "direction": "BULLISH",
            "confidence": 88,
        },
    })

    assert "IDM: ✔ Bullish (%88)" in message
