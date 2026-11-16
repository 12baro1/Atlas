"""Veri kullanım raporu + OI geçmişi testleri.

Kapsam:
- build_shared_market_evidence: kaynak ayrımı, OI snapshot vs timestamped geçmiş.
- Strateji veri kullanım raporu: yalnızca okunan girdiler raporlanır,
  okunmayan veri asla kullanılmış gibi gösterilmez.
- Liquidation stratejisi: yalnızca FRESH ve en az 2 zaman damgalı OI
  gözleminden kontraksiyon; tek snapshot kurulum üretemez ve açıkça
  gerekçelendirilir; zaman damgasız trailing snapshot fail-closed olur.
- TUI veri kullanım bölümü: kaynak/durum/filtre/eksik neden satırları.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from shared.market_data_services import build_shared_market_evidence
from strategies.liquidation.strategy import generate as liquidation_generate
from strategy_lab import SevenStrategyLab, _setup_diagnostic
from atlas_tui import _add_data_usage_section


SYMBOL = "BTC/USDT:USDT"


class Candle:
    """Yerel test mumu: strategy_lab'ın kullandığı duck-typed OHLCV nesnesi."""

    def __init__(self, open_, high, low, close, volume=100.0):
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


def baseline_candles(count=20, volume=100.0):
    highs = [101, 102, 103, 104, 103, 102, 103, 104, 105, 104,
             103, 104, 105, 106, 105, 104, 103, 104, 105, 104]
    lows = [99, 98, 99, 99, 98, 99, 99, 98, 99, 99,
            98, 99, 99, 98, 99, 99, 98, 99, 99, 98]
    return [Candle(100, high, low, 101, volume=volume) for high, low in zip(highs[:count], lows[:count])]


def impulse_candle():
    # Likidasyon benzeri yukarı yönlü düzeltme impulsu: 93.5 -> 100.
    return Candle(93.5, 100.4, 93.2, 100, volume=140.0)


def liquidation_data(now_ms, oi_values, oi_times, extra_fields=None):
    data = {
        "symbol": SYMBOL,
        "current_price": 100.0,
        "current_price_source": "GATEIO_TICKER",
        "snapshot_timestamp_ms": now_ms,
        "1h": baseline_candles() + [impulse_candle()],
        "open_interest": list(oi_values),
        "open_interest_timestamps_ms": list(oi_times),
        "open_interest_source": "REST" if oi_times else "REST_SNAPSHOT_ONLY",
        "funding_rate": [0.0001],
        "funding_rate_timestamps_ms": [now_ms - 60_000],
        "funding_rate_source": "REST",
        "recent_trades": [
            {"amount": 2.0, "price": 100.0, "side": "buy"} for _ in range(25)
        ],
        "recent_trades_source": "WEBSOCKET",
        "liquidation_events": [],
        "liquidation_events_source": "UNAVAILABLE",
    }
    if extra_fields:
        data.update(extra_fields)
    # data_engine, türetilmiş ortak kanıtı ekler; strateji bunu tüketir.
    data["shared_market_evidence"] = build_shared_market_evidence(data)
    return data


# --- build_shared_market_evidence: OI ayrımı --------------------------------------

def test_evidence_separates_oi_history_from_snapshot_only():
    now = int(time.time() * 1000)
    aligned = build_shared_market_evidence({
        "symbol": SYMBOL,
        "snapshot_timestamp_ms": now,
        "open_interest": [1000.0, 950.0],
        "open_interest_timestamps_ms": [now - 7_200_000, now - 60_000],
    })
    oi = aligned["open_interest"]
    assert oi["state"] == "FRESH"
    assert oi["count"] == 2
    assert oi["change_pct"] == pytest.approx(-5.0)

    snapshot_only = build_shared_market_evidence({
        "symbol": SYMBOL,
        "snapshot_timestamp_ms": now,
        "open_interest": [1000.0],
        "open_interest_timestamps_ms": [now - 60_000],
    })
    oi = snapshot_only["open_interest"]
    assert oi["state"] == "FRESH"
    assert oi["count"] == 1
    # Tek gözlem değişim yüzdesi ÜRETMEZ: snapshot asla geçmiş gibi gösterilmez.
    assert "change_pct" not in oi


def test_evidence_fails_closed_on_misaligned_oi_series():
    now = int(time.time() * 1000)
    result = build_shared_market_evidence({
        "symbol": SYMBOL,
        "snapshot_timestamp_ms": now,
        "open_interest": [1000.0, 950.0, 940.0],
        "open_interest_timestamps_ms": [now - 7_200_000, now - 60_000],
    })
    assert result["open_interest"]["state"] == "MISSING_TIMESTAMPS"
    assert "change_pct" not in result["open_interest"]


def test_evidence_marks_missing_feeds_without_hiding_them():
    now = int(time.time() * 1000)
    evidence = build_shared_market_evidence({"symbol": SYMBOL, "snapshot_timestamp_ms": now})
    sources = evidence["sources"]

    assert sources["orderbook"]["state"] == "UNAVAILABLE"
    assert sources["trades"]["state"] == "UNAVAILABLE"
    assert sources["liquidations"]["state"] == "UNAVAILABLE"
    assert sources["open_interest"]["state"] == "UNAVAILABLE"
    assert sources["funding"]["state"] == "UNAVAILABLE"


# --- strateji veri kullanım raporu -------------------------------------------------

def test_data_usage_lists_only_fields_the_strategy_reads():
    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0], [now - 60_000])
    data["15m"] = []
    data["4h"] = []

    report = SevenStrategyLab().analyze(data)
    rows = {row["strategy_id"]: row for row in report["data_usage"]}

    # Trend yalnızca 4h/1h/current_price okur: mikroyapı girdisi hiç listelenmez.
    assert set(rows["trend_pullback"]["generator_inputs"]) <= {"4h", "1h", "current_price"}
    # Orderflow orderbook okur; eksikse durum açıkça raporlanır.
    assert rows["orderflow_momentum"]["generator_inputs"]["orderbook"] == "UNAVAILABLE"
    # Liquidation OI okur: tek snapshot INSUFFICIENT_HISTORY olarak raporlanır.
    assert rows["liquidation_cascade"]["generator_inputs"]["open_interest"] == "INSUFFICIENT_HISTORY"


def test_data_usage_rows_carry_status_filter_result_and_trace_id():
    from trace_context import new_trace_id

    data = {"symbol": SYMBOL, "trace_id": new_trace_id(), "15m": [], "1h": [], "4h": []}
    report = SevenStrategyLab().analyze(data)

    assert len(report["data_usage"]) == 7
    for row in report["data_usage"]:
        assert row["trace_id"] == data["trace_id"]
        assert isinstance(row["setup_produced"], bool)
        assert row["common_filter_result"] in {"PASSED", "REJECTED", "NOT_REACHED"}
        assert isinstance(row["shared_source_status"], dict)
        assert "generator_inputs" in row and "analysis_features" in row


def test_data_usage_reports_filter_rejection_and_missing_reason(monkeypatch):
    import strategy_lab

    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "TREND", "trend": "BULLISH", "strength": 1.0})
    candidate = {
        "direction": "LONG", "entry_type": "MARKET", "entry": 100.0,
        "stop_loss": 98.0, "tp1": 102.5, "tp2": 104.0, "tp3": 106.0,
        "strength": 85.0, "reasons": ["test"],
    }
    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: dict(candidate))
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", lambda plan: {
        "eligible": False, "reason": "TEST_STOP_COST_REJECT", "weighted_net_rr": 0.5, "risk_plan": None,
    })

    data = {"symbol": SYMBOL, "15m": [], "1h": [], "4h": []}
    report = SevenStrategyLab().analyze(data)
    row = next(r for r in report["data_usage"] if r["strategy_id"] == "trend_pullback")

    assert row["status"] == "BLOCKED_COMMON_FILTER"
    assert row["setup_produced"] is True
    assert row["common_filter_result"] == "REJECTED"
    assert row["filter_reasons"] == ["TEST_STOP_COST_REJECT"]
    assert row["missing_reason"] is None


def test_data_usage_reports_missing_reason_when_no_setup_produced():
    empty = SevenStrategyLab().analyze({"symbol": SYMBOL, "15m": [], "1h": [], "4h": []})
    empty_row = next(r for r in empty["data_usage"] if r["strategy_id"] == "trend_pullback")

    assert empty_row["setup_produced"] is False
    assert empty_row["common_filter_result"] == "NOT_REACHED"
    assert empty_row["missing_reason"]


# --- liquidation strategy: timestamped OI observations -----------------------------

def test_liquidation_setup_requires_two_timestamped_oi_observations():
    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0], [now - 60_000])

    assert liquidation_generate(data) is None


def test_liquidation_setup_from_aligned_timestamped_oi_pairs():
    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0, 950.0], [now - 7_200_000, now - 60_000])

    plan = liquidation_generate(data)

    assert plan is not None
    assert plan["strategy_id"] == "liquidation_cascade"
    assert plan["direction"] == "LONG"
    assert plan["entry"] == 100.0
    # Native generators publish raw pattern setups; shared geometry belongs
    # to SevenStrategyLab's common filter, not the strategy package.
    assert plan["initial_stop_loss"] < 98
    assert "stop_loss" not in plan
    assert not any(key in plan for key in ("tp1", "tp2", "tp3"))
    metrics = plan["liquidation_metrics"]
    assert metrics["oi_change_pct"] == pytest.approx(-5.0)
    assert metrics["event_alignment"] == "UNAVAILABLE"
    assert any("timestamped observations" in reason for reason in plan["reasons"])


def test_liquidation_fails_closed_on_unstamped_trailing_snapshot():
    """Zaman damgasız trailing snapshot hizalı seriyi bozamaz: fail-closed."""
    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0, 950.0], [now - 7_200_000, now - 60_000])
    # Sonradan zaman damgasız eklenen snapshot: hizalama bozulur.
    data["open_interest"] = [1000.0, 950.0, 940.0]
    data["shared_market_evidence"] = build_shared_market_evidence(data)

    # Kanıt katmanı MISSING_TIMESTAMPS verir; strateji kurulum üretemez.
    assert data["shared_market_evidence"]["open_interest"]["state"] == "MISSING_TIMESTAMPS"
    assert liquidation_generate(data) is None


def test_liquidation_rejects_stale_shared_oi_evidence():
    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0, 950.0], [now - 7_200_000, now - 60_000])
    data["shared_market_evidence"] = {
        "open_interest": {"state": "STALE", "count": 2, "change_pct": -5.0},
    }

    assert liquidation_generate(data) is None


def test_liquidation_diagnostic_names_single_snapshot_limit(monkeypatch):
    import strategy_lab
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "UNKNOWN", "trend": "NEUTRAL", "strength": 0.0})

    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0], [now - 60_000])
    data["15m"] = []
    data["4h"] = []

    report = SevenStrategyLab().analyze(data)

    liquidation = next(
        item for item in report["strategies"] if item["strategy_id"] == "liquidation_cascade"
    )
    assert liquidation["status"] == "MISSING_DATA"
    assert "INSUFFICIENT_OI_HISTORY" in liquidation["reason"]
    assert "open_interest_timestamps_ms" in liquidation["reason"]
    assert "timestamped observation(s)" in liquidation["reason"]


def test_liquidation_setup_passes_common_filter_and_is_selected(monkeypatch):
    import strategy_lab
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "HIGH_VOLATILITY", "trend": "BULLISH", "strength": 1.0})
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", lambda plan: {
        "eligible": True, "reason": None, "weighted_net_rr": 2.1,
        "risk_plan": {"final_geometry_reconciled": True, "risk_setup_valid": True,
                      "weighted_net_rr": 2.1, "weighted_rr": 2.2},
    })

    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0, 950.0], [now - 7_200_000, now - 60_000])

    report = SevenStrategyLab().analyze(data)

    selected = report["selected"]
    assert selected is not None
    assert selected["strategy_id"] == "liquidation_cascade"
    assert selected["status"] == "SELECTED"
    assert selected["setup_id"].startswith("setup-liquidation_cascade-")
    # Ortak filtre sonucu aday bazlı trace'e yazılır.
    filter_stages = [entry for entry in data["trace"]["stages"] if entry["stage"] == "COMMON_FILTER"]
    assert filter_stages
    passed = [entry for entry in filter_stages if entry["filter_result"] == "PASSED"]
    assert any(entry["strategy"] == "liquidation_cascade" for entry in passed)
    # Veri kullanım satırı setup üretimini ve filtre sonucunu taşır.
    row = next(r for r in report["data_usage"] if r["strategy_id"] == "liquidation_cascade")
    assert row["setup_produced"] is True
    assert row["common_filter_result"] == "PASSED"
    assert row["generator_inputs"]["open_interest"] == "AVAILABLE"


# --- TUI section -----------------------------------------------------------------

def _usage_row(strategy_id, strategy, **overrides):
    row = {
        "strategy_id": strategy_id,
        "strategy": strategy,
        "status": overrides.get("status", "NO_SETUP"),
        "setup_produced": overrides.get("setup_produced", False),
        "common_filter_result": overrides.get("common_filter_result", "NOT_REACHED"),
        "trace_id": "trace-x-1",
        "generator_inputs": overrides.get("generator_inputs", {}),
        "analysis_features": overrides.get("analysis_features", []),
        "shared_source_status": overrides.get("shared_source_status", {}),
        "filter_reasons": overrides.get("filter_reasons", []),
        "missing_reason": overrides.get("missing_reason"),
    }
    return row


def test_tui_data_usage_section_lists_inputs_and_shared_sources():
    report = {"data_usage": [_usage_row(
        "liquidation_cascade", "Likidasyon",
        status="MISSING_DATA",
        missing_reason="INSUFFICIENT_OI_HISTORY - single snapshot",
        shared_source_status={
            "open_interest": {"state": "INSUFFICIENT_HISTORY", "source": "GATEIO_REST_SNAPSHOT"},
            "orderbook": {"state": "UNAVAILABLE", "source": "UNAVAILABLE"},
        },
        generator_inputs={
            "1h": "AVAILABLE",
            "open_interest": "INSUFFICIENT_HISTORY",
            "funding_rate": "AVAILABLE",
        },
    )]}
    lines = []
    _add_data_usage_section(lines, report)
    text = "\n".join(lines)

    assert "VERİ KULLANIM RAPORU" in text
    assert "Likidasyon" in text
    assert "Open Interest: INSUFFICIENT_HISTORY | kaynak: GATEIO_REST_SNAPSHOT" in text
    assert "Orderbook: UNAVAILABLE" in text
    assert "Mumlar 1h: AVAILABLE" in text
    assert "Funding: AVAILABLE" in text
    assert "setup üretmedi" in text
    assert "ortak filtre: erişilmedi" in text
    assert "eksik/koşul nedeni: INSUFFICIENT_OI_HISTORY" in text


def test_tui_data_usage_section_silent_without_rows():
    lines = []
    _add_data_usage_section(lines, {})
    assert lines == []


def test_tui_data_usage_shows_filter_result_and_filter_reasons():
    report = {"data_usage": [_usage_row(
        "trend_pullback", "Trend",
        status="BLOCKED_COMMON_FILTER", setup_produced=True,
        common_filter_result="REJECTED", filter_reasons=["MARKET_ENTRY_TOO_FAR"],
        generator_inputs={"1h": "AVAILABLE", "4h": "AVAILABLE", "current_price": "AVAILABLE"},
    )]}
    lines = []
    _add_data_usage_section(lines, report)
    text = "\n".join(lines)

    assert "setup üretildi" in text
    assert "ortak filtre: reddedildi" in text
    assert "filtre: MARKET_ENTRY_TOO_FAR" in text


def test_setup_diagnostic_helper_remains_decision_neutral():
    """_setup_diagnostic yalnızca gerekçe üretir; setup üretmez."""
    regime = {"label": "UNKNOWN", "trend": "NEUTRAL"}
    reason = _setup_diagnostic("liquidation_cascade", {"1h": [], "open_interest": [1000.0], "open_interest_timestamps_ms": [1]}, regime)
    assert "INSUFFICIENT_HISTORY" in reason



def test_gate_liquidation_order_side_maps_to_liquidated_position():
    from shared.market_data_services import _liquidation_evidence
    now = int(time.time() * 1000)
    evidence = _liquidation_evidence([
        {"timestamp_ms": now, "notional": 200.0, "order_side": "BUY"},
        {"timestamp_ms": now, "notional": 50.0, "order_side": "SELL"},
    ], now)
    assert evidence["state"] == "AVAILABLE"
    assert evidence["short_liquidation_notional"] == 200.0
    assert evidence["long_liquidation_notional"] == 50.0
