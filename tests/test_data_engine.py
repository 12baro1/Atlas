import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_engine


class FakeExchange:
    def __init__(self, rows, now_ms):
        self.rows = rows
        self.now_ms = now_ms

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return self.rows

    def parse_timeframe(self, timeframe):
        return {"15m": 900, "1h": 3600, "4h": 14400}[timeframe]

    def milliseconds(self):
        return self.now_ms


def test_fetch_discards_current_incomplete_candle(monkeypatch):
    now = 10_000_000
    rows = [
        [now - 1_800_000, 100, 103, 99, 102, 10],
        [now, 102, 105, 101, 104, 12],
    ]
    monkeypatch.setattr(data_engine, "exchange", FakeExchange(rows, now))
    candles = data_engine._fetch("BTC/USDT:USDT", "15m", 100)
    assert [c.time for c in candles] == [now - 1_800_000]


def test_fetch_discards_invalid_duplicate_and_out_of_order_rows(monkeypatch):
    now = 10_000_000
    rows = [
        [now - 3_600_000, 100, 103, 99, 102, 10],
        [now - 3_600_000, 102, 105, 101, 104, 12],
        [now - 7_200_000, 102, 105, 101, 104, 12],
        [now - 1_800_000, 100, float("nan"), 99, 102, 10],
        [now - 1_800_000, 100, 103, 99, 102, 10],
    ]
    monkeypatch.setattr(data_engine, "exchange", FakeExchange(rows, now))
    candles = data_engine._fetch("BTC/USDT:USDT", "15m", 100)
    assert len(candles) == 2
    assert candles[0].time < candles[1].time


def test_fetch_keeps_valid_closed_candle_with_zero_volume(monkeypatch):
    now = 10_000_000
    rows = [[now - 1_800_000, 100, 103, 99, 102, 0]]
    monkeypatch.setattr(data_engine, "exchange", FakeExchange(rows, now))
    candles = data_engine._fetch("BTC/USDT:USDT", "15m", 100)
    assert len(candles) == 1
    assert candles[0].volume == 0


def test_get_market_data_tracks_per_feed_provenance_and_snapshot_timestamps(monkeypatch):
    from core.candle import Candle
    from strategies.orderflow.websocket_collector import MexcPublicStream

    now = 1_700_000_000_000

    class FakeExchange:
        def milliseconds(self):
            return now

        def fetch_order_book(self, _symbol, limit=50):
            return {"bids": [[99, 2]], "asks": [[101, 2]], "timestamp": now - 1_000}

        def fetch_trades(self, _symbol, limit=200):
            return [
                {"timestamp": now - 1_000, "price": 100.0, "amount": 1.0, "side": "buy"}
                for _ in range(20)
            ]

        def fetch_open_interest_history(self, *_args, **_kwargs):
            return []

        def fetch_open_interest(self, _symbol):
            return {"openInterestValue": 1234.0, "timestamp": now - 2_000}

        def fetch_funding_rate_history(self, _symbol, limit=100):
            return [{"timestamp": now - 3_000, "fundingRate": 0.0001}]

        def fetch_ticker(self, _symbol):
            return {"last": 100.0, "timestamp": now}

    class FakeStream:
        def start(self):
            return True

        def snapshot(self, _now, wait_ms=None):
            # A connected socket with no topic data must not be reported as a
            # live order book/trade/liquidation feed.
            return {
                "connected": True,
                "source": "MEXC_FUTURES_PUBLIC_WEBSOCKET",
                "orderbook": None,
                "recent_trades": [],
                "trade_flow_history": [],
                "liquidation_events": [],
            }

    monkeypatch.setenv("ATLAS_MICROSTRUCTURE_ARCHIVE_ENABLED", "0")
    monkeypatch.setattr(data_engine, "exchange", FakeExchange())
    monkeypatch.setattr(data_engine, "fetch_candles", lambda *_args, **_kwargs: [
        Candle(time=now - 3_600_000, open=100, high=102, low=98, close=101, volume=10)
    ])
    monkeypatch.setattr(data_engine, "configured_sector_peers", lambda _symbol: [])
    monkeypatch.setattr(MexcPublicStream, "for_symbol", classmethod(lambda cls, _symbol: FakeStream()))

    data = data_engine.get_market_data("BTC/USDT:USDT", force_refresh=True)

    assert data["data_provenance"]["orderbook"] == "MEXC_REST"
    assert data["data_provenance"]["recent_trades"] == "MEXC_REST"
    assert data["data_provenance"]["open_interest"] == "MEXC_REST_SNAPSHOT"
    assert data["open_interest_timestamps_ms"] == [now - 2_000]
    assert data["funding_rate_timestamps_ms"] == [now - 3_000]
    assert data["shared_market_evidence"]["sources"]["orderbook"]["state"] == "FRESH"
    assert data["shared_market_evidence"]["sources"]["trades"]["state"] == "FRESH"
    assert data["shared_market_evidence"]["open_interest"]["count"] == 1
    assert "change_pct" not in data["shared_market_evidence"]["open_interest"]
    assert data["shared_market_evidence"]["funding"]["state"] == "FRESH"
    assert data["microstructure_source"] == "REST_FALLBACK"
