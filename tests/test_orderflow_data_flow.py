"""Requirement H: Order Flow verisinin karar yolunda kullanilmalidir.

Uctan uca akis:
Gate.io veri kaynagi -> veri normalizasyonu (build_shared_market_evidence)
-> ortak analiz servisleri -> strateji setup uretimi -> ortak filtre ->
ana karar motoru -> nihai entry.

Order Book, taker buy/sell, CVD, footprint ve likasyon verilerinin sadece
loglanmasi degil, setup/entry kararini etkilemesi gerekir. Olmayan veya stale
veri icin deger uydurulmaz; strateji None dondurmelidir.
"""
import time

import pytest

from shared.market_data_services import build_shared_market_evidence
from strategy_lab import SevenStrategyLab
import strategy_lab


class Candle:
    def __init__(self, open_, high, low, close, volume=100.0):
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


def _eligible_risk(plan):
    return {
        "eligible": True, "reason": None, "weighted_net_rr": 2.5,
        "risk_plan": {
            "final_geometry_reconciled": True, "risk_setup_valid": True,
            "weighted_net_rr": 2.5, "weighted_rr": 2.7,
        },
    }


def _orderflow_raw_data(now_ms, side="buy", book_imbalance=0.5):
    """Gate.io-style raw order flow data.

    trade_flow_history batches carry buy_notional/sell_notional so CVD can
    be computed (shared.microstructure_services.cumulative_volume_delta).
    """
    bid_size = 20.0 if book_imbalance > 0 else 2.0
    ask_size = 2.0 if book_imbalance > 0 else 20.0
    buy_notional = 200.0 if side == "buy" else 10.0
    sell_notional = 10.0 if side == "buy" else 200.0
    return {
        "symbol": "BTC/USDT:USDT",
        "snapshot_timestamp_ms": now_ms,
        "current_price": 100.0,
        "15m": [Candle(100, 101, 99, 100) for _ in range(15)],
        "orderbook": {
            "bids": [[99.9, bid_size], [99.8, bid_size], [99.7, bid_size]],
            "asks": [[100.1, ask_size], [100.2, ask_size], [100.3, ask_size]],
        },
        "orderbook_timestamp_ms": now_ms,
        "recent_trades": [
            {"amount": 5.0, "price": 100.1, "side": side} for _ in range(40)
        ],
        "recent_trades_timestamp_ms": now_ms,
        "trade_flow_history": [
            {"timestamp_ms": now_ms - 1000, "buy_notional": buy_notional,
             "sell_notional": sell_notional}
            for _ in range(40)
        ],
        "liquidation_events": [],
        "data_provenance": {
            "orderbook": "GATEIO_WS_ORDERBOOK",
            "recent_trades": "GATEIO_WS_TRADES",
            "trade_flow_history": "GATEIO_WS_TRADES",
        },
        "shared_market_evidence": {},
    }


def test_orderflow_normalization_produces_fresh_book_and_cvd():
    """Order Book ve CVD Gate.io'dan normalizasyon sonucu FRESH olmalidir."""
    now_ms = int(time.time() * 1000)
    data = _orderflow_raw_data(now_ms)
    evidence = build_shared_market_evidence(data)

    book = evidence["sources"]["orderbook"]
    assert book["state"] == "FRESH", f"orderbook must be FRESH, got {book['state']}"
    trades = evidence["sources"]["trades"]
    assert trades["state"] == "FRESH", f"trades must be FRESH, got {trades['state']}"
    cvd = evidence["sources"]["cvd"]
    assert cvd["state"] in ("FRESH", "AVAILABLE"), f"cvd must be fresh/available, got {cvd['state']}"

    book_evidence = evidence["orderbook"]
    assert "imbalance" in book_evidence, "orderbook imbalance must be computed"
    assert isinstance(book_evidence["imbalance"], (int, float))

    cvd_evidence = evidence["cvd"]
    assert cvd_evidence.get("direction") in ("BUY_DOMINANT", "SELL_DOMINANT", "NEUTRAL"), (
        f"cvd direction must be set, got {cvd_evidence.get('direction')}"
    )


def test_orderflow_reaches_strategy_through_shared_evidence(monkeypatch):
    """Order flow verisi shared_market_evidence uzerinden strateje ulasir;
    strateje giren veri FRESH isaretlenmelidir."""
    import strategies.orderflow.strategy as of_module

    now_ms = int(time.time() * 1000)
    data = _orderflow_raw_data(now_ms)
    data["shared_market_evidence"] = build_shared_market_evidence(data)

    received = {}

    def spying_generate(d):
        sme = d.get("shared_market_evidence", {})
        received["book_state"] = sme.get("sources", {}).get("orderbook", {}).get("state")
        received["trades_state"] = sme.get("sources", {}).get("trades", {}).get("state")
        received["cvd_state"] = sme.get("sources", {}).get("cvd", {}).get("state")
        received["imbalance"] = sme.get("orderbook", {}).get("imbalance")
        received["cvd_direction"] = sme.get("cvd", {}).get("direction")
        return None  # spy: don't let real strict logic interfere

    monkeypatch.setattr(strategy_lab, "_orderflow_momentum", spying_generate)
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", _eligible_risk)
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {
        "label": "TREND", "trend": "BULLISH", "strength": 1.0,
    })

    report = SevenStrategyLab().analyze(data)
    of_row = next(r for r in report["strategies"] if r["strategy_id"] == "orderflow_momentum")

    # Order flow data must reach the strategy with FRESH states.
    assert received["book_state"] == "FRESH"
    assert received["trades_state"] == "FRESH"
    assert received["imbalance"] is not None
    assert received["cvd_direction"] is not None

    # Strategy reports measurable data usage (not silently dropped).
    assert of_row["strategy_id"] == "orderflow_momentum"
    usage = next(u for u in report["data_usage"] if u["strategy_id"] == "orderflow_momentum")
    assert usage["setup_produced"] is False  # spy returned None
    assert usage["common_filter_result"] == "NOT_REACHED"


def test_orderflow_stale_data_produces_no_setup(monkeypatch):
    """Stale order book/trades orderflow_momentumu engellemeli; deger uydurulmaz."""
    import strategies.orderflow.strategy as of_module

    now_ms = int(time.time() * 1000)
    stale_data = _orderflow_raw_data(now_ms - 60_000)
    stale_data["orderbook_timestamp_ms"] = now_ms - 60_000
    stale_data["recent_trades_timestamp_ms"] = now_ms - 60_000
    stale_data["shared_market_evidence"] = build_shared_market_evidence(stale_data)

    plan = of_module.generate(stale_data)
    assert plan is None, "stale order flow must produce no setup"


def test_no_orderflow_data_means_no_fabricated_signal():
    """Order flow verisi yoksa deger uydurulmaz; strateji None dondurmelidir."""
    import strategies.orderflow.strategy as of_module

    empty = {"symbol": "BTC/USDT:USDT", "shared_market_evidence": {}}
    assert of_module.generate(empty) is None

    # Only orderbook, no trades -> no setup (trade_flow_active required)
    partial = {
        "symbol": "BTC/USDT:USDT",
        "snapshot_timestamp_ms": int(time.time() * 1000),
        "15m": [Candle(100, 101, 99, 100) for _ in range(15)],
        "orderbook": {"bids": [[99.9, 10.0]], "asks": [[100.1, 10.0]]},
        "orderbook_timestamp_ms": int(time.time() * 1000),
        "shared_market_evidence": {
            "sources": {"orderbook": {"state": "FRESH"}, "trades": {"state": "UNAVAILABLE"}},
        },
    }
    assert of_module.generate(partial) is None


def test_orderflow_side_change_flips_data(monkeypatch):
    """Alim/satis yonu degisince order flow verisi de degismelidir; yapay
    sabit sayi kullanilamaz."""
    import strategies.orderflow.strategy as of_module

    now_ms = int(time.time() * 1000)

    buy_data = _orderflow_raw_data(now_ms, side="buy", book_imbalance=0.5)
    buy_data["shared_market_evidence"] = build_shared_market_evidence(buy_data)
    buy_evidence = build_shared_market_evidence(buy_data)
    buy_imbalance = buy_evidence["orderbook"]["imbalance"]
    buy_cvd = buy_evidence["cvd"].get("direction")

    sell_data = _orderflow_raw_data(now_ms, side="sell", book_imbalance=-0.5)
    sell_data["shared_market_evidence"] = build_shared_market_evidence(sell_data)
    sell_evidence = build_shared_market_evidence(sell_data)
    sell_imbalance = sell_evidence["orderbook"]["imbalance"]
    sell_cvd = sell_evidence["cvd"].get("direction")

    # Buy flow must differ from sell flow; no fabricated constant values.
    assert buy_imbalance > 0 and sell_imbalance < 0, (
        f"buy={buy_imbalance}, sell={sell_imbalance} must have opposite signs"
    )
    assert buy_cvd != sell_cvd, "CVD direction must flip with trade side"



def test_orderflow_strategy_uses_fresh_rest_book_and_trades_without_ws_cvd(monkeypatch):
    """Background scans can still use REST order flow when no WS CVD buffer exists."""
    import strategies.orderflow.strategy as of_module

    now_ms = int(time.time() * 1000)
    data = _orderflow_raw_data(now_ms, side="buy", book_imbalance=0.5)
    data["current_price"] = 100.8
    data["15m"] = [Candle(100, 102, 99, 101.8, 150) for _ in range(15)]
    data["orderbook"] = {
        "bids": [[100.00, 20], [99.99, 20], [99.98, 20]],
        "asks": [[100.01, 2], [100.02, 2], [100.03, 2]],
    }
    data["trade_flow_history"] = []
    data["data_provenance"] = {
        "orderbook": "GATEIO_REST",
        "recent_trades": "GATEIO_REST",
        "trade_flow_history": "UNAVAILABLE",
    }
    data["shared_market_evidence"] = build_shared_market_evidence(data)
    import strategies.orderflow.analytics as analytics
    monkeypatch.setattr(
        analytics, "footprint_directional_evidence",
        lambda footprint, direction: {"state": "AVAILABLE", "confirmed": True},
    )

    plan = of_module.generate(data)
    assert plan is not None
    assert plan["direction"] == "LONG"



def test_orderflow_diagnostic_reports_exact_failed_gates_and_optional_cvd():
    """No-setup output names measurable failures instead of one generic message."""
    now_ms = int(time.time() * 1000)
    data = _orderflow_raw_data(now_ms, side="buy", book_imbalance=0.5)
    data["recent_trades"] = data["recent_trades"][:5]
    data["trade_flow_history"] = []
    data["shared_market_evidence"] = build_shared_market_evidence(data)

    reason = strategy_lab._setup_diagnostic(
        "orderflow_momentum", data, {"label": "TREND", "adx": 25},
    )

    assert "INSUFFICIENT_VALID_TRADES" in reason
    assert "FOOTPRINT_NOT_CONFIRMED" in reason
    assert "CVD_UNAVAILABLE_OPTIONAL" in reason
    assert "CONDITION_NOT_MET: fresh book/trades" not in reason


def test_orderflow_diagnostic_reports_spread_limit():
    """Spread failure is reported with the measured value and configured ceiling."""
    now_ms = int(time.time() * 1000)
    data = _orderflow_raw_data(now_ms)
    data["orderbook"] = {
        "bids": [[99.90, 20], [99.89, 20], [99.88, 20]],
        "asks": [[100.10, 20], [100.11, 20], [100.12, 20]],
    }
    data["shared_market_evidence"] = {}

    reason = strategy_lab._setup_diagnostic(
        "orderflow_momentum", data, {"label": "TREND", "adx": 25},
    )

    assert "SPREAD_LIMIT_EXCEEDED" in reason
    assert "maximum=0.08" in reason
