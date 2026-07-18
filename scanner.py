import ccxt
import logging
import os
from universe_engine import select_symbols

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
symbols, universe_stats = select_symbols(
    markets=markets,
    suffix="/USDT:USDT",
    require_active=True,
    require_swap=False,
)

backend = getattr(ccxt, "BACKEND", "unknown")
if backend == "mock":
    allow_mock = os.getenv("ATLAS_ALLOW_MOCK", "0").strip().lower() in {"1", "true", "yes"}
    if not allow_mock:
        raise RuntimeError(
            "ccxt mock backend aktif. Canli tarama icin pip install ccxt yapin. "
            "Sadece test/offline icin ATLAS_ALLOW_MOCK=1 ile devam edin."
        )
    logger.warning(
        "ccxt mock backend aktif (ATLAS_ALLOW_MOCK=1). Sonuclar test/offline verisine dayanir."
    )

logger.info(
    "Tarama havuzu | toplam=%s kalan=%s suffix_elendi=%s inactive_elendi=%s",
    universe_stats["total_markets"],
    universe_stats["kept"],
    universe_stats["skipped_suffix"],
    universe_stats["skipped_inactive"],
)

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
