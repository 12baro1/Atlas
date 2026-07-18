from market_phase_engine import MarketPhaseEngine
from signal_engine import SignalEngine


def test_market_phase_detects_expansion_with_bos_and_confluence():
    engine = MarketPhaseEngine()

    result = engine.detect(
        structure=[{"bos": True, "choch": False, "direction": "BULLISH"}],
        trend={"trend": "BULLISH"},
        liquidity_sweep={"buy_side": False, "sell_side": False},
        fvg=[{"filled": False}],
        orderblocks=[{"mitigated": False}],
        premium_discount={"premium": False, "discount": True},
        mtf={"entry": "LONG", "valid": True}
    )

    assert result == {
        "phase": "EXPANSION",
        "valid": True,
        "confidence": 95
    }


def test_signal_confidence_uses_market_phase_adjustments():
    engine = SignalEngine()

    assert engine.apply_market_phase(84, {"phase": "EXPANSION"}) == 92
    assert engine.apply_market_phase(84, {"phase": "RETRACEMENT"}) == 76
    assert engine.apply_market_phase(84, {"phase": "ACCUMULATION"}) == 87
    assert engine.apply_market_phase(99, {"phase": "EXPANSION"}) == 100
