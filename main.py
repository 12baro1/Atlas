import logging
import os
import sys
import time

from data_engine import get_market_data, get_correlation_universe, exchange, ccxt
from config import Config
from engine import AtlasEngine
from universe_engine import select_symbols

# Terminal kartı
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
    max_symbols=int(os.getenv("ATLAS_MAX_SYMBOLS", "0").strip() or 0),
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

# Manuel işlem modu: Bybit'e otomatik emir gönderilmez.
# Sinyaller Telegram + terminal kartı ile bildirilir, trader kendisi işlem yapar.
if bool(getattr(Config, "TELEGRAM_ENABLED", True)):
    token = str(getattr(Config, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    chat_id = str(getattr(Config, "TELEGRAM_CHAT_ID", "") or "").strip()
    if not token:
        logger.warning("Telegram aktif ama bot token bos. Bildirim gonderilmeyecek.")
    if not chat_id:
        logger.warning("Telegram chat id bos. Auth db/chat_ids yoksa bildirim gonderilmeyecek.")

telegram_service = None
if bool(getattr(Config, "TELEGRAM_POLLING_ENABLED", True)) or bool(getattr(Config, "TELEGRAM_WEBHOOK_ENABLED", False)):
    try:
        from telegram_auth import TelegramAuthService
        from telegram_auth_store import TelegramAuthStore
        from telegram_service import TelegramService, TelegramTradeCommandHandler
        from telegram_webhook import TelegramWebhookHandler

        _store = TelegramAuthStore(Config.TELEGRAM_AUTH_DB_FILE)
        _auth = TelegramAuthService(
            store=_store,
            password=Config.BOT_PASSWORD,
            password_hash=Config.BOT_PASSWORD_HASH,
            admin_ids=Config.TELEGRAM_ADMIN_IDS,
        )
        _trade_handler = TelegramTradeCommandHandler(journal=engine.trade_journal)
        telegram_service = TelegramService(
            auth_service=_auth,
            webhook_handler=TelegramWebhookHandler(),
            trade_command_handler=_trade_handler,
        )
        telegram_service.start(daemon=True)
        logger.info("Telegram servisi baslatildi (polling=%s webhook=%s).",
                    bool(getattr(Config, "TELEGRAM_POLLING_ENABLED", True)),
                    bool(getattr(Config, "TELEGRAM_WEBHOOK_ENABLED", False)))
    except Exception:
        logger.exception("Telegram servisi baslatilamadi, otomatik bota devam ediliyor.")

def scan_once(symbols, label):
    processed = 0
    success = 0
    failed = 0
    skipped = 0

    # Korrelasyon evreni (BTC/ETH) her scan için bir kez çekilir ve paylaşılır.
    universe = {}
    try:
        universe = get_correlation_universe()
    except Exception:
        logger.warning("Korrelasyon evreni alinamadi; korrelasyon filtresi pasif.")

    for index, symbol in enumerate(symbols, start=1):
        try:
            processed += 1
            logger.info("[%s/%s] Analiz basliyor: %s", index, len(symbols), symbol)

            data = get_market_data(symbol)
            if universe:
                data["correlation_universe"] = universe
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

            # Canlı sinyal sonuç takibi: bu semboldeki açık sinyalleri güncel fiyatla çöz
            if Config.SIGNAL_TRACKING_ENABLED:
                candles_15m = data.get("15m") or data.get("15M") or []
                for open_trade in engine.trade_journal.open_trades(symbol=symbol):
                    closed = engine.trade_journal.resolve_open_signal(open_trade, candles_15m)
                    if closed and closed.get("result"):
                        logger.info(
                            "Sinyal sonucu | %s %s %s | result=%s rr=%s | %s",
                            closed.get("symbol"), closed.get("side"),
                            closed.get("opened_at"), closed.get("result"),
                            closed.get("pnl_rr"), closed.get("close_reason"),
                        )

                # Teorik sinyal sonuçları (TP/SL rozetleme + expiry)
                resolved = engine.trade_journal.resolve_signal_outcomes(
                    {symbol: candles_15m}
                )
                for outcome in resolved:
                    logger.info(
                        "Sinyal outcome | %s %s | status=%s result=%s realized_r=%s",
                        outcome.get("symbol"), outcome.get("direction"),
                        outcome.get("status"), outcome.get("final_result"),
                        outcome.get("realized_r"),
                    )

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


def refresh_learning_meta():
    """Meta öğrenme katmanını journal'daki kapanmış sonuçlarla tazeler."""
    try:
        if not bool(getattr(Config, "LEARNING_ENGINE_ENABLED", True)):
            return
        refresher = engine.refresh_learning()
        if refresher is None:
            return
        logger.info(
            "Learning meta | kaynak=%s bucket=%s",
            getattr(engine.learning, "stats", {}).get("source"),
            len(getattr(engine.learning, "stats", {}).get("setups", {})),
        )
    except Exception:
        logger.exception("Learning meta tazelemesi basarisiz.")


scan_interval = float(os.getenv("ATLAS_SCAN_INTERVAL_SECONDS", "0").strip() or "0")
cycle = 1

if scan_interval <= 0:
    scan_once(symbols, "tek")
    refresh_learning_meta()
else:
    while True:
        logger.info("Cevrim %s basliyor; %s sn sonra tekrar taranacak (Ctrl+C ara).", cycle, scan_interval)
        scan_once(symbols, "tek")
        refresh_learning_meta()
        try:
            time.sleep(scan_interval)
        except KeyboardInterrupt:
            logger.info("Durduruldu.")
            break
        cycle += 1

engine.flush_telegram_notifications(
    join_timeout=float(getattr(Config, "TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", 0.5))
)

if telegram_service is not None:
    telegram_service.stop()
