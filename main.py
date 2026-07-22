import ccxt
import logging
import os
import sys
import time

from telegram_engine import TelegramBot

from bybit import create_public_swap_exchange
from bybit_execution_engine import BybitExecutionEngine
from data_engine import get_market_data
from config import Config
from engine import AtlasEngine
from universe_engine import select_symbols

engine = AtlasEngine()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("atlas.scanner")

exchange = create_public_swap_exchange(enable_rate_limit=True)

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
execution_engine = BybitExecutionEngine()
if bool(getattr(Config, "TELEGRAM_ENABLED", True)):
    token = str(getattr(Config, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    chat_id = str(getattr(Config, "TELEGRAM_CHAT_ID", "") or "").strip()
    if not token:
        logger.warning("Telegram aktif ama bot token bos. Bildirim gonderilmeyecek.")
    if not chat_id:
        logger.warning("Telegram chat id bos. Auth db/chat_ids yoksa bildirim gonderilmeyecek.")


def _send_execution_telegram(symbol, execution_result):
    if not bool(getattr(Config, "TELEGRAM_ENABLED", True)):
        return False

    if not execution_result.get("executed"):
        return False

    order_id = execution_result.get("order_id") or "N/A"
    ret_code = execution_result.get("ret_code")
    ret_msg = execution_result.get("ret_msg")
    side = str(execution_result.get("side") or "").upper()
    amount = execution_result.get("amount")
    price = execution_result.get("price")

    message_lines = [
        "ATLAS ORDER UPDATE",
        "Order Executed",
        f"Symbol: {symbol}",
        f"Order ID: {order_id}",
        f"Side: {side}",
        f"Amount: {amount}",
        f"Price: {price}",
        f"retCode: {ret_code}",
        f"retMsg: {ret_msg}",
    ]
    message = "\n".join(message_lines)

    sent = TelegramBot().send(message)
    logger.info(
        "Execution Telegram | symbol=%s sent=%s order_id=%s retCode=%s retMsg=%s",
        symbol,
        sent,
        order_id,
        ret_code,
        ret_msg,
    )
    return sent

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

        execution_result = execution_engine.process(symbol=symbol, result=result)
        logger.info(
            "Execution | symbol=%s executed=%s reason=%s details=%s",
            symbol,
            execution_result.get("executed"),
            execution_result.get("reason"),
            execution_result,
        )
        if execution_result.get("executed"):
            logger.info(
                "Execution success | symbol=%s order_id=%s retCode=%s retMsg=%s",
                symbol,
                execution_result.get("order_id"),
                execution_result.get("ret_code"),
                execution_result.get("ret_msg"),
            )
        else:
            logger.error(
                "Execution failed | symbol=%s reason=%s error=%s retCode=%s retMsg=%s exchange_error=%s",
                symbol,
                execution_result.get("reason"),
                execution_result.get("error"),
                execution_result.get("ret_code"),
                execution_result.get("ret_msg"),
                execution_result.get("exchange_error"),
            )

        print("Execution :", "OPENED" if execution_result.get("executed") else "SKIPPED")
        print("Execution Reason :", execution_result.get("reason"))
        if execution_result.get("decision_action"):
            print("Decision Action :", execution_result.get("decision_action"))
        if execution_result.get("decision_reason"):
            print("Decision Reason :", execution_result.get("decision_reason"))
        if execution_result.get("required_confidence") is not None:
            print("Required Confidence :", execution_result.get("required_confidence"))
        if execution_result.get("order_id"):
            print("Order ID :", execution_result.get("order_id"))
        if execution_result.get("ret_code") is not None:
            print("retCode :", execution_result.get("ret_code"))
        if execution_result.get("ret_msg") is not None:
            print("retMsg :", execution_result.get("ret_msg"))

        if execution_result.get("executed"):
            _send_execution_telegram(symbol=symbol, execution_result=execution_result)

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
