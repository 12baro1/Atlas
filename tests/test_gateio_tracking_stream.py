import json
from unittest.mock import Mock

import pytest

from gateio_tracking_stream import GateTrackingStream
from telegram_tracking import evaluate_live
from tests.test_tracking_history import BTC, START, plan
from tracking_history import EvidenceMissing, TradeGroup


def receive(stream, trades):
    stream._consume({
        "channel": "futures.trades",
        "event": "update",
        "result": [
            {"contract": "BTC_USDT", "id": index, "create_time_ms": stamp, "price": str(price), "size": 1}
            for index, (stamp, price) in enumerate(trades, start=1)
        ],
    }, {"BTC_USDT"})


def test_stream_tracks_entry_and_each_partial_target_before_five_minute_close():
    stream = GateTrackingStream()
    stream.follow([BTC])
    receive(stream, [
        (START - 2000, 101), (START + 100, 100), (START + 1100, 110),
        (START + 2100, 120), (START + 3100, 105), (START + 4100, 130), (START + 5100, 129),
    ])
    state = "WAITING"
    tracked = plan(opened_at=START, entry_reached=False, entry_reached_at=None, partial_weights=[0.5, 0.3, 0.2])
    for elapsed, target_levels, expected_state in [
        (3000, [], "ACTIVE"), (4000, [1], "ACTIVE"),
        (5000, [1, 2], "ACTIVE"), (6000, [1, 2], "ACTIVE"), (7000, [1, 2, 3], "CLOSED"),
    ]:
        state, tracked = evaluate_live(BTC, state, json.dumps(tracked), START + elapsed, stream.trade_range)
        assert state == expected_state
        assert tracked.get("tps_hit", []) == target_levels
        if target_levels:
            assert tracked["trailing_stop"] == tracked["entry"]
    assert tracked["status"] == "TP3"


def test_stream_bridges_reconnect_before_processing_new_prices():
    stream = GateTrackingStream()
    stream.follow([BTC])
    receive(stream, [(START + 1100, 105), (START + 2200, 110), (START + 3200, 111)])
    with pytest.raises(EvidenceMissing):
        stream.trade_range(BTC, START, START + 4000)
    fallback = Mock(return_value=[TradeGroup(START + 100, {100}, 1)])
    groups = stream.trade_range(BTC, START, START + 4000, fallback)
    assert [group.time for group in groups] == [START + 100, START + 2200]
    fallback.assert_called_once_with(BTC, START, START + 2000)

    stream._clear("BTC_USDT")
    with pytest.raises(EvidenceMissing):
        stream.trade_range(BTC, START, START + 4000)


def test_socket_groups_same_millisecond_and_waits_for_later_timestamp():
    stream = GateTrackingStream()
    stream.follow([BTC])
    receive(stream, [(START - 2000, 99), (START + 100, 100), (START + 100, 101)])
    assert stream.trade_range(BTC, START, START + 1000) == []
    receive(stream, [(START + 200, 102)])
    [group] = stream.trade_range(BTC, START, START + 1000)
    assert group.prices == {100, 101}


def test_stream_excludes_internal_insurance_fills_from_market_prices():
    stream = GateTrackingStream()
    stream.follow([BTC])
    receive(stream, [(START - 2000, 100), (START + 100, 101)])
    stream._consume({
        "channel": "futures.trades",
        "event": "update",
        "result": [{
            "contract": "BTC_USDT", "id": 3, "create_time_ms": START + 150,
            "price": "80", "size": 1, "is_internal": True,
        }],
    }, {"BTC_USDT"})
    receive(stream, [(START + 200, 102)])
    [group] = stream.trade_range(BTC, START, START + 1000)
    assert group.prices == {101}
