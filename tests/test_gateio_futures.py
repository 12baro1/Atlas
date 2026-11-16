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
            return [{"time":1700000000,"open_interest":"1234"}]
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


def test_gate_ticker_open_interest_and_funding():
    ex = FakeGate()
    ex.load_markets()
    assert ex.fetch_ticker("BTC/USDT:USDT")["last"] == "101"
    assert ex.fetch_open_interest("BTC/USDT:USDT")["openInterestAmount"] == 0.1234
    assert ex.fetch_funding_rate_history("BTC/USDT:USDT")[0]["fundingRate"] == 0.0001
