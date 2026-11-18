import requests

from gateio_futures import GateFuturesExchange


class FakeGate(GateFuturesExchange):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append((path, params or {}))
        if path == "/futures/usdt/contracts":
            return [{"name":"BTC_USDT","quanto_multiplier":"0.0001","order_size_min":1}]
        if path == "/futures/usdt/candlesticks":
            return [{"t":1700000000,"o":"100","h":"102","l":"99","c":"101","v":"5"}]
        if path == "/futures/usdt/order_book":
            return {"id":1,"t":1700000000000,"bids":[{"p":"100","s":2}],"asks":[{"p":"101","s":3}]}
        if path == "/futures/usdt/trades":
            return [{"id":1,"create_time_ms":1700000000000,"price":"100","size":2}]
        if path == "/futures/usdt/tickers":
            return [{"contract":"BTC_USDT","last":"101","high_24h":"105","low_24h":"95"}]
        if path == "/futures/usdt/contract_stats":
            return [{"time":1700000000,"open_interest":"1234","open_interest_usd":123400.0}]
        if path == "/futures/usdt/funding_rate":
            return [{"t":1700000000,"r":"0.0001"}]
        raise AssertionError(path)


def test_gate_market_symbols_and_ohlcv_normalization():
    ex = FakeGate()
    assert list(ex.load_markets()) == ["BTC/USDT:USDT"]
    assert ex.market_id("BTC/USDT:USDT") == "BTC_USDT"
    assert ex.fetch_ohlcv("BTC/USDT:USDT", "15m") == [
        [1700000000000, 100.0, 102.0, 99.0, 101.0, 0.0005]
    ]


def test_gate_orderbook_and_trades_normalization():
    ex = FakeGate()
    ex.load_markets()
    book = ex.fetch_order_book("BTC/USDT:USDT")
    trades = ex.fetch_trades("BTC/USDT:USDT")
    assert book["bids"] == [[100.0, 0.0002]]
    assert book["asks"] == [[101.0, 0.0003]]
    assert trades[0]["side"] == "buy"
    assert trades[0]["amount"] == 0.0002


def test_gate_rest_trade_timestamps_normalize_seconds_and_preserve_milliseconds():
    class SecondsGate(FakeGate):
        def _get(self, path, params=None):
            if path == "/futures/usdt/trades":
                return [
                    {"id": 1, "create_time_ms": 1700000000, "price": "100", "size": 2},
                    {"id": 2, "create_time_ms": 1700000001000, "price": "101", "size": -1},
                ]
            return super()._get(path, params)

    ex = SecondsGate()
    ex.load_markets()
    trades = ex.fetch_trades("BTC/USDT:USDT", since=1700000000000)
    assert [trade["timestamp"] for trade in trades] == [1700000000000, 1700000001000]
    assert [trade["side"] for trade in trades] == ["buy", "sell"]


def test_gate_ticker_open_interest_and_funding():
    ex = FakeGate()
    ex.load_markets()
    assert ex.fetch_ticker("BTC/USDT:USDT")["last"] == "101"
    assert ex.fetch_open_interest("BTC/USDT:USDT")["openInterestAmount"] == 0.1234
    assert ex.fetch_funding_rate_history("BTC/USDT:USDT")[0]["fundingRate"] == 0.0001


def test_gate_open_interest_history_exposes_timestamped_amount_and_usd_value():
    ex = FakeGate()
    ex.load_markets()
    rows = ex.fetch_open_interest_history("BTC/USDT:USDT", timeframe="1h", limit=10)
    assert rows[0]["timestamp"] == 1700000000000
    assert rows[0]["openInterestAmount"] == 0.1234
    assert rows[0]["openInterestValue"] == 123400.0


def test_gate_open_interest_snapshot_uses_exchange_timestamp_and_usd_value():
    ex = FakeGate()
    ex.load_markets()
    snapshot = ex.fetch_open_interest("BTC/USDT:USDT")
    assert snapshot["timestamp"] == 1700000000000
    assert snapshot["openInterestAmount"] == 0.1234
    assert snapshot["openInterestValue"] == 123400.0



def test_gate_load_markets_excludes_nontrading_contract_statuses():
    class StatusGate(FakeGate):
        def _get(self, path, params=None):
            if path == "/futures/usdt/contracts":
                return [
                    {"name": "BTC_USDT", "quanto_multiplier": "0.0001", "status": "trading"},
                    {"name": "PRE_USDT", "quanto_multiplier": "1", "status": "prelaunch"},
                    {"name": "DEL_USDT", "quanto_multiplier": "1", "status": "delisted"},
                    {"name": "BRK_USDT", "quanto_multiplier": "1", "status": "circuit_breaker"},
                    {"name": "EXIT_USDT", "quanto_multiplier": "1", "status": "delisting"},
                    {"name": "OLD_USDT", "quanto_multiplier": "1", "in_delisting": True},
                ]
            return super()._get(path, params)

    ex = StatusGate()
    markets = ex.load_markets()
    assert list(markets) == ["BTC/USDT:USDT"]
    assert markets["BTC/USDT:USDT"]["active"] is True
    assert markets["BTC/USDT:USDT"]["status"] == "trading"


def test_gate_open_interest_history_is_sorted_oldest_to_newest():
    class ReverseHistoryGate(FakeGate):
        def _get(self, path, params=None):
            if path == "/futures/usdt/contract_stats":
                return [
                    {"time": 1700003600, "open_interest": "2000", "open_interest_usd": 200000.0},
                    {"time": 1700000000, "open_interest": "1000", "open_interest_usd": 100000.0},
                ]
            return super()._get(path, params)

    ex = ReverseHistoryGate()
    ex.load_markets()
    rows = ex.fetch_open_interest_history("BTC/USDT:USDT", timeframe="1h", limit=10)
    assert [row["timestamp"] for row in rows] == [1700000000000, 1700003600000]
    assert [row["openInterestAmount"] for row in rows] == [0.1, 0.2]



def test_gate_get_retries_transient_network_errors(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class FlakySession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise requests.Timeout("temporary Gate.io timeout")
            return Response()

    monkeypatch.setattr("gateio_futures.time.sleep", lambda _delay: None)
    session = FlakySession()
    exchange = GateFuturesExchange(
        session=session,
        max_retries=3,
        retry_backoff_seconds=0,
    )

    assert exchange._get("/futures/usdt/contracts") == {"ok": True}
    assert session.calls == 3


def test_gate_get_does_not_retry_non_transient_http_errors(monkeypatch):
    class BadResponse:
        status_code = 400

        def raise_for_status(self):
            raise requests.HTTPError("bad request", response=self)

    class BadSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return BadResponse()

    monkeypatch.setattr("gateio_futures.time.sleep", lambda _delay: None)
    session = BadSession()
    exchange = GateFuturesExchange(
        session=session,
        max_retries=3,
        retry_backoff_seconds=0,
    )

    import pytest
    with pytest.raises(requests.HTTPError):
        exchange._get("/futures/usdt/contracts")
    assert session.calls == 1
