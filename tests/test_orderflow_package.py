from strategies.orderflow.analytics import build_cvd, build_footprint, absorption_evidence, liquidity_walls
from strategies.orderflow.gateio_public_stream import GatePublicStream


def test_cvd_uses_timestamped_aggressor_notional():
    result = build_cvd([
        {"timestamp_ms": 2000, "price": 10, "size": 2, "side": "BUY"},
        {"timestamp_ms": 1000, "price": 10, "size": 1, "side": "SELL"},
    ])
    assert result["state"] == "AVAILABLE"
    assert result["trade_count"] == 2
    assert result["net_delta"] == 10
    assert result["series"][0]["timestamp_ms"] == 1000


def test_footprint_aggregates_executed_notional_by_price():
    result = build_footprint([
        {"price": 100, "size": 2, "side": "BUY"},
        {"price": 100, "size": 1, "side": "SELL"},
    ])
    assert result["state"] == "AVAILABLE"
    assert result["levels"]["100"]["buy_notional"] == 200
    assert result["levels"]["100"]["sell_notional"] == 100


def test_absorption_is_explicitly_labeled_as_proxy():
    class Candle:
        open = 100
        close = 99
    result = absorption_evidence([
        {"timestamp_ms": 1, "price": 100, "size": 3, "side": "BUY"},
        {"timestamp_ms": 2, "price": 99, "size": 1, "side": "SELL"},
    ], [Candle()])
    assert result["classification"] == "BUYER_FLOW_ABSORBED_PROXY"
    assert "not directly observable" in result["disclaimer"]


def test_liquidity_walls_are_displayed_depth_notional():
    result = liquidity_walls({"bids": [[99, 2]], "asks": [[101, 3]]})
    assert result["state"] == "AVAILABLE"
    assert result["bids"][0]["notional"] == 198
    assert "may be cancelled" in result["disclaimer"]


def test_gateio_public_stream_parses_and_filters_liquidations():
    stream = GatePublicStream("BTC/USDT:USDT")
    stream._consume({
        "channel": "futures.public_liquidates",
        "event": "update",
        "time_ms": 1700000001000,
        "result": [
            {"contract": "BTC_USDT", "price": "60000", "size": "-0.2", "time": 1700000000000},
            {"contract": "ETH_USDT", "price": "3000", "size": "1", "time": 1700000000000},
        ],
    })
    snapshot = stream.snapshot(now_ms=1700000001000)
    assert len(snapshot["liquidation_events"]) == 1
    assert snapshot["liquidation_events"][0]["symbol"] == "BTC"
    assert snapshot["liquidation_events"][0]["side"] == "SELL"
    assert snapshot["liquidation_events"][0]["order_side"] == "SELL"
    assert snapshot["liquidation_events"][0]["position_side"] == "LONG"
    assert snapshot["liquidation_events_source"] == "GATEIO_FUTURES_PUBLIC_LIQUIDATES_WS"



def test_footprint_directional_confirmation_uses_executed_notional():
    from strategies.orderflow.analytics import footprint_directional_evidence

    footprint = build_footprint([
        {"price": 100, "size": 2, "side": "BUY"},
        {"price": 100, "size": 1, "side": "SELL"},
        {"price": 101, "size": 2, "side": "BUY"},
        {"price": 101, "size": 1, "side": "SELL"},
        {"price": 102, "size": 2, "side": "BUY"},
        {"price": 102, "size": 1, "side": "SELL"},
    ])
    assert footprint_directional_evidence(footprint, "LONG")["confirmed"] is True
    assert footprint_directional_evidence(footprint, "SHORT")["confirmed"] is False


def test_nearby_oversized_opposing_wall_blocks_setup():
    from strategies.orderflow.analytics import opposing_liquidity_wall

    book = {
        "bids": [[99, 1], [98, 1], [97, 1]],
        "asks": [[101, 20], [102, 1], [103, 1]],
    }
    result = opposing_liquidity_wall(book, "LONG", entry=100.8, atr=2.0)
    assert result["state"] == "AVAILABLE"
    assert result["blocking"] is True
    assert result["distance_atr"] <= 0.20
    assert result["size_multiple"] >= 2.5


def test_liquidation_pressure_requires_material_real_event_imbalance():
    from strategies.orderflow.analytics import liquidation_pressure

    trades = [{"price": 100, "size": 1, "side": "BUY"} for _ in range(10)]
    events = [
        {"side": "BUY", "notional": 180, "timestamp_ms": 1000},
        {"side": "SELL", "notional": 10, "timestamp_ms": 1000},
    ]
    result = liquidation_pressure(events, trades)
    assert result["state"] == "AVAILABLE"
    assert result["confirmed"] is True
    assert result["direction"] == "LONG"
    assert result["dominant_share"] > 0.9

    weak = liquidation_pressure(
        [{"side": "SELL", "notional": 1, "timestamp_ms": 1000}],
        trades,
    )
    assert weak["confirmed"] is False


def test_orderflow_generator_uses_footprint_and_blocks_nearby_wall(monkeypatch):
    from strategies.orderflow import strategy as orderflow
    from strategies.orderflow.strategy import generate

    class Candle:
        open = 99.0
        high = 101.0
        low = 98.5
        close = 100.5
        volume = 100.0

    class FakeOrderbookEngine:
        MARKET_MAX_SPREAD_PCT = 0.10

        def analyze(self, *args, **kwargs):
            return {
                "active": True, "trade_flow_active": True, "imbalance": 0.25,
                "trade_delta": 0.25, "spread_pct": 0.01, "trade_count": 20,
                "bid_notional": 5000.0, "ask_notional": 3000.0,
            }

    monkeypatch.setattr(orderflow, "_ORDERBOOK_ENGINE", FakeOrderbookEngine())
    monkeypatch.setattr(orderflow, "_atr", lambda candles: 2.0)
    monkeypatch.setattr(orderflow, "_candle_quality", lambda candle: {
        "body_ratio": 0.60, "close_location": 0.75,
    })
    monkeypatch.setattr(orderflow, "_current_price", lambda data: data["current_price"])
    monkeypatch.setattr(orderflow, "_entry_reference", lambda data: {})
    monkeypatch.setattr(orderflow, "displacement", lambda candles, atr: 1.0)
    monkeypatch.setattr(orderflow, "cumulative_volume_delta", lambda batches: {
        "state": "UNAVAILABLE",
    })
    monkeypatch.setattr(orderflow, "build_orderflow_evidence", lambda trades, book, candles, liquidations: {
        "footprint": build_footprint(trades),
        "cvd": {"state": "AVAILABLE"},
        "liquidity_walls": {"state": "AVAILABLE"},
        "liquidations": {"state": "UNAVAILABLE"},
    })

    trades = [
        {"timestamp_ms": 100000, "price": price, "size": 1.0, "side": "BUY"}
        for price in (100.0, 100.1, 100.2) for _ in range(5)
    ] + [
        {"timestamp_ms": 100000, "price": price, "size": 1.0, "side": "SELL"}
        for price, count in ((100.0, 2), (100.1, 2), (100.2, 1)) for _ in range(count)
    ]
    data = {
        "orderbook": {
            "bids": [[99, 1], [98, 1], [97, 1]],
            "asks": [[110, 1], [111, 1], [112, 1]],
        },
        "15m": [Candle()],
        "snapshot_timestamp_ms": 100000,
        "orderbook_timestamp_ms": 100000,
        "recent_trades_timestamp_ms": 100000,
        "recent_trades": trades,
        "trade_flow_history": [],
        "liquidation_events": [],
        "current_price": 100.0,
    }

    plan = generate(data)
    assert plan is not None
    assert plan["orderflow_metrics"]["footprint_confirmation"]["confirmed"] is True

    data["current_price"] = 100.8
    data["orderbook"]["asks"] = [[101, 20], [102, 1], [103, 1]]
    assert generate(data) is None


def test_orderflow_rejects_stale_shared_book_or_trade_evidence():
    from strategies.orderflow.strategy import generate

    assert generate({
        "shared_market_evidence": {
            "sources": {
                "orderbook": {"state": "STALE"},
                "trades": {"state": "FRESH"},
            }
        },
        "orderbook": {"bids": [[99, 1]], "asks": [[101, 1]]},
        "recent_trades": [{"price": 100, "size": 1, "side": "BUY"}],
    }) is None



def test_gate_websocket_trade_size_is_normalized_by_contract_multiplier():
    stream = GatePublicStream("BTC/USDT:USDT")
    stream.set_contract_size(0.001)
    stream._consume({
        "channel": "futures.trades",
        "event": "update",
        "time_ms": 1700000001000,
        "result": [{
            "contract": "BTC_USDT", "create_time_ms": 1700000000000,
            "size": "100", "price": "60000", "id": "normalized-trade",
        }],
    })
    snapshot = stream.snapshot(now_ms=1700000001000)
    assert snapshot["recent_trades"][0]["raw_contract_size"] == 100
    assert snapshot["recent_trades"][0]["size"] == 0.1
    assert snapshot["recent_trades"][0]["amount"] == 0.1


def test_gate_orderbook_updates_replay_from_rest_nonce_and_normalize_sizes():
    stream = GatePublicStream("BTC/USDT:USDT")
    stream.set_contract_size(0.001)
    stream._consume({
        "channel": "futures.order_book_update", "event": "update",
        "time_ms": 1700000001000,
        "result": {
            "U": 11, "u": 12, "t": 1700000001000,
            "b": [{"p": "60000", "s": "200"}],
            "a": [{"p": "60010", "s": "0"}],
        },
    })
    assert stream.set_orderbook_snapshot({
        "nonce": 10, "timestamp": 1700000000000,
        "bids": [[59990, 1.0]], "asks": [[60010, 0.5]],
    }) is True
    book = stream.snapshot(now_ms=1700000001000)["orderbook"]
    assert book["nonce"] == 12
    assert [60000.0, 0.2] in book["bids"]
    assert not any(price == 60010 for price, _ in book["asks"])


def test_gate_orderbook_gap_fails_closed_until_resnapshot():
    stream = GatePublicStream("BTC/USDT:USDT")
    assert stream.set_orderbook_snapshot({
        "nonce": 10, "bids": [[100, 1]], "asks": [[101, 1]],
    }) is True
    stream._consume({
        "channel": "futures.order_book_update", "event": "update",
        "time_ms": 1700000001000,
        "result": {"U": 15, "u": 16, "t": 1700000001000, "b": [], "a": []},
    })
    assert stream.snapshot(now_ms=1700000001000)["orderbook"] is None


def test_gate_contract_stats_produces_timestamped_normalized_oi():
    stream = GatePublicStream("BTC/USDT:USDT")
    stream.set_contract_size(0.001)
    stream._consume({
        "channel": "futures.contract_stats", "event": "update",
        "time_ms": 1700000001000,
        "result": [
            {"time": 1700000000, "open_interest": "100"},
            {"time": 1700000060, "open_interest": "120"},
        ],
    })
    oi = stream.snapshot(now_ms=1700000061000)["open_interest"]
    assert [row["timestamp"] for row in oi] == [1700000000000, 1700000060000]
    assert [row["openInterestAmount"] for row in oi] == [0.1, 0.12]
