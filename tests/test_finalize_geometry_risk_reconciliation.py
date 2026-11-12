"""P0-1 regresyon testleri: finalize_setup_geometry sonrası bayat RR yok.

SL/TP geometrisi kesinleştikten sonra rr / weighted_rr / weighted_net_rr /
position_size alanları yayımlanan geometriyle yeniden hesaplanmalıdır.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from atlas_main_engine import AtlasMainEngine


def _risk_payload(**overrides):
    """RiskEngine.calculate çıktısını taklit eden, bayat değerleri içeren payload.

    Bayat değerler, finalize ÖNCESİ merdivene (tp1=110, tp2=105, tp3=105.5)
    göre hesaplanmıştır: weighted_rr = 2.0*0.5 + 1.0*0.3 + 1.1*0.2 = 1.52.
    """
    payload = {
        "side": "LONG",
        "entry": 100.0,
        "requested_stop_loss": 96.0,
        "stop_loss": 95.0,
        "original_stop_loss": 96.0,
        "stop_adjusted": True,
        "risk_setup_valid": True,
        "risk_setup_reason": "Auto-expanded stop",
        "risk": 6.0,  # bilinçli olarak bayat: eski stop 94'e göre
        "tp1": 110.0,
        "tp2": 105.0,
        "tp3": 105.5,
        "rr_by_tp": {"tp1": 2.0, "tp2": 1.0, "tp3": 1.1},
        "rr1": 2.0,
        "rr2": 1.0,
        "rr3": 1.1,
        "selected_tp": "tp1",
        "selected_rr": 2.0,
        "rr": 2.0,
        "net_rr": 1.5,
        "weighted_rr": 1.52,
        "weighted_net_rr": 1.5,
        "execution_rr": 1.5,
        "cost_drag_rr": 0.02,
        "rr_selection_rule": "max_rr",
        "entry_type": "MARKET",
        "maker_fee_rate": 0.0002,
        "taker_fee_rate": 0.00055,
        "spread_rate": 0.0,
        "slippage_rate": 0.0,
        "minimum_tick_distance": 0.01,
        "sizing_factor": 1.0,
        "position_size_limit": 1000.0,
        "risk_percent_base": 1.0,
        "minimum_net_rr": 2.0,
        "position_size": 20.0,
    }
    payload.update(overrides)
    return payload


def _targets(**overrides):
    targets = {
        "tp1": 110.0,
        "tp2": 105.0,
        "tp3": 105.5,
        "minimum_target_separation": 2.0,
    }
    targets.update(overrides)
    return targets


def _entry(**overrides):
    entry = {
        "valid": True,
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 96.0,
    }
    entry.update(overrides)
    return entry


def test_tp_change_recomputes_weighted_rr_and_net_rr():
    """TP dedupe/sıralama sonrası weighted_rr bayat kalmamalı.

    Final merdiven (105, 110) → rr_by_tp {tp1: 1.0, tp2: 2.0};
    ağırlıklar 0.5/0.3 normalize → 0.625/0.375 → weighted_rr = 1.375.
    Maliyet (MARKET girişte taker + maker çıkışlar) bir kez dahil edilir:
    plan_cost = 100*0.00055 + (105*0.625 + 110*0.375)*0.0002 = 0.076375
    fee_in_r = 0.076375 / 5 = 0.015275 → net = 1.375 - 0.015275 = 1.3597.
    """
    result = AtlasMainEngine.finalize_setup_geometry(
        _entry(), _risk_payload(), _targets()
    )

    risk = result["risk"]
    assert risk["rr_by_tp"] == {"tp1": 1.0, "tp2": 2.0}
    assert risk["weighted_rr"] == pytest.approx(1.375, abs=1e-9)
    assert risk["weighted_net_rr"] == pytest.approx(1.3597, abs=1e-4)
    assert risk["execution_rr"] == pytest.approx(risk["weighted_net_rr"])
    # Bayat değerler artık yok
    assert risk["weighted_rr"] != 1.52
    assert risk["weighted_net_rr"] != 1.5


def test_stop_derived_stale_rr_is_corrected_with_final_stop():
    """Bayat stop'a göre hesaplanmış RR alanları final stop ile düzeltilmelidir."""
    stale = _risk_payload(
        rr_by_tp={"tp1": 1.25, "tp2": 2.5},
        rr1=1.25,
        rr2=2.5,
        weighted_rr=1.71875,
        weighted_net_rr=1.7,
        net_rr=1.7,
    )
    result = AtlasMainEngine.finalize_setup_geometry(_entry(), stale, _targets())

    risk = result["risk"]
    assert risk["stop_loss"] == 95.0
    assert risk["risk"] == pytest.approx(5.0, abs=1e-9)
    assert risk["rr_by_tp"] == {"tp1": 1.0, "tp2": 2.0}
    assert risk["weighted_rr"] == pytest.approx(1.375, abs=1e-9)
    assert risk["weighted_net_rr"] == pytest.approx(1.3597, abs=1e-4)


def test_stop_and_tp_change_updates_position_size():
    """Risk mesafesi ve net-RR değişince pozisyon boyutu yeniden ölçeklenmeli.

    net_rr = 1.3597 < MINIMUM_NET_RR (2.0) → risk_reduction_factor ≈ 0.6799;
    hedef sermaye = 10000 * 0.6799% = 67.985; stop maliyeti dahil birim risk
    = 5 + (100+95)*0.00055 = 5.10725 → boyut ≈ 13.3115 (bayat 20.0 değil).
    """
    result = AtlasMainEngine.finalize_setup_geometry(
        _entry(), _risk_payload(), _targets()
    )

    risk = result["risk"]
    assert risk["risk"] == pytest.approx(5.0, abs=1e-9)
    assert risk["risk_reduction_factor"] == pytest.approx(
        round(risk["weighted_net_rr"] / 2.0, 4), abs=1e-9
    )
    assert risk["position_size"] == pytest.approx(13.3115, abs=1e-3)
    assert risk["position_size"] != 20.0
    assert risk["capital_at_risk"] == pytest.approx(67.99, abs=0.05)


def test_net_rr_includes_execution_costs_exactly_once():
    """weighted_net_rr = weighted_rr − fee_in_r; maliyet iki kez düşülmez."""
    result = AtlasMainEngine.finalize_setup_geometry(
        _entry(), _risk_payload(), _targets()
    )

    risk = result["risk"]
    weighted_rr = risk["weighted_rr"]
    plan_cost = risk["plan_cost_quote_per_unit"]
    fee_in_r = plan_cost / risk["risk"]
    assert risk["weighted_net_rr"] == pytest.approx(round(weighted_rr - fee_in_r, 4), abs=1e-6)
    assert risk["cost_drag_rr"] == pytest.approx(round(fee_in_r, 4), abs=1e-6)
    # Çift sayım kontrolü: iki kez düşülmüş değer net_rr'ye eşit olamaz.
    double_counted = round(weighted_rr - 2 * fee_in_r, 4)
    assert risk["weighted_net_rr"] != pytest.approx(double_counted, abs=1e-3)


def test_final_signal_geometry_and_rr_are_consistent():
    """Final sinyal payload'ındaki entry/SL/TP/RR tek geometriye ait olmalı."""
    result = AtlasMainEngine.finalize_setup_geometry(
        _entry(), _risk_payload(), _targets()
    )
    entry, risk, targets = result["entry"], result["risk"], result["targets"]

    assert entry["stop_loss"] == risk["stop_loss"] == 95.0
    assert entry["tp1"] == risk["tp1"] == targets["tp1"] == 105.0
    assert entry["tp2"] == risk["tp2"] == targets["tp2"] == 110.0
    assert entry["tp3"] is None and risk["tp3"] is None and targets["tp3"] is None
    assert risk["rr1"] == pytest.approx(round((105.0 - 100.0) / 5.0, 2))
    assert risk["rr2"] == pytest.approx(round((110.0 - 100.0) / 5.0, 2))
    assert risk["final_geometry_reconciled"] is True
    assert entry["final_geometry_authority"] == "ATLAS_MAIN_ENGINE"


def test_reconciliation_is_idempotent():
    """Aynı girdiyle ikinci finalize çağrısı değerleri değiştirmemeli."""
    first = AtlasMainEngine.finalize_setup_geometry(
        _entry(), _risk_payload(), _targets()
    )
    second = AtlasMainEngine.finalize_setup_geometry(
        first["entry"], first["risk"], first["targets"]
    )

    assert second["risk"]["weighted_rr"] == first["risk"]["weighted_rr"]
    assert second["risk"]["weighted_net_rr"] == first["risk"]["weighted_net_rr"]
    assert second["risk"]["position_size"] == first["risk"]["position_size"]


def test_missing_risk_payload_is_preserved():
    result = AtlasMainEngine.finalize_setup_geometry(
        _entry(), None, _targets()
    )
    assert result["risk"] is None
    assert result["entry"]["valid"] is True
