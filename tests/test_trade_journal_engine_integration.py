import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from engine import AtlasEngine


def _candle(index):
    return Candle(
        time=1_700_000_000_000 + (index * 60_000),
        open=100 + index,
        high=101 + index,
        low=99 + index,
        close=100.5 + index,
        volume=120.0,
    )


def test_engine_records_trade_journal_snapshot(monkeypatch):
    engine = AtlasEngine()

    monkeypatch.setattr(engine, "_validate_market_data", lambda data: None)
    monkeypatch.setattr(engine, "_analyze_timeframe", lambda candles: {"pivots": [], "structure": [{"label": "HH", "bos": False, "choch": False, "direction": "BULLISH"}]})
    monkeypatch.setattr(engine, "_build_structure_state", lambda **kwargs: {"structure": [], "bos": [], "choch": [], "liquidity": [], "liquidity_layers": {"swing": [], "internal": [], "all": []}, "eqh_eql": {"eqh": [], "eql": [], "active": False}, "orderblocks": [], "fvg": [], "liquidity_sweep": {"buy_side": False, "sell_side": False, "strength_score": 0}, "inducement": {"active": False}, "breaker": []})
    monkeypatch.setattr(engine, "_build_context_state", lambda **kwargs: {"mtf": {"valid": True, "weekly": "BULLISH", "daily": "BULLISH", "h4": "BULLISH", "entry": "LONG"}, "trend": {"trend": "BULLISH", "strength": 2}, "premium_discount": {"valid": True}, "killzone": {"name": "LONDON"}, "session": {"session": "LONDON"}, "ote": {"valid": True}, "htf_orderblock": {"valid": True}, "htf_fvg": {"valid": True}, "market_phase": {"phase": "Expansion", "phase_confidence": 80, "phase_score": 90, "mtf_alignment": 100}})
    monkeypatch.setattr(engine, "_build_unicorn_state", lambda **kwargs: {"active": False, "direction": "NONE", "confidence": 0, "best": None, "setups": [], "timeframes": {}})
    monkeypatch.setattr(engine, "_build_cisd_state", lambda **kwargs: {"active": False, "direction": "NONE", "confidence": 0, "best": None, "timeframes": {}, "events": []})
    monkeypatch.setattr(engine, "_build_volume_profile_state", lambda data: {"active": False, "direction": "NONE", "confidence": 0, "best": None, "timeframes": {}})
    monkeypatch.setattr(engine, "_build_institutional_state", lambda **kwargs: {"active": False, "direction": "NONE", "confidence": 0, "score": 0, "best": None})
    monkeypatch.setattr(engine, "_build_execution_state", lambda **kwargs: {"entry": {"direction": "LONG", "valid": True, "entry": 100.0, "stop_loss": 99.0}, "confirmation": {"confirmed": True}, "confluence": {"score": 90, "confidence": 90, "checks": ["✔ Entry"]}, "dynamic_tp": {"tp1": 101.0, "tp2": 102.0, "tp3": 103.0}, "risk": {"rr": 2.5, "entry": 100.0, "stop_loss": 99.0, "position_size": 1.0, "capital_at_risk": 10.0}, "rr": {"rr": 2.5}, "signal": {"signal": "LONG", "confidence": 88, "grade": "A", "stars": "★★★★☆", "strength": "STRONG", "checks": ["✔ Entry"], "market_phase": "Expansion", "phase_quality": 80, "liquidity_strength": 0, "smt_confidence": 0, "unicorn_confidence": 0, "unicorn_active": False, "cisd_confidence": 0, "cisd_active": False, "cisd_direction": "NONE", "volume_profile_confidence": 0, "volume_profile_direction": "NONE", "institutional_confidence": 0, "institutional_direction": "NONE", "alignment_conflicts": 0}})
    monkeypatch.setattr(engine.decision, "decide", lambda **kwargs: {"action": "LONG", "reason": "ok", "score": 90, "confidence": 88, "cisd_match": False, "volume_profile_match": False, "institutional_match": False})
    monkeypatch.setattr(engine, "_calculate_risk", lambda entry, dynamic_tp, volume_profile=None, institutional=None: {"rr": 2.5, "entry": 100.0, "stop_loss": 99.0, "position_size": 1.0, "capital_at_risk": 10.0})
    monkeypatch.setattr(engine, "_calculate_dynamic_tp", lambda entry, liquidity, fvg, orderblocks: {"tp1": 101.0, "tp2": 102.0, "tp3": 103.0})
    monkeypatch.setattr(engine, "_notify_if_elite", lambda **kwargs: False)

    data = {
        "symbol": "BTC/USDT:USDT",
        "1w": [_candle(0), _candle(1), _candle(2), _candle(3)],
        "15m": [_candle(0), _candle(1), _candle(2), _candle(3)],
        "1h": [_candle(0), _candle(1), _candle(2), _candle(3)],
        "4h": [_candle(0), _candle(1), _candle(2), _candle(3)],
        "1d": [_candle(0), _candle(1), _candle(2), _candle(3)],
    }

    result = engine.analyze(data)

    assert result["journal"]["symbol"] == "BTC/USDT:USDT"
    assert result["analysis"]["journal"]["timeframe"] == "multi"
    assert engine.trade_journal.analysis_summary()["total_snapshots"] == 1
