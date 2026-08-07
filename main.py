import logging
import os
import sys
import time
import asyncio

from telegram_engine import TelegramBot
from data_engine import get_market_data, exchange, ccxt
from config import Config
from engine import AtlasEngine
from universe_engine import select_symbols

# Yeni profesyonel modüller
from utils.signal_card import build_signal_card, format_card_text

engine = AtlasEngine()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("atlas.scanner")

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
        logger.error(
            "ccxt mock backend aktif. Canli tarama icin once `python3 -m pip install ccxt` calistirin. "
            "Sadece test/offline icin `ATLAS_ALLOW_MOCK=1 python3 main.py` kullanin."
        )
        sys.exit(2)
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

Config.refresh_from_env()

# Bybit Execution Engine kaldırıldı - Manuel işlem modu
# execution_engine = BybitExecutionEngine()
if bool(getattr(Config, "TELEGRAM_ENABLED", True)):
    token = str(getattr(Config, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    chat_id = str(getattr(Config, "TELEGRAM_CHAT_ID", "") or "").strip()
    if not token:
        logger.warning("Telegram aktif ama bot token bos. Bildirim gonderilmeyecek.")
    if not chat_id:
        logger.warning("Telegram chat id bos. Auth db/chat_ids yoksa bildirim gonderilmeyecek.")


# _send_execution_telegram fonksiyonu kaldırıldı - Manuel modda kullanılmıyor
# Bybit ile otomatik işlem yapılmadığı için order execution bildirimi gönderilmiyor
# Sinyal bildirimleri TelegramEngine tarafından zaten gönderiliyor

def scan_once(symbols, label):
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

            analysis_started = time.perf_counter()
            result = engine.analyze(data)
            elapsed = time.perf_counter() - analysis_started
            logger.info("[%s/%s] Analiz tamamlandi: %s (%.2fs)", index, len(symbols), symbol, elapsed)

            if result is None:
                skipped += 1
                logger.warning("[%s/%s] Sonuc yok, atlandi: %s", index, len(symbols), symbol)
                continue

            success += 1

            card = build_signal_card(result)
            print(format_card_text(card))

            logger.info(
                "Manual Mode | symbol=%s verdict=%s signal=%s confidence=%s (Otomatik işlem yok)",
                symbol,
                card["verdict"],
                card["signal"],
                card["confidence"],
            )

        except Exception:
            failed += 1
            logger.exception("[%s/%s] Analiz hatasi: %s", index, len(symbols), symbol)

    logger.info(
        "Tarama bitti (%s) | islenen=%s basarili=%s atlanan=%s hatali=%s",
        label,
        processed,
        success,
        skipped,
        failed,
    )
    return processed, success, skipped, failed


scan_interval = float(os.getenv("ATLAS_SCAN_INTERVAL_SECONDS", "0").strip() or "0")
cycle = 1

if scan_interval <= 0:
    scan_once(symbols, "tek")
else:
    while True:
        logger.info("Cevrim %s basliyor; %s sn sonra tekrar taranacak (Ctrl+C ara).", cycle, scan_interval)
        scan_once(symbols, "tek")
        try:
            time.sleep(scan_interval)
        except KeyboardInterrupt:
            logger.info("Durduruldu.")
            break
        cycle += 1

engine.flush_telegram_notifications(
    join_timeout=float(getattr(Config, "TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", 0.5))
)
