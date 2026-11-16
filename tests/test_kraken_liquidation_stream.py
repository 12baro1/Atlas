"""Tests for public Kraken Futures liquidation event normalization."""
from strategies.orderflow.kraken_liquidation_stream import (
    KrakenLiquidationStream,
    _canonical_base,
)


def test_canonical_base_maps_kraken_xbt_to_btc():
    assert _canonical_base("XBT:USD") == "BTC"
    assert _canonical_base("ETH:USD") == "ETH"


def test_only_exchange_labelled_liquidations_and_terminations_are_emitted():
    stream = KrakenLiquidationStream()
    stream._product_bases = {"PF_XBTUSD": "BTC"}
    stream._consume({
        "feed": "trade_snapshot",
        "product_id": "PF_XBTUSD",
        "trades": [
            {"uid": "normal", "type": "fill", "product_id": "PF_XBTUSD",
             "time": 1000, "price": 60000, "qty": 0.1, "side": "buy"},
            {"uid": "liq-1", "type": "liquidation", "product_id": "PF_XBTUSD",
             "time": 1100, "price": 59900, "qty": 0.25, "side": "sell"},
            {"uid": "term-1", "type": "termination", "product_id": "PF_XBTUSD",
             "time": 1200, "price": 59800, "qty": 0.05, "side": "buy"},
        ],
    })

    assert [event["event_type"] for event in stream._events] == [
        "liquidation", "termination"
    ]
    assert stream._events[0]["symbol"] == "BTC"
    assert stream._events[0]["side"] == "SELL"
    assert stream._events[0]["notional"] == 14975


def test_duplicate_liquidation_uid_is_deduplicated():
    stream = KrakenLiquidationStream()
    stream._product_bases = {"PF_XBTUSD": "BTC"}
    event = {
        "feed": "trade", "uid": "same-id", "type": "liquidation",
        "product_id": "PF_XBTUSD", "time": 1000, "price": 10,
        "qty": 2, "side": "sell",
    }
    stream._consume(event)
    stream._consume(event)
    assert len(stream._events) == 1


def test_snapshot_filters_by_asset_and_age():
    stream = KrakenLiquidationStream()
    stream._product_bases = {"PF_XBTUSD": "BTC", "PF_ETHUSD": "ETH"}
    stream._consume({
        "feed": "trade",
        "uid": "btc-liq",
        "type": "liquidation",
        "product_id": "PF_XBTUSD",
        "time": 100000,
        "price": 60000,
        "qty": 0.1,
        "side": "sell",
    })
    stream._consume({
        "feed": "trade",
        "uid": "eth-liq",
        "type": "liquidation",
        "product_id": "PF_ETHUSD",
        "time": 100000,
        "price": 3000,
        "qty": 1,
        "side": "buy",
    })

    result = stream.snapshot("BTC/USDT:USDT", now_ms=100500)
    assert [event["event_id"] for event in result["events"]] == ["btc-liq"]
    assert result["matched_products"] == 1


def test_unknown_product_and_invalid_event_are_ignored():
    stream = KrakenLiquidationStream()
    stream._product_bases = {"PF_XBTUSD": "BTC"}
    stream._consume({
        "feed": "trade", "uid": "unknown", "type": "liquidation",
        "product_id": "PF_UNKNOWNUSD", "time": 1000, "price": 10,
        "qty": 1, "side": "sell",
    })
    stream._consume({
        "feed": "trade", "uid": "bad-side", "type": "liquidation",
        "product_id": "PF_XBTUSD", "time": 1000, "price": 10,
        "qty": 1, "side": "unknown",
    })
    assert list(stream._events) == []
