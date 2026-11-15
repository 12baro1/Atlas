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
