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
    assert engine.main_engine.motor_call_counts["smt"] == 1
    assert engine.main_engine.evidence_pool[-1]["motor"] == "smt"


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
    assert "motor_diagnostics" in analysis
    assert analysis["motor_diagnostics"]["motor_outputs"]["mtf"]["entry"] is None


def test_smt_comparison_series_are_cut_off_at_primary_decision_time():
    engine = AtlasEngine()
    capture = _CaptureDetect()
    engine.smt = capture
    base = 1_700_000_000_000
    primary = [_candle(0), _candle(1), _candle(2)]
    comparison = [
        _candle(0),
        _candle(1),
        _candle(2),
        _candle(3),
        _candle(4),
    ]
    comparison[-2] = Candle(
        time=base + 3 * 60_000, open=100, high=102, low=99, close=101, volume=100
    )
    comparison[-1] = Candle(
        time=base + 4 * 60_000, open=100, high=103, low=99, close=102, volume=100
    )
    engine._build_smt_state({
        "symbol": "SOL/USDT:USDT",
        "15m": primary,
        "1h": [], "4h": [], "1d": [],
        "smt_universe": {
            "BTC/USDT:USDT": {"15m": comparison, "1h": [], "4h": [], "1d": []}
        },
    })
    times = [item.time for item in capture.kwargs["smt_universe"]["BTC/USDT:USDT"]["15m"]]
    assert times
    assert max(times) + 15 * 60_000 <= primary[-1].time + 15 * 60_000



def test_timeframe_smt_state_does_not_borrow_another_timeframe_divergence():
    engine = AtlasEngine()
    state = {
        "active": True,
        "direction": "BEARISH",
        "confidence": 90,
        "divergences": [
            {"type": "BEARISH", "timeframe": "4h", "confidence": 90},
            {"type": "BULLISH", "timeframe": "15m", "confidence": 60},
        ],
    }
    h1 = engine._timeframe_smt_state(state, "1h")
    m15 = engine._timeframe_smt_state(state, "15m")
    assert h1["active"] is False
    assert h1["direction"] == "NONE"
    assert m15["active"] is True
    assert m15["direction"] == "BULLISH"


def test_timeframe_structure_direction_uses_latest_confirmed_break():
    engine = AtlasEngine()
    structure = [
        {"label": "HH", "bos": True, "direction": "BULLISH"},
        {"label": "LL", "choch": True, "direction": "BEARISH"},
    ]
    assert engine._timeframe_structure_direction(structure) == "BEARISH"



def test_timeframe_structure_motors_publish_evidence_to_main_engine():
    engine = AtlasEngine()
    engine.main_engine.reset_evidence()

    result = engine._analyze_timeframe([_candle(i) for i in range(20)])
    diagnostics = engine.main_engine.motor_diagnostics()

    assert "structure" in result
    assert diagnostics["call_counts"]["market_structure"] == 5
    assert diagnostics["call_counts"]["bos"] == 1
    assert diagnostics["call_counts"]["choch"] == 1
    assert diagnostics["error_count"] == 0
    assert diagnostics["evidence_count"] == diagnostics["call_total"]


def test_market_analysis_specialists_are_registered_through_main_engine_proxies():
    from atlas_main_engine import MotorProxy

    engine = AtlasEngine()
    expected = {
        "bos", "choch", "liquidity", "orderblocks", "orderbook", "mitigation",
        "fvg", "liquidity_sweep", "breaker", "trendline", "trend",
        "market_phase", "market_regime", "trade_quality", "mtf",
        "premium_discount", "killzone", "session", "ote", "htf_orderblock",
        "htf_fvg", "smt", "unicorn", "cisd", "volume_profile",
        "institutional", "entry", "entry_optimizer", "entry_confirmation",
        "confluence", "signal", "risk", "rr", "dynamic_tp", "setup_quality",
        "news_filter", "correlation", "cooldown", "learning",
    }
    assert expected.issubset(set(engine.main_engine.motors))
    assert all(isinstance(motor, MotorProxy) for motor in engine.main_engine.motors.values())
    # ManualTradeQualityGate is invoked by the runtime for manual-entry review,
    # not as a market-analysis specialist.
    assert "manual_quality_gate" not in engine.main_engine.motors
    assert engine.manual_quality_gate is not None
