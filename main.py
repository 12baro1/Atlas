import ccxt
import logging
import os

from data_engine import get_market_data
from engine import AtlasEngine
from universe_engine import select_symbols

engine = AtlasEngine()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("atlas.scanner")

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
    max_symbols=int(getattr(engine.config, "MAX_SYMBOLS", 0) or 0),
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
    "Sembol secimi | backend=%s toplam=%s kalan=%s suffix_elendi=%s inactive_elendi=%s cap_elendi=%s",
    backend,
    universe_stats["total_markets"],
    universe_stats["kept"],
    universe_stats["skipped_suffix"],
    universe_stats["skipped_inactive"],
    universe_stats["limited"],
)

processed = 0
success = 0
failed = 0
skipped = 0

for index, symbol in enumerate(symbols, start=1):

    try:
        processed += 1
        logger.info("[%s/%s] Analiz basliyor: %s", index, len(symbols), symbol)

        data = get_market_data(symbol)
        logger.info("Veri alindi: %s", data["symbol"])

        result = engine.analyze(data)

        if result is None:
            skipped += 1
            logger.warning("[%s/%s] Sonuc yok, atlandi: %s", index, len(symbols), symbol)
            continue

        success += 1

        analysis = result["analysis"]

        print(f"\n✓ {symbol}")

        if len(analysis["structure"]) > 0:
            print("Son Yapı :", analysis["structure"][-1]["label"])

        print("Liquidity :", len(analysis["liquidity"]))
        print("OrderBlocks :", len(analysis["orderblocks"]))
        print("FVG :", len(analysis["fvg"]))

        print("Signal :", result["signal"]["signal"])
        print("Confidence :", result["signal"]["confidence"])
        print("Grade :", result["signal"]["grade"])
        print("Strength :", result["signal"]["strength"])

        print("Trend :", analysis["trend"]["trend"])

        print("Entry :", analysis["entry"]["direction"])
        print("Entry Price :", analysis["entry"]["entry"])
        print("Stop Loss :", analysis["entry"]["stop_loss"])
        print("Entry Valid :", analysis["entry"]["valid"])
        print("Reason :", analysis["entry"]["reason"])

        print("Confirmed :", analysis["confirmation"]["confirmed"])
        print("Confirm Reason :", analysis["confirmation"]["reason"])

        print("\nMarket Phase Analysis:")
        print("  Phase :", analysis["market_phase"]["phase"])
        print("  Confidence :", analysis["market_phase"]["phase_confidence"], "%")
        print("  Strength :", analysis["market_phase"]["phase_strength"])
        print("  Score :", analysis["market_phase"]["phase_score"])
        print("  MTF Alignment :", analysis["market_phase"]["mtf_alignment"], "%")

        print("Weekly :", analysis["mtf"]["weekly"])
        print("Daily :", analysis["mtf"]["daily"])
        print("H4 :", analysis["mtf"]["h4"])
        print("Entry TF :", analysis["mtf"]["entry"])
        print("MTF Valid :", analysis["mtf"]["valid"])

        print("TP1 :", result["dynamic_tp"]["tp1"])
        print("TP2 :", result["dynamic_tp"]["tp2"])
        print("TP3 :", result["dynamic_tp"]["tp3"])

        if result["risk"]:

            print("----- RISK -----")
            print("Capital Risk :", result["risk"]["capital_at_risk"])
            print("Position Size :", result["risk"]["position_size"])
            print("Risk :", result["risk"]["risk"])

        print("--------------------------------")

    except Exception:
        failed += 1
        logger.exception("[%s/%s] Analiz hatasi: %s", index, len(symbols), symbol)

logger.info(
    "Tarama bitti | islenen=%s basarili=%s atlanan=%s hatali=%s",
    processed,
    success,
    skipped,
    failed,
)
