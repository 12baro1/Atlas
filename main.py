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
from utils.dynamic_targets import DynamicTargetCalculator
from core.ai_learner import AILearningCore
from signal_engine import AdvancedSignalEngine

engine = AtlasEngine()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("atlas.scanner")

# Profesyonel bileşenleri başlat
ai_core = AILearningCore()
target_calc = DynamicTargetCalculator()
signal_engine = AdvancedSignalEngine(ai_learner=ai_core, target_calculator=target_calc)

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

        # Güvenli trend erişimi - KeyError önleme
        trend_data = analysis.get("trend", {})
        if trend_data:
            print("Trend :", trend_data.get("trend", "Bilinmiyor"))
        else:
            print("Trend : Veri yok")

        # Güvenli entry erişimi
        entry_data = analysis.get("entry", {})
        if entry_data:
            print("Entry :", entry_data.get("direction", "Bilinmiyor"))
            print("Entry Price :", entry_data.get("entry", "N/A"))
            print("Stop Loss :", entry_data.get("stop_loss", "N/A"))
            print("Entry Valid :", entry_data.get("valid", False))
            print("Reason :", entry_data.get("reason", "N/A"))
        else:
            print("Entry : Veri yok")

        # Güvenli confirmation erişimi
        conf_data = analysis.get("confirmation", {})
        if conf_data:
            print("Confirmed :", conf_data.get("confirmed", False))
            print("Confirm Reason :", conf_data.get("reason", "N/A"))
        else:
            print("Confirmed : Veri yok")

        # Güvenli market_phase erişimi
        mp_data = analysis.get("market_phase", {})
        if mp_data:
            print("\nMarket Phase Analysis:")
            print("  Phase :", mp_data.get("phase", "Bilinmiyor"))
            print("  Confidence :", mp_data.get("phase_confidence", 0), "%")
            print("  Strength :", mp_data.get("phase_strength", "N/A"))
            print("  Score :", mp_data.get("phase_score", 0))
            print("  MTF Alignment :", mp_data.get("mtf_alignment", 0), "%")
        else:
            print("\nMarket Phase Analysis: Veri yok")

        # Güvenli mtf erişimi
        mtf_data = analysis.get("mtf", {})
        if mtf_data:
            print("Weekly :", mtf_data.get("weekly", "N/A"))
            print("Daily :", mtf_data.get("daily", "N/A"))
            print("H4 :", mtf_data.get("h4", "N/A"))
            print("Entry TF :", mtf_data.get("entry", "N/A"))
            print("MTF Valid :", mtf_data.get("valid", False))
        else:
            print("MTF : Veri yok")

        # Güvenli dynamic_tp erişimi
        tp_data = result.get("dynamic_tp", {})
        if tp_data:
            print("TP1 :", tp_data.get("tp1", "N/A"))
            print("TP2 :", tp_data.get("tp2", "N/A"))
            print("TP3 :", tp_data.get("tp3", "N/A"))
        else:
            print("Dynamic TP : Veri yok")

        # Bybit Execution Engine kaldırıldı - Manuel işlem modu
        # execution_result = execution_engine.process(symbol=symbol, result=result)
        # Manuel işlem için execution_result simüle ediyoruz
        execution_result = {
            "executed": False,
            "reason": "manual_mode_no_auto_execution",
            "symbol": symbol,
            "signal": result.get("signal", {}).get("signal"),
            "confidence": result.get("signal", {}).get("confidence"),
        }
        logger.info(
            "Manual Mode | symbol=%s signal=%s confidence=%s (Otomatik işlem yok, Telegram bildirimi gönderiliyor)",
            symbol,
            execution_result.get("signal"),
            execution_result.get("confidence"),
        )

        print("Execution :", "OPENED" if execution_result.get("executed") else "SKIPPED (Manuel Mod)")
        print("Execution Reason :", execution_result.get("reason"))

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

engine.flush_telegram_notifications(
    join_timeout=float(getattr(Config, "TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", 0.5))
)
