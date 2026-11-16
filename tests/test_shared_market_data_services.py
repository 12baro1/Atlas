from shared.market_data_services import build_shared_market_evidence


def test_shared_evidence_tracks_each_source_independently():
    now = 1_700_000_000_000
    data = {
        "snapshot_timestamp_ms": now,
        "15m": [object()],
        "1h": [object(), object()],
        "orderbook": {"bids": [[99, 2], [98, 1]], "asks": [[101, 1], [102, 1]]},
        "orderbook_timestamp_ms": now - 1_000,
        "recent_trades": [
            {"price": 100, "size": 2, "side": "BUY"},
            {"price": 100, "size": 1, "side": "SELL"},
        ],
        "recent_trades_timestamp_ms": now - 2_000,
        "trade_flow_history": [
            {"timestamp_ms": now - 60_000, "buy_notional": 200.0, "sell_notional": 100.0},
        ],
        "liquidation_events": [
            {"timestamp_ms": now - 1_000, "notional": 500, "side": "BUY"},
            {"timestamp_ms": now - 1_000, "notional": 100, "side": "SELL"},
        ],
        "open_interest": [1000, 970],
        "open_interest_timestamps_ms": [now - 3_600_000, now - 1_800_000],
        "funding_rate": [0.0001],
        "funding_rate_timestamps_ms": [now - 60_000],
        "data_provenance": {
            "orderbook": "MEXC_FUTURES_PUBLIC_WEBSOCKET",
            "recent_trades": "MEXC_REST",
            "liquidations": "TEST_FIXTURE",
            "open_interest": "MEXC_REST_OBSERVED_SNAPSHOTS",
            "funding_rate": "MEXC_REST_SNAPSHOT",
        },
        "correlation_universe": {"BTC": [1, 2]},
        "sector_peer_universe": {"SOL/USDT:USDT": {"4h": [1, 2, 3]}},
    }

    result = build_shared_market_evidence(data)

    assert result["sources"]["orderbook"]["source"] == "MEXC_FUTURES_PUBLIC_WEBSOCKET"
    assert result["sources"]["trades"]["source"] == "MEXC_REST"
    assert result["orderbook"]["freshness"]["state"] == "FRESH"
    assert result["orderbook"]["imbalance"] > 0
    assert result["trades"]["trade_count"] == 2
    assert result["trades"]["delta_ratio"] > 0
    assert result["cvd"]["state"] == "FRESH"
    assert result["cvd"]["net_delta"] == 100.0
    assert result["footprint"]["state"] == "AVAILABLE"
    assert result["liquidity_walls"]["state"] == "AVAILABLE"
    assert result["liquidations"]["long_liquidation_notional"] == 500
    assert result["open_interest"]["change_pct"] == -3.0
    assert result["funding"]["latest"] == 0.0001
    assert result["correlation_universe"]["BTC"] == 2
    assert result["sector_peer_universe"]["SOL/USDT:USDT"] == 3


def test_shared_evidence_marks_stale_and_future_feeds_without_hiding_them():
    now = 1_700_000_000_000
    result = build_shared_market_evidence({
        "snapshot_timestamp_ms": now,
        "orderbook": {"bids": [[99, 1]], "asks": [[101, 1]]},
        "orderbook_timestamp_ms": now - 20_000,
        "recent_trades": [{"price": 100, "size": 1, "side": "BUY"}],
        "recent_trades_timestamp_ms": now + 1_000,
        "trade_flow_history": [
            {"timestamp_ms": now - 600_000, "buy_notional": 100.0, "sell_notional": 50.0},
        ],
    })

    assert result["orderbook"]["state"] == "STALE"
    assert result["trades"]["state"] == "INVALID_FUTURE_TIMESTAMP"
    assert result["cvd"]["state"] == "STALE"


def test_single_open_interest_snapshot_is_not_misrepresented_as_history():
    now = 1_700_000_000_000
    result = build_shared_market_evidence({
        "snapshot_timestamp_ms": now,
        "open_interest": [1234],
        "open_interest_timestamps_ms": [now - 1_000],
    })

    assert result["open_interest"]["state"] == "FRESH"
    assert result["open_interest"]["count"] == 1
    assert "change_pct" not in result["open_interest"]


def test_missing_or_unstamped_liquidations_are_unavailable_not_zero_signal():
    now = 1_700_000_000_000
    result = build_shared_market_evidence({
        "snapshot_timestamp_ms": now,
        "liquidation_events": [
            {"timestamp_ms": now - 2_000_000, "notional": 10_000, "side": "BUY"},
            {"notional": 5_000, "side": "SELL"},
        ],
    })

    assert result["liquidations"]["state"] == "UNAVAILABLE"
    assert result["liquidations"]["event_count"] == 0
