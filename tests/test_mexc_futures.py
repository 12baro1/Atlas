from mexc_futures import MexcFuturesExchange


class FakeMexc(MexcFuturesExchange):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append((path, params or {}))
        if path == "/api/v1/contract/detail":
            return [
                {"symbol": "BTC_USDT", "baseCoin": "BTC", "quoteCoin": "USDT",
                 "settleCoin": "USDT", "contractSize": 0.001, "state": 0,
                 "priceScale": 1, "volScale": 0, "minVol": 1},
                {"symbol": "BTC_USD", "baseCoin": "BTC", "quoteCoin": "USD",
                 "settleCoin": "BTC", "contractSize": 1, "state": 0},
                {"symbol": "OLD_USDT", "baseCoin": "OLD", "quoteCoin": "USDT",
                 "settleCoin": "USDT", "contractSize": 1, "state": 3},
            ]
        if path.endswith("/kline/BTC_USDT"):
            return {"time": [1700000000], "open": [100], "high": [102],
                    "low": [99], "close": [101], "vol": [500]}
        if path.endswith("/depth/BTC_USDT"):
            return {"bids": [[100, 20, 2]], "asks": [[101, 30, 3]],
                    "timestamp": 1700000000000, "version": 10}
        if path.endswith("/deals/BTC_USDT"):
            return [{"p": 100, "v": 50, "T": 1, "t": 1700000000000}]
        if path == "/api/v1/contract/ticker":
            return {"symbol": "BTC_USDT", "lastPrice": 101, "holdVol": 1000,
                    "timestamp": 1700000000000, "volume24": 2000, "amount24": 202000}
        if path.endswith("/funding_rate/BTC_USDT"):
            return {"fundingRate": 0.0001, "timestamp": 1700000000000}
        if path == "/api/v1/contract/funding_rate/history":
            return {"resultList": [{"settleTime": 1699990000000, "fundingRate": 0.0002}]}
        raise AssertionError(f"Unexpected MEXC endpoint: {path}")


def test_market_metadata_maps_only_active_usdt_perpetuals():
    exchange = FakeMexc()
    markets = exchange.load_markets()
    assert list(markets) == ["BTC/USDT:USDT"]
    assert markets["BTC/USDT:USDT"]["swap"] is True
    assert exchange.market_id("BTC/USDT:USDT") == "BTC_USDT"


def test_ohlcv_maps_seconds_to_milliseconds_and_contract_volume():
    exchange = FakeMexc()
    exchange.load_markets()
    rows = exchange.fetch_ohlcv("BTC/USDT:USDT", "15m", limit=10)
    assert rows == [[1700000000000, 100.0, 102.0, 99.0, 101.0, 0.5]]
    path, params = exchange.calls[-1]
    assert path.endswith("/kline/BTC_USDT")
    assert params["interval"] == "Min15"


def test_orderbook_and_trades_normalize_contract_quantity():
    exchange = FakeMexc()
    exchange.load_markets()
    book = exchange.fetch_order_book("BTC/USDT:USDT", limit=20)
    trades = exchange.fetch_trades("BTC/USDT:USDT", limit=10)
    assert book["bids"] == [[100.0, 0.02]]
    assert book["asks"] == [[101.0, 0.03]]
    assert trades[0]["side"] == "buy"
    assert trades[0]["amount"] == 0.05


def test_open_interest_uses_only_timestamped_observed_snapshots():
    exchange = FakeMexc()
    exchange.load_markets()
    history = exchange.fetch_open_interest_history("BTC/USDT:USDT", limit=10)
    assert len(history) == 1
    assert history[0]["openInterestAmount"] == 1.0
    snapshot = exchange.fetch_open_interest("BTC/USDT:USDT")
    assert snapshot["openInterestAmount"] == 1.0


def test_funding_history_uses_exchange_settlement_timestamps():
    exchange = FakeMexc()
    exchange.load_markets()
    rows = exchange.fetch_funding_rate_history("BTC/USDT:USDT", limit=10)
    assert rows == [{
        "symbol": "BTC/USDT:USDT", "timestamp": 1699990000000,
        "fundingRate": 0.0002,
        "info": {"settleTime": 1699990000000, "fundingRate": 0.0002},
    }]


def test_all_tickers_are_normalized_for_the_active_market_universe():
    exchange = FakeMexc()
    exchange.load_markets()
    tickers = exchange.fetch_tickers(["BTC/USDT:USDT"])
    assert list(tickers) == ["BTC/USDT:USDT"]
    assert tickers["BTC/USDT:USDT"]["last"] == 101
    assert tickers["BTC/USDT:USDT"]["baseVolume"] == 2.0
