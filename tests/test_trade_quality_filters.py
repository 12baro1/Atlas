import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from trade_quality_filters import TradeQualityFilters


def _candle(time, open_price, high, low, close, volume=1.0):
    from core.candle import Candle
    return Candle(time=time, open=open_price, high=high, low=low, close=close, volume=volume)


def _trend_candles(n=40, start=100.0, atr=2.0):
    """ATR≈2 olan tek yönlü seri."""
    return [
        _candle(1000 + i * 60, start + i, start + i + atr, start + i - atr, start + i + atr / 2)
        for i in range(n)
    ]


def _tp_for(entry, stop, direction):
    """Giriş/stop'a göre tutarlı TP1-TP3 üretir (TP1 en az 1R)."""
    risk = abs(entry - stop)
    step = max(risk, risk * 0.5, 1e-9)
    if direction == "LONG":
        return [entry + step, entry + step * 2, entry + step * 3]
    return [entry - step, entry - step * 2, entry - step * 3]


def base_ctx(direction="LONG", atr=2.0, **overrides):
    if direction == "LONG":
        entry, stop, current = 100.0, 98.0, 100.5
        h4 = "BULLISH"
    else:
        entry, stop, current = 100.0, 102.0, 99.5
        h4 = "BEARISH"
    ctx = {
        "direction": direction,
        "entry": {
            "valid": True, "direction": direction, "entry": entry,
            "stop_loss": stop, "entry_type": "LIMIT", "ote_confluence": True,
        },
        "risk": {
            "risk_setup_valid": True, "entry": entry, "stop_loss": stop,
            "weighted_net_rr": 3.0, "execution_rr": 3.0,
        },
        "current_price": current,
        "candles": [],
        "atr_value": atr,
        "mtf": {"valid": True, "entry": direction, "h4": h4},
        "liquidity_sweep": {
            "is_sweep": False, "buy_side": False, "sell_side": False,
            "ambiguous_sweep": False,
            "post_structure": {"confirmed": False, "direction": None},
        },
        "liquidity_layers": {"swing": [], "internal": [], "all": []},
        "eqh_eql": {"eqh": [], "eql": []},
        "smt": None, "cisd": None, "volume_profile": None,
        "institutional": None, "unicorn": None,
    }
    ctx.update(overrides)
    # dynamic_tp son giriş/stop değerlerinden türetilir; override edilmediyse
    # giriş değişikliğine göre otomatik olarak güncellenir.
    if "dynamic_tp" not in overrides:
        e = ctx["entry"]["entry"]
        s = ctx["entry"]["stop_loss"]
        ctx["dynamic_tp"] = {
            "tp1": _tp_for(e, s, direction)[0],
            "tp2": _tp_for(e, s, direction)[1],
            "tp3": _tp_for(e, s, direction)[2],
            "sources": ["market_structure", "market_structure", "market_structure"],
            "synthetic_targets": False,
        }
    return ctx


def _run(filters, ctx):
    return filters.evaluate_all(**ctx)


# ------------------------------------------------------------------ F1: HTF/LTF

def test_htf_ltf_aligned_passes_for_long_and_short():
    filters = TradeQualityFilters()
    for direction in ("LONG", "SHORT"):
        result = _run(filters, base_ctx(direction=direction))
        f = result["filters"]["htf_ltf_alignment"]
        assert f["passed"] is True
        assert result["allowed"] is True
        assert not result["critical_blockers"], result["critical_blockers"]


def test_htf_ltf_strong_conflict_blocks_without_confirmed_reversal():
    filters = TradeQualityFilters()
    for direction in ("LONG", "SHORT"):
        opposing = "BEARISH" if direction == "LONG" else "BULLISH"
        ctx = base_ctx(
            direction=direction,
            mtf={"valid": True, "entry": direction, "h4": opposing},
            liquidity_sweep={"is_sweep": True, "buy_side": False, "sell_side": False,
                             "ambiguous_sweep": False,
                             "post_structure": {"confirmed": False, "direction": None}},
        )
        result = _run(filters, ctx)
        f = result["filters"]["htf_ltf_alignment"]
        assert f["passed"] is False, f"{direction}: {f}"
        assert f["severity"] == "critical"
        assert result["allowed"] is False
        assert any("HTF/LTF conflict" in b for b in result["critical_blockers"])


def test_htf_ltf_confirmed_reversal_is_not_blocked():
    filters = TradeQualityFilters()
    # 4H karşı yönlü ama onaylı swept reversal → engel değil.
    ctx = base_ctx(
        direction="LONG",
        mtf={"valid": True, "entry": "LONG", "h4": "BEARISH",
             "entry_source": "CONFIRMED_15M_REVERSAL"},
        liquidity_sweep={
            "is_sweep": True, "sell_side": True, "buy_side": False,
            "ambiguous_sweep": False,
            "post_structure": {"confirmed": True, "direction": "BULLISH"},
        },
    )
    result = _run(filters, ctx)
    f = result["filters"]["htf_ltf_alignment"]
    assert f["passed"] is True, f
    assert result["allowed"] is True


def test_htf_ltf_neutral_htf_passes():
    filters = TradeQualityFilters()
    ctx = base_ctx(direction="LONG", mtf={"valid": True, "entry": "LONG", "h4": "NEUTRAL"})
    result = _run(filters, ctx)
    assert result["filters"]["htf_ltf_alignment"]["passed"] is True
    assert result["allowed"] is True


# ------------------------------------------------------------------ F2: Likidite kalitesi

def test_liquidity_sweep_not_required_passes():
    filters = TradeQualityFilters()
    # Sweep yok; filtre sessize geçer, işlem engellenmez.
    result = _run(filters, base_ctx())
    f = result["filters"]["liquidity_quality"]
    assert f["passed"] is True
    assert result["allowed"] is True


def test_opposing_sweep_is_warning_not_blocker():
    filters = TradeQualityFilters()
    ctx = base_ctx(
        direction="LONG",
        liquidity_sweep={"is_sweep": True, "buy_side": True, "sell_side": False,
                         "ambiguous_sweep": False,
                         "post_structure": {"confirmed": True, "direction": "BEARISH"}},
    )
    result = _run(filters, ctx)
    f = result["filters"]["liquidity_quality"]
    assert f["passed"] is True, f
    assert result["allowed"] is True
    assert any("Sweep evidence opposes" in w for w in result["warnings"])


def test_aligned_confirmed_sweep_bonus():
    filters = TradeQualityFilters()
    ctx = base_ctx(
        direction="LONG",
        liquidity_sweep={"is_sweep": True, "sell_side": True, "buy_side": False,
                         "ambiguous_sweep": False,
                         "post_structure": {"confirmed": True, "direction": "BULLISH"}},
        eqh_eql={"eqh": [{"price": 110.0, "touches": 3}], "eql": []},
    )
    result = _run(filters, ctx)
    f = result["filters"]["liquidity_quality"]
    assert f["passed"] is True
    assert f["score_delta"] >= 0


def test_weak_hostile_liquidity_blocks():
    filters = TradeQualityFilters()
    # Karşı sweep + karşı-yön EQH/EQL yoğunluğu → puan düşüp engel olur.
    ctx = base_ctx(
        direction="LONG",
        liquidity_sweep={"is_sweep": True, "buy_side": True, "sell_side": False,
                         "ambiguous_sweep": False,
                         "post_structure": {"confirmed": True, "direction": "BEARISH"}},
        eqh_eql={"eqh": [], "eql": [
            {"price": 90.0, "touches": 3},
            {"price": 89.0, "touches": 3},
            {"price": 88.0, "touches": 3},
        ]},
    )
    result = _run(filters, ctx)
    f = result["filters"]["liquidity_quality"]
    assert f["passed"] is False, f
    assert f["severity"] == "critical"
    assert result["allowed"] is False


# ------------------------------------------------------------------ F3: Giriş mesafesi

def test_entry_close_to_market_passes_with_bonus():
    filters = TradeQualityFilters()
    ctx = base_ctx(direction="LONG", entry={"entry": 100.5, "stop_loss": 98.0, "entry_type": "LIMIT"},
                   current_price=100.5, atr=2.0)
    result = _run(filters, ctx)
    f = result["filters"]["entry_distance"]
    assert f["passed"] is True
    assert f.get("distance_atr", 1) <= 0.5


def test_far_market_entry_blocked():
    filters = TradeQualityFilters()
    # MARKET girişi 3 ATR uzakta → geç giriş engeli.
    ctx = base_ctx(direction="LONG", entry={"entry": 106.0, "stop_loss": 98.0, "entry_type": "MARKET"},
                   current_price=100.0, atr=2.0)
    result = _run(filters, ctx)
    f = result["filters"]["entry_distance"]
    assert f["passed"] is False, f
    assert f["severity"] == "critical"
    assert result["allowed"] is False
    assert any("Entry too far" in b for b in result["critical_blockers"])


def test_far_limit_entry_is_advisory_not_blocker():
    filters = TradeQualityFilters()
    # LIMIT girişi uzakta ama beklemede tutulur, reddedilmez.
    ctx = base_ctx(direction="LONG", entry={"entry": 106.0, "stop_loss": 98.0, "entry_type": "LIMIT"},
                   current_price=100.0, atr=2.0)
    result = _run(filters, ctx)
    f = result["filters"]["entry_distance"]
    assert f["passed"] is True
    assert result["allowed"] is True
    assert any("far" in w.lower() for w in result["warnings"])


def test_entry_distance_symmetric_for_short():
    filters = TradeQualityFilters()
    ctx = base_ctx(direction="SHORT", entry={"entry": 94.0, "stop_loss": 102.0, "entry_type": "MARKET"},
                   current_price=100.0, atr=2.0)
    result = _run(filters, ctx)
    assert result["filters"]["entry_distance"]["passed"] is False
    assert result["allowed"] is False


# ------------------------------------------------------------------ F4: Stop kalitesi

def test_valid_structural_stop_passes():
    filters = TradeQualityFilters()
    for direction in ("LONG", "SHORT"):
        result = _run(filters, base_ctx(direction=direction))
        assert result["filters"]["stop_quality"]["passed"] is True
        assert result["allowed"] is True


def test_tight_stop_blocked():
    filters = TradeQualityFilters()
    # LONG: giriş 100, stop 99.9 → 0.05 ATR < 0.25 minimum.
    ctx = base_ctx(direction="LONG", entry={"entry": 100.0, "stop_loss": 99.9},
                   risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 99.9},
                   atr=2.0)
    result = _run(filters, ctx)
    f = result["filters"]["stop_quality"]
    assert f["passed"] is False, f
    assert f["severity"] == "critical"
    assert result["allowed"] is False


def test_tight_stop_blocked_for_short():
    filters = TradeQualityFilters()
    ctx = base_ctx(direction="SHORT", entry={"entry": 100.0, "stop_loss": 100.05},
                   risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 100.05},
                   atr=2.0)
    result = _run(filters, ctx)
    assert result["filters"]["stop_quality"]["passed"] is False
    assert result["allowed"] is False


def test_wide_stop_blocked():
    filters = TradeQualityFilters()
    ctx = base_ctx(direction="LONG", entry={"entry": 100.0, "stop_loss": 85.0},
                   risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 85.0},
                   atr=2.0)
    result = _run(filters, ctx)
    f = result["filters"]["stop_quality"]
    assert f["passed"] is False, f
    assert f["severity"] == "critical"
    assert result["allowed"] is False


def test_stop_wrong_side_blocked():
    filters = TradeQualityFilters()
    ctx = base_ctx(direction="LONG", entry={"entry": 100.0, "stop_loss": 101.0},
                   risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 101.0},
                   atr=2.0)
    result = _run(filters, ctx)
    assert result["filters"]["stop_quality"]["passed"] is False
    assert result["allowed"] is False


# ------------------------------------------------------------------ F5: TP/RR tutarlılığı

def test_adequate_net_rr_passes_with_bonus():
    filters = TradeQualityFilters()
    result = _run(filters, base_ctx())
    f = result["filters"]["tp_rr_consistency"]
    assert f["passed"] is True
    assert f.get("net_rr") == 3.0
    assert result["allowed"] is True


def test_synthetic_tp_blocked():
    filters = TradeQualityFilters()
    ctx = base_ctx(dynamic_tp={"tp1": 103.0, "tp2": 106.0, "tp3": 109.0,
                               "sources": ["rr_fallback"], "synthetic_targets": True})
    result = _run(filters, ctx)
    f = result["filters"]["tp_rr_consistency"]
    assert f["passed"] is False, f
    assert f["severity"] == "critical"
    assert result["allowed"] is False
    assert any("synthetic" in b.lower() for b in result["critical_blockers"])


def test_net_rr_below_minimum_blocked():
    filters = TradeQualityFilters()
    ctx = base_ctx(risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 98.0,
                         "weighted_net_rr": 1.0, "execution_rr": 1.0})
    result = _run(filters, ctx)
    f = result["filters"]["tp_rr_consistency"]
    assert f["passed"] is False, f
    assert f["severity"] == "critical"
    assert result["allowed"] is False


def test_no_structural_target_blocked():
    filters = TradeQualityFilters()
    ctx = base_ctx(dynamic_tp={"tp1": None, "tp2": None, "tp3": None,
                               "sources": [], "synthetic_targets": False})
    result = _run(filters, ctx)
    assert result["filters"]["tp_rr_consistency"]["passed"] is False
    assert result["allowed"] is False


def test_tp1_too_close_blocked():
    filters = TradeQualityFilters()
    # risk 2.0 (100-98), tp1 101.5 → 0.75R < 0.80 minimum.
    ctx = base_ctx(entry={"entry": 100.0, "stop_loss": 98.0, "entry_type": "LIMIT"},
                   risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 98.0,
                         "weighted_net_rr": 3.0, "execution_rr": 3.0},
                   dynamic_tp={"tp1": 101.5, "tp2": 106.0, "tp3": 109.0,
                               "sources": ["market_structure"] * 3,
                               "synthetic_targets": False},
                   atr=2.0)
    result = _run(filters, ctx)
    assert result["filters"]["tp_rr_consistency"]["passed"] is False
    assert result["allowed"] is False


# ------------------------------------------------------------------ F6: Motor çetelişi

def test_no_motor_conflict_passes():
    filters = TradeQualityFilters()
    ctx = base_ctx(
        smt={"active": True, "direction": "LONG", "confidence": 80},
        cisd={"active": True, "direction": "BULLISH", "confidence": 80},
    )
    result = _run(filters, ctx)
    assert result["filters"]["motor_conflict"]["passed"] is True
    assert result["allowed"] is True


def test_single_strong_opposing_motor_is_warning_not_blocker():
    filters = TradeQualityFilters()
    ctx = base_ctx(
        direction="LONG",
        smt={"active": True, "direction": "BEARISH", "confidence": 88},
    )
    result = _run(filters, ctx)
    f = result["filters"]["motor_conflict"]
    assert f["passed"] is True, f
    assert result["allowed"] is True
    assert any("one strong opposing motor" in w for w in result["warnings"])


def test_single_weak_opposing_motor_does_not_block():
    filters = TradeQualityFilters()
    ctx = base_ctx(
        direction="LONG",
        smt={"active": True, "direction": "BEARISH", "confidence": 60},  # < 75 eşik
    )
    result = _run(filters, ctx)
    f = result["filters"]["motor_conflict"]
    assert f["passed"] is True
    assert result["allowed"] is True


def test_two_strong_opposing_motors_blocked():
    filters = TradeQualityFilters()
    ctx = base_ctx(
        direction="LONG",
        smt={"active": True, "direction": "BEARISH", "confidence": 88},
        institutional={"active": True, "direction": "SHORT", "confidence": 86},
    )
    result = _run(filters, ctx)
    f = result["filters"]["motor_conflict"]
    assert f["passed"] is False, f
    assert f["severity"] == "critical"
    assert result["allowed"] is False
    assert any("strong opposing motors" in b for b in result["critical_blockers"])


def test_motor_conflict_symmetric_for_short():
    filters = TradeQualityFilters()
    ctx = base_ctx(
        direction="SHORT",
        smt={"active": True, "direction": "LONG", "confidence": 88},
        volume_profile={"active": True, "direction": "BULLISH", "confidence": 85},
    )
    result = _run(filters, ctx)
    assert result["filters"]["motor_conflict"]["passed"] is False
    assert result["allowed"] is False


# ------------------------------------------------------------------ Filtreler kanıt üretir, tek başına karar vermez

def test_filters_return_evidence_not_action():
    filters = TradeQualityFilters()
    result = _run(filters, base_ctx())
    assert "allowed" in result
    assert "critical_blockers" in result
    assert "adjustments" in result
    assert "filters" in result
    assert set(result["filters"]) == {
        "htf_ltf_alignment", "liquidity_quality", "entry_distance",
        "stop_quality", "tp_rr_consistency", "motor_conflict",
    }
    # Her filtre ayrı ayrı geçti/geçmedi, ciddiyet ve neden bildirir.
    for name, f in result["filters"].items():
        assert "passed" in f and "severity" in f and "reason" in f


def test_any_critical_filter_blocks_decision_input():
    filters = TradeQualityFilters()
    ctx = base_ctx(
        direction="LONG",
        smt={"active": True, "direction": "BEARISH", "confidence": 88},
        institutional={"active": True, "direction": "SHORT", "confidence": 86},
    )
    result = _run(filters, ctx)
    assert result["allowed"] is False
    assert result["critical_blockers"]


def test_filters_disabled_pass_through(monkeypatch):
    import config
    monkeypatch.setattr(config.Config, "QUALITY_FILTERS_ENABLED", False)
    filters = TradeQualityFilters()
    result = _run(filters, base_ctx())
    assert result["enabled"] is False
    assert result["allowed"] is True
    assert result["critical_blockers"] == []
