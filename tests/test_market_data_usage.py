"""Veri kullanım raporu + OI geçmişi testleri.

Kapsam:
- market_feed_evidence: kaynak ayrımı, OI snapshot vs timestamped geçmiş.
- STRATEGY_FEEDS eşlemesi: kullanılmayan veri kullanılmış gösterilmez.
- Liquidation stratejisi: yalnızca hizalı zaman damgalı OI çiftlerinden
  kontraksiyon; tek snapshot kurulum üretemez ve açıkça gerekçelendirilir.
- TUI veri kullanım bölümü: kullanılmayan veri "KULLANILMADI" görünür.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from shared.market_data_services import market_feed_evidence
from strategies.liquidation.strategy import generate as liquidation_generate
from strategy_lab import SevenStrategyLab, STRATEGY_FEEDS, _strategy_data_usage, _setup_diagnostic
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


def liquidation_data(now_ms, oi_values, oi_times, snapshot_extra=None):
    data = {
        "symbol": SYMBOL,
        "current_price": 100.0,
        "current_price_source": "BYBIT_TICKER",
        "snapshot_timestamp_ms": now_ms,
        "1h": baseline_candles() + [impulse_candle()],
        "open_interest": list(oi_values),
        "open_interest_timestamps_ms": list(oi_times),
        "open_interest_source": "REST" if oi_times else "REST_SNAPSHOT_ONLY",
        "funding_rate": [0.0001],
        "funding_rate_source": "REST",
        "recent_trades": [
            {"amount": 2.0, "price": 100.0, "side": "buy"} for _ in range(25)
        ],
        "recent_trades_source": "WEBSOCKET",
        "liquidation_events": [],
        "liquidation_events_source": "UNAVAILABLE",
    }
    if snapshot_extra is not None:
        data["open_interest"] = list(oi_values) + [snapshot_extra]
    return data


# --- market_feed_evidence -----------------------------------------------------

def test_feed_evidence_reports_orderbook_source_and_freshness():
    now = int(time.time() * 1000)
    evidence = market_feed_evidence({
        "symbol": SYMBOL,
        "snapshot_timestamp_ms": now,
        "orderbook": {"bids": [["100", "1"]] * 3, "asks": [["101", "1"]] * 3, "timestamp": now - 1000},
        "orderbook_source": "WEBSOCKET",
    })

    book = evidence["feeds"]["orderbook"]
    assert book["source"] == "WEBSOCKET"
    assert book["status"] == "AVAILABLE"
    assert book["samples"] == 6
    assert book["age_ms"] == 1000
    assert book["freshness"] == "FRESH"


def test_feed_evidence_separates_oi_history_from_snapshot_only():
    now = int(time.time() * 1000)
    aligned = market_feed_evidence({
        "symbol": SYMBOL,
        "snapshot_timestamp_ms": now,
        "open_interest": [1000.0, 950.0],
        "open_interest_timestamps_ms": [now - 7_200_000, now - 60_000],
        "open_interest_source": "REST",
    })
    oi = aligned["feeds"]["open_interest"]
    assert oi["status"] == "AVAILABLE"
    assert oi["source"] == "REST"
    assert oi["timestamped_samples"] == 2
    assert oi["snapshot_only_samples"] == 0

    snapshot_only = market_feed_evidence({
        "symbol": SYMBOL,
        "snapshot_timestamp_ms": now,
        "open_interest": [1000.0],
        "open_interest_timestamps_ms": [],
        "open_interest_source": "REST_SNAPSHOT_ONLY",
    })
    oi = snapshot_only["feeds"]["open_interest"]
    assert oi["status"] == "INSUFFICIENT_OI_HISTORY"
    assert oi["source"] == "REST_SNAPSHOT_ONLY"
    assert oi["timestamped_samples"] == 0
    assert oi["snapshot_only_samples"] == 1
    assert oi["reason"] == "SINGLE_OI_SNAPSHOT_CANNOT_ESTABLISH_CONTRACTION"

    mixed = market_feed_evidence({
        "symbol": SYMBOL,
        "snapshot_timestamp_ms": now,
        "open_interest": [1000.0, 950.0, 940.0],
        "open_interest_timestamps_ms": [now - 7_200_000, now - 60_000],
        "open_interest_source": "REST",
    })
    oi = mixed["feeds"]["open_interest"]
    assert oi["timestamped_samples"] == 2
    assert oi["snapshot_only_samples"] == 1
    assert oi["status"] == "AVAILABLE"


def test_feed_evidence_marks_missing_feeds_with_reasons():
    now = int(time.time() * 1000)
    evidence = market_feed_evidence({"symbol": SYMBOL, "snapshot_timestamp_ms": now})
    feeds = evidence["feeds"]

    assert feeds["orderbook"]["status"] == "UNAVAILABLE"
    assert feeds["orderbook"]["reason"] == "NO_ORDERBOOK_SNAPSHOT"
    assert feeds["recent_trades"]["reason"] == "NO_RECENT_TRADES"
    assert feeds["trade_flow_history"]["reason"] == "NO_TIMESTAMPED_TRADE_BATCHES"
    assert feeds["liquidation_events"]["reason"] == "NO_EXCHANGE_LIQUIDATION_FEED"
    assert feeds["open_interest"]["reason"] == "NO_TIMESTAMPED_OI_OBSERVATIONS"
    assert feeds["funding_rate"]["reason"] == "NO_FUNDING_RATE_HISTORY"
    assert feeds["candles"]["reason"] == "INCOMPLETE_OHLCV_TIMEFRAMES"
    assert feeds["correlation_universe"]["reason"] == "NO_BENCHMARK_CANDLES"
    assert evidence["microstructure_source"] == "UNAVAILABLE"


# --- STRATEGY_FEEDS mapping ----------------------------------------------------

def test_strategy_feeds_map_only_the_data_each_strategy_reads():
    assert STRATEGY_FEEDS["trend_pullback"] == ("candles",)
    assert STRATEGY_FEEDS["volatility_breakout"] == ("candles",)
    assert STRATEGY_FEEDS["mean_reversion"] == ("candles",)
    assert STRATEGY_FEEDS["liquidation_cascade"] == (
        "candles", "open_interest", "funding_rate", "recent_trades", "liquidation_events",
    )
    assert STRATEGY_FEEDS["orderflow_momentum"] == (
        "candles", "orderbook", "recent_trades", "trade_flow_history", "footprint", "liquidation_events",
    )
    assert STRATEGY_FEEDS["relative_strength"] == ("candles", "correlation_universe")
    assert STRATEGY_FEEDS["smc"] == ("candles", "orderbook", "recent_trades", "open_interest", "funding_rate")


def test_data_usage_marks_unused_feeds_as_not_used():
    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0, 950.0], [now - 7_200_000, now - 60_000])

    trend = _strategy_data_usage("trend_pullback", data)
    assert trend["feeds"]["candles"]["used"] is True
    assert trend["feeds"]["open_interest"]["used"] is False
    assert trend["feeds"]["open_interest"]["status"] == "NOT_USED"
    assert trend["feeds"]["orderbook"]["status"] == "NOT_USED"

    liquidation = _strategy_data_usage("liquidation_cascade", data)
    assert liquidation["feeds"]["open_interest"]["used"] is True
    assert liquidation["feeds"]["open_interest"]["status"] == "AVAILABLE"
    assert liquidation["feeds"]["funding_rate"]["used"] is True
    assert liquidation["feeds"]["orderbook"]["used"] is False

    orderflow = _strategy_data_usage("orderflow_momentum", data)
    # Footprint yalnızca orderflow için türetilir ve kullanılır.
    assert orderflow["feeds"]["footprint"]["used"] is True
    assert "source" in orderflow["feeds"]["footprint"]


def test_data_usage_carries_trace_id_of_the_analysis():
    from trace_context import new_trace_id

    data = {"symbol": SYMBOL, "trace_id": new_trace_id()}
    row = _strategy_data_usage("trend_pullback", data)
    assert row["trace_id"] == data["trace_id"]


# --- liquidation strategy: aligned timestamped OI pairs --------------------------

def test_liquidation_setup_requires_two_timestamped_oi_observations():
    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0], [])

    assert liquidation_generate(data) is None


def test_liquidation_setup_from_aligned_timestamped_oi_pairs():
    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0, 950.0], [now - 7_200_000, now - 60_000])

    plan = liquidation_generate(data)

    assert plan is not None
    assert plan["strategy_id"] == "liquidation_cascade"
    assert plan["direction"] == "LONG"
    assert plan["entry"] == 100.0
    assert plan["stop_loss"] < 98
    assert plan["tp1"] == pytest.approx(104.0)
    metrics = plan["liquidation_metrics"]
    assert metrics["oi_change_pct"] == pytest.approx(-5.0)
    assert metrics["oi_history_samples"] == 2
    assert metrics["oi_snapshot_value"] is None
    assert any("timestamped observations" in reason for reason in plan["reasons"])


def test_liquidation_ignores_trailing_snapshot_when_computing_oi_change():
    """Zaman damgasız snapshot tarihsel seriye karışmaz; kayma düzeltildi."""
    now = int(time.time() * 1000)
    # Sonra eklenen zaman damgasız snapshot (940) eski kodda oi[-1] olur ve
    # değişimi -(950->940)=-1.05%'e ezer; hizalı çiftler -5% kontraksiyonu korur.
    data = liquidation_data(
        now, [1000.0, 950.0], [now - 7_200_000, now - 60_000], snapshot_extra=940.0,
    )

    plan = liquidation_generate(data)

    assert plan is not None
    metrics = plan["liquidation_metrics"]
    assert metrics["oi_change_pct"] == pytest.approx(-5.0)
    assert metrics["oi_history_samples"] == 2
    assert metrics["oi_snapshot_value"] == pytest.approx(940.0)


def test_liquidation_diagnostic_names_single_snapshot_limit(monkeypatch):
    import strategy_lab
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "UNKNOWN", "trend": "NEUTRAL", "strength": 0.0})

    now = int(time.time() * 1000)
    data = liquidation_data(now, [1000.0], [])
    data["15m"] = []
    data["4h"] = []

    report = SevenStrategyLab().analyze(data)

    liquidation = next(
        item for item in report["strategies"] if item["strategy_id"] == "liquidation_cascade"
    )
    assert liquidation["status"] == "MISSING_DATA"
    assert "INSUFFICIENT_OI_HISTORY" in liquidation["reason"]
    assert "open_interest_timestamps_ms" in liquidation["reason"]
    assert "timestamped observations" in liquidation["reason"]


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


# --- TUI section -----------------------------------------------------------------

def _usage_row(strategy_id, strategy, feeds, **overrides):
    row = {
        "strategy_id": strategy_id,
        "strategy": strategy,
        "feeds": feeds,
        "microstructure_source": "MIXED_WEBSOCKET_AND_REST",
        "trace_id": "trace-x-1",
        "status": overrides.get("status", "NO_SETUP"),
        "setup_produced": overrides.get("setup_produced", False),
        "common_filter_result": overrides.get("common_filter_result", "NOT_REACHED"),
        "filter_reasons": overrides.get("filter_reasons", []),
        "missing_reason": overrides.get("missing_reason"),
    }
    return row


def test_tui_data_usage_section_marks_unused_data():
    feeds = {
        "candles": {"used": True, "source": "REST", "status": "AVAILABLE", "samples": 200},
        "orderbook": {"used": False, "status": "NOT_USED"},
        "open_interest": {"used": True, "source": "REST_SNAPSHOT_ONLY", "status": "INSUFFICIENT_OI_HISTORY",
                          "timestamped_samples": 0, "snapshot_only_samples": 1,
                          "reason": "SINGLE_OI_SNAPSHOT_CANNOT_ESTABLISH_CONTRACTION"},
    }
    report = {"data_usage": [_usage_row(
        "liquidation_cascade", "Likidasyon", feeds,
        status="MISSING_DATA", missing_reason="INSUFFICIENT_OI_HISTORY",
    )]}
    lines = []
    _add_data_usage_section(lines, report)
    text = "\n".join(lines)

    assert "VERİ KULLANIM RAPORU" in text
    assert "Likidasyon" in text
    assert "KULLANILMADI" in text                      # unused orderbook is explicit
    assert "Mumlar: AVAILABLE | kaynak: REST" in text
    assert "INSUFFICIENT_OI_HISTORY" in text
    assert "zaman damgalı: 0" in text
    assert "eksik/koşul nedeni: INSUFFICIENT_OI_HISTORY" in text
    assert "Mikroyapı kaynak özeti: MIXED_WEBSOCKET_AND_REST" in text
    # Kullanılmayan veri asla kullanılmış gibi gösterilmez.
    assert "Orderbook: AVAILABLE" not in text


def test_tui_data_usage_section_silent_without_rows():
    lines = []
    _add_data_usage_section(lines, {})
    assert lines == []


def test_tui_data_usage_shows_filter_result_and_filter_reasons():
    feeds = {"candles": {"used": True, "source": "REST", "status": "AVAILABLE", "samples": 200}}
    report = {"data_usage": [_usage_row(
        "trend_pullback", "Trend", feeds,
        status="BLOCKED_COMMON_FILTER", setup_produced=True,
        common_filter_result="REJECTED", filter_reasons=["MARKET_ENTRY_TOO_FAR"],
    )]}
    lines = []
    _add_data_usage_section(lines, report)
    text = "\n".join(lines)

    assert "setup üretildi" in text
    assert "ortak filtre: reddedildi" in text
    assert "filtre: MARKET_ENTRY_TOO_FAR" in text
