import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from engine import AtlasEngine


class _CaptureDetect:
    def __init__(self):
        self.kwargs = None

    def detect(self, **kwargs):
        self.kwargs = kwargs
        return {
            "active": True,
            "direction": "BULLISH",
            "confidence": 78,
            "best": {"type": "BULLISH", "confidence": 78},
            "bullish": [],
            "bearish": [],
            "divergences": [],
        }


def _candle(index):
    return Candle(
        time=1_700_000_000_000 + (index * 60_000),
        open=100 + index,
        high=101 + index,
        low=99 + index,
        close=100.5 + index,
        volume=100.0,
    )


def test_build_smt_state_passes_expected_contract():
    engine = AtlasEngine()
    capture = _CaptureDetect()
    engine.smt = capture

    market_data = {
        "symbol": "SOL/USDT:USDT",
        "15m": [_candle(1), _candle(2), _candle(3)],
        "1h": [_candle(1), _candle(2), _candle(3)],
        "4h": [_candle(1), _candle(2), _candle(3)],
        "1d": [_candle(1), _candle(2), _candle(3)],
        "smt_universe": {
            "BTC/USDT:USDT": {
                "15m": [_candle(1), _candle(2), _candle(3)],
                "1h": [_candle(1), _candle(2), _candle(3)],
                "4h": [_candle(1), _candle(2), _candle(3)],
                "1d": [_candle(1), _candle(2), _candle(3)],
            }
        },
        "selected_altcoins": ["SOL/USDT:USDT"],
    }

    result = engine._build_smt_state(market_data)

    assert result["active"] is True
    assert capture.kwargs is not None
    assert capture.kwargs["primary_symbol"] == "SOL/USDT:USDT"
    assert capture.kwargs["timeframes"] == engine.SMT_TIMEFRAMES
    assert "SOL/USDT:USDT" in capture.kwargs["smt_universe"]


def test_compose_analysis_includes_smt_key():
    engine = AtlasEngine()

    structure_state = {
        "structure": [],
        "bos": [],
        "choch": [],
        "liquidity": [],
        "eqh_eql": {"eqh": [], "eql": [], "active": False},
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweep": {"buy_side": False, "sell_side": False},
        "inducement": {"active": False},
        "breaker": [],
    }
    context_state = {
        "mtf": {"valid": False},
        "trend": {"trend": "RANGE"},
        "ote": {"valid": False},
        "premium_discount": {"valid": False},
        "killzone": False,
        "session": False,
        "htf_orderblock": {"valid": False},
        "htf_fvg": {"valid": False},
        "market_phase": {"phase": "Ranging"},
    }
    execution_state = {
        "entry": {"direction": "NONE", "valid": False},
        "confirmation": {"confirmed": False},
        "dynamic_tp": {"tp1": None, "tp2": None, "tp3": None},
        "confluence": {"score": 0, "checks": []},
    }
    smt_state = {
        "active": True,
        "direction": "BULLISH",
        "confidence": 80,
        "best": {"type": "BULLISH", "confidence": 80},
    }

    analysis = engine._compose_analysis(structure_state, context_state, execution_state, smt_state)

    assert "smt" in analysis
    assert analysis["smt"]["direction"] == "BULLISH"
