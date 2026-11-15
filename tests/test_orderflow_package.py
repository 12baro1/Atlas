from strategies.orderflow.analytics import build_cvd, build_footprint, absorption_evidence, liquidity_walls
from strategies.orderflow.websocket_collector import BybitPublicStream


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


def test_websocket_collector_parses_orderbook_trades_and_liquidations():
    stream = BybitPublicStream("BTC/USDT:USDT")
    stream._consume({"topic": "orderbook.50.BTCUSDT", "type": "snapshot",
                     "data": {"ts": 1000, "b": [["99", "2"]], "a": [["101", "3"]]}})
    stream._consume({"topic": "publicTrade.BTCUSDT", "data": [
        {"T": 1100, "p": "100", "v": "2", "S": "Buy", "i": "t1"}]})
    stream._consume({"topic": "allLiquidation.BTCUSDT", "data": [
        {"T": 1200, "p": "100", "v": "1", "S": "Sell"}]})
    result = stream.snapshot(1300)
    assert result["orderbook"]["bids"] == [(99.0, 2.0)]
    assert result["recent_trades"][0]["side"] == "BUY"
    assert result["liquidation_events"][0]["notional"] == 100



def test_footprint_directional_confirmation_uses_executed_notional():
    from strategies.orderflow.analytics import footprint_directional_evidence

    footprint = build_footprint([
        {"price": 100, "size": 2, "side": "BUY"},
        {"price": 100, "size": 1, "side": "SELL"},
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
    import strategy_lab
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

    monkeypatch.setattr(strategy_lab, "_ORDERBOOK_ENGINE", FakeOrderbookEngine())
    monkeypatch.setattr(strategy_lab, "_atr", lambda candles: 2.0)
    monkeypatch.setattr(strategy_lab, "_candle_quality", lambda candle: {
        "body_ratio": 0.60, "close_location": 0.75,
    })
    monkeypatch.setattr(strategy_lab, "_current_price", lambda data: data["current_price"])
    monkeypatch.setattr(strategy_lab, "_valid_plan", lambda *args, **kwargs: {
        "strategy_id": "orderflow_momentum", "direction": args[0],
        "entry": args[1], "stop_loss": args[2], "reasons": [],
    })
    monkeypatch.setattr(strategy_lab, "_entry_reference", lambda data: {})
    monkeypatch.setattr(strategy_lab, "_structure_candle_sets", lambda data: [])
    monkeypatch.setattr(strategy_lab, "displacement", lambda candles, atr: 1.0)
    monkeypatch.setattr(strategy_lab, "cumulative_volume_delta", lambda batches: {
        "state": "UNAVAILABLE",
    })
    monkeypatch.setattr(strategy_lab, "build_orderflow_evidence", lambda trades, book, candles, liquidations: {
        "footprint": build_footprint(trades),
        "cvd": {"state": "AVAILABLE"},
        "liquidity_walls": {"state": "AVAILABLE"},
        "liquidations": {"state": "UNAVAILABLE"},
    })

    trades = [
        {"timestamp_ms": 100000, "price": 100.0, "size": 1.0, "side": "BUY"}
        for _ in range(15)
    ] + [
        {"timestamp_ms": 100000, "price": 100.0, "size": 1.0, "side": "SELL"}
        for _ in range(5)
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
