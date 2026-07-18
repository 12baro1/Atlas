"""Minimal local ccxt compatibility layer for offline Atlas tests."""


class bybit:
    """Small subset of ccxt.bybit used by the repository smoke tests."""

    def __init__(self, config=None):
        self.config = config or {}

    def load_markets(self):
        # Offline test ortamında yalnızca BTC/ETH ile sınırlamamak için
        # tipik USDT perpetual sembollerinin deterministik bir listesini döndür.
        symbols = [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT",
            "XRP/USDT:USDT",
            "BNB/USDT:USDT",
            "DOGE/USDT:USDT",
            "ADA/USDT:USDT",
            "AVAX/USDT:USDT",
            "TRX/USDT:USDT",
            "LINK/USDT:USDT",
            "DOT/USDT:USDT",
            "MATIC/USDT:USDT",
            "LTC/USDT:USDT",
            "BCH/USDT:USDT",
            "UNI/USDT:USDT",
            "NEAR/USDT:USDT",
            "ATOM/USDT:USDT",
            "APT/USDT:USDT",
            "OP/USDT:USDT",
            "ARB/USDT:USDT",
            "SUI/USDT:USDT",
            "SEI/USDT:USDT",
            "TIA/USDT:USDT",
            "PEPE/USDT:USDT",
            "WIF/USDT:USDT",
            "INJ/USDT:USDT",
            "AAVE/USDT:USDT",
            "FIL/USDT:USDT",
            "ETC/USDT:USDT",
            "XLM/USDT:USDT",
            "HBAR/USDT:USDT",
            "IMX/USDT:USDT",
            "RNDR/USDT:USDT",
            "RUNE/USDT:USDT",
            "GRT/USDT:USDT",
            "PYTH/USDT:USDT",
        ]
        return {
            symbol: {
                "active": True,
                "swap": True,
                "quote": "USDT",
            }
            for symbol in symbols
        }

    def fetch_ohlcv(self, symbol, timeframe="15m", since=None, limit=100):
        base_time = 1_700_000_000_000
        step_ms = self._timeframe_to_ms(timeframe)
        symbol_seed = sum(ord(char) for char in symbol)
        if symbol.startswith("BTC"):
            base_price = 100_000.0
        elif symbol.startswith("ETH"):
            base_price = 3_000.0
        else:
            base_price = 50.0 + float(symbol_seed % 4_000)
        rows = []

        for i in range(limit or 100):
            wave = (i % 20) - 10
            trend = i * (1.8 + ((symbol_seed % 17) / 20))
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
