"""Minimal local ccxt compatibility layer for offline Atlas tests."""


class bybit:
    """Small subset of ccxt.bybit used by the repository smoke tests."""

    def __init__(self, config=None):
        self.config = config or {}

    def load_markets(self):
        return {
            "BTC/USDT:USDT": {},
            "ETH/USDT:USDT": {},
        }

    def fetch_ohlcv(self, symbol, timeframe="15m", since=None, limit=100):
        base_time = 1_700_000_000_000
        step_ms = self._timeframe_to_ms(timeframe)
        base_price = 100_000.0 if symbol.startswith("BTC") else 3_000.0
        rows = []

        for i in range(limit or 100):
            wave = (i % 20) - 10
            trend = i * 3.5
            open_price = base_price + trend + (wave * 12)
            close_price = open_price + (18 if i % 2 == 0 else -14)
            high = max(open_price, close_price) + 35 + (i % 5)
            low = min(open_price, close_price) - 35 - (i % 7)
            volume = 100 + (i % 30)
            rows.append([
                base_time + (i * step_ms),
                float(open_price),
                float(high),
                float(low),
                float(close_price),
                float(volume),
            ])

        return rows

    def _timeframe_to_ms(self, timeframe):
        mapping = {
            "15m": 15 * 60 * 1000,
            "4h": 4 * 60 * 60 * 1000,
            "1d": 24 * 60 * 60 * 1000,
            "1w": 7 * 24 * 60 * 60 * 1000,
        }
        return mapping.get(timeframe, mapping["15m"])
