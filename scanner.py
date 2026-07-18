import ccxt
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("atlas.raw_scanner")

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    },
    "enableRateLimit": True
})

markets = exchange.load_markets()

symbols = []

for symbol, meta in markets.items():
    if not symbol.endswith("/USDT:USDT"):
        continue

    if isinstance(meta, dict) and not meta.get("active", True):
        continue

        symbols.append(symbol)

symbols.sort()

logger.info("Toplam Coin: %s", len(symbols))

success = 0
failed = 0
empty = 0

for i, symbol in enumerate(symbols, 1):
    try:
        candles = exchange.fetch_ohlcv(symbol, "15m", limit=1000)

        if len(candles) > 0:
            success += 1
            print(f"[{i}/{len(symbols)}] ✅ {symbol} ({len(candles)} mum)")
        else:
            empty += 1
            print(f"[{i}/{len(symbols)}] ❌ {symbol}")

    except Exception as e:
        failed += 1
        print(f"[{i}/{len(symbols)}] HATA {symbol}: {e}")

logger.info("Tarama bitti | basarili=%s bos=%s hatali=%s", success, empty, failed)
