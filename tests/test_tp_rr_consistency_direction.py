"""P0-3 regresyon testleri: TP yönü ve sıralama doğrulaması (imzalı kontrol).

_filter_tp_rr_consistency mutlak değer (abs) ile RR üretmemeli:
- LONG: her TP > Entry; SHORT: her TP < Entry.
- LONG: TP1 < TP2 < TP3; SHORT: TP1 > TP2 > TP3.
Yanlış tarafta kalan TP mutlak RR ile geçerli gösterilemez.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from trade_quality_filters import TradeQualityFilters


def _call(direction="LONG", entry_price=100.0, stop=98.0, tp1=103.0, tp2=105.0,
          tp3=107.0, net_rr=2.5):
    filters = TradeQualityFilters()
    entry = {"entry": entry_price, "stop_loss": stop}
    if direction is not None:
        entry["direction"] = direction
    risk = {
        "stop_loss": stop,
        "weighted_net_rr": net_rr,
        "execution_rr": net_rr,
    }
    dynamic_tp = {
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sources": ["market_structure"],
    }
    return filters._filter_tp_rr_consistency(
        direction=direction,
        entry=entry,
        risk=risk,
        dynamic_tp=dynamic_tp,
        atr=1.0,
    )


def _blockers(detail):
    return " | ".join(detail.get("critical_blockers") or [])


def test_long_wrong_side_tp_is_rejected():
    """LONG'da entry altındaki TP mutlak RR ile maskelenemez (eski davranış geçerliydi)."""
    detail = _call(direction="LONG", tp1=103.0, tp2=95.0, tp3=107.0)

    assert detail["passed"] is False
    assert detail["severity"] == "critical"
    assert "tp2 on wrong side of entry (LONG)" in _blockers(detail)


def test_short_wrong_side_tp_is_rejected():
    """SHORT'ta entry üstündeki TP mutlak RR ile maskelenemez."""
    detail = _call(direction="SHORT", entry_price=100.0, stop=102.0,
                   tp1=103.0, tp2=97.0, tp3=95.0)

    assert detail["passed"] is False
    assert detail["severity"] == "critical"
    assert "tp1 on wrong side of entry (SHORT)" in _blockers(detail)


def test_long_broken_ordering_is_rejected():
    """LONG: TP1 > TP2 (merdiven bozuk) -> kritik engel; mutlak RR bunu geçemez."""
    detail = _call(direction="LONG", tp1=105.0, tp2=103.0, tp3=107.0)

    assert detail["passed"] is False
    assert detail["severity"] == "critical"
    assert "TP/RR: broken target ordering" in _blockers(detail)


def test_short_broken_ordering_is_rejected():
    """SHORT: TP1 < TP2 (merdiven bozuk) -> kritik engel."""
    detail = _call(direction="SHORT", entry_price=100.0, stop=102.0,
                   tp1=97.0, tp2=99.0, tp3=95.0)

    assert detail["passed"] is False
    assert detail["severity"] == "critical"
    assert "TP/RR: broken target ordering" in _blockers(detail)


def test_overlapping_tps_are_rejected():
    """tp1 == tp2: katı sıralama ihlali sayılır."""
    detail = _call(direction="LONG", tp1=103.0, tp2=103.0, tp3=107.0)

    assert detail["passed"] is False
    assert "TP/RR: broken target ordering" in _blockers(detail)


def test_missing_tp1_is_rejected_even_with_tp2():
    detail = _call(direction="LONG", tp1=None, tp2=105.0, tp3=107.0)

    assert detail["passed"] is False
    assert detail["severity"] == "critical"
    assert "TP/RR: TP1 missing" in _blockers(detail)


def test_direction_unresolved_is_rejected():
    """Yön çözümlenemediğinde (param yok, entry yönü yok, stop yok) engel.

    Yön çıkarımı entry/stop'a bağlıdır; stop olmadığından yön belirsiz kalır
    ve yön kontrolü entry/stop kontrolünden önce tetiklenir.
    """
    filters = TradeQualityFilters()
    detail = filters._filter_tp_rr_consistency(
        direction=None,
        entry={"entry": 100.0},
        risk={"stop_loss": None, "weighted_net_rr": 2.5},
        dynamic_tp={"tp1": 103.0, "tp2": 105.0, "tp3": 107.0,
                    "sources": ["market_structure"]},
        atr=1.0,
    )

    assert detail["passed"] is False
    assert detail["severity"] == "critical"
    assert "TP/RR: direction unresolved" in _blockers(detail)


def test_missing_entry_or_stop_is_rejected():
    detail = _call(direction="LONG", stop=None, tp1=103.0, tp2=105.0, tp3=107.0)

    assert detail["passed"] is False
    assert detail["severity"] == "critical"
    assert "TP/RR: missing entry or stop" in _blockers(detail)


def test_valid_long_ladder_passes():
    detail = _call(direction="LONG", tp1=103.0, tp2=105.0, tp3=107.0)

    assert detail["passed"] is True
    assert detail.get("critical_blockers") == []
    assert detail["tp1_rr"] == pytest.approx(1.5, abs=1e-6)


def test_valid_short_ladder_passes():
    detail = _call(direction="SHORT", entry_price=100.0, stop=102.0,
                   tp1=97.0, tp2=95.0, tp3=93.0)

    assert detail["passed"] is True
    assert detail.get("critical_blockers") == []
    assert detail["tp1_rr"] == pytest.approx(1.5, abs=1e-6)


def test_partial_ladder_tp2_tp3_missing_passes():
    """Yalnız TP1 varsa sıralama kontrolü tetiklenmez."""
    detail = _call(direction="LONG", tp1=103.0, tp2=None, tp3=None)

    assert detail["passed"] is True
    assert detail.get("critical_blockers") == []


def test_tp1_below_minimum_rr_is_rejected_signed():
    """TP1 entry'ye çok yakın: işaretli mesafe < MIN_TP1_RR -> engel."""
    detail = _call(direction="LONG", tp1=100.5, tp2=105.0, tp3=107.0)

    assert detail["passed"] is False
    assert "TP/RR: TP1" in _blockers(detail)
    assert "below minimum" in _blockers(detail)
