"""Headless long-running Atlas market-analysis service.

This service runs the same seven-strategy AtlasRuntime used by the terminal UI.
It only reads public Gate.io market data and never submits exchange orders.
"""
from __future__ import annotations

import logging
import os
import signal
import threading
from pathlib import Path


DEFAULT_MAX_SYMBOLS = 300
DEFAULT_SCAN_INTERVAL_SECONDS = 900


def configured_max_symbols(raw_value: str | None) -> int:
    """Return the scanner cap; legacy zero/unlimited settings are clamped to 300."""
    if raw_value is None or not str(raw_value).strip():
        return DEFAULT_MAX_SYMBOLS
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("ATLAS_MAX_SYMBOLS must be a non-negative integer") from exc
    if value < 0:
        raise ValueError("ATLAS_MAX_SYMBOLS must be a non-negative integer")
    if value == 0:
        return DEFAULT_MAX_SYMBOLS
    return min(value, DEFAULT_MAX_SYMBOLS)


def select_live_symbols(markets, max_symbols: int = DEFAULT_MAX_SYMBOLS, exchange_client=None):
    """Select the highest-turnover active Gate.io USDT perpetual swaps."""
    from universe_engine import select_symbols

    symbols, stats = select_symbols(
        markets,
        suffix="/USDT:USDT",
        require_active=True,
        require_swap=True,
        max_symbols=0,
        require_crypto=True,
    )
    if not symbols:
        return symbols, stats

    # Rank before applying the cap; alphabetical truncation can exclude liquid markets.
    scores = {}
    fetch_tickers = getattr(exchange_client, "fetch_tickers", None)
    if callable(fetch_tickers):
        try:
            tickers = fetch_tickers(symbols=symbols) or {}
            for symbol in symbols:
                ticker = tickers.get(symbol) if isinstance(tickers, dict) else None
                if not isinstance(ticker, dict):
                    continue
                info = ticker.get("info") if isinstance(ticker.get("info"), dict) else {}
                raw_volume = ticker.get("quoteVolume")
                if raw_volume is None:
                    raw_volume = info.get("volume_24h_quote")
                try:
                    volume = float(raw_volume or 0)
                except (TypeError, ValueError, OverflowError):
                    volume = 0.0
                if not (0 < volume < float("inf")):
                    try:
                        volume = float(ticker.get("last") or ticker.get("close") or 0) * float(ticker.get("baseVolume") or 0)
                    except (TypeError, ValueError, OverflowError):
                        volume = 0.0
                if 0 < volume < float("inf"):
                    scores[symbol] = volume
        except Exception:
            # Stay available during a temporary ticker endpoint failure.
            scores = {}

    if scores:
        symbols.sort(key=lambda symbol: (scores.get(symbol, -1.0), symbol), reverse=True)
        stats["ranking_source"] = "gateio_24h_quote_volume"
    else:
        symbols.sort()
        stats["ranking_source"] = "alphabetical_fallback"

    if max_symbols > 0 and len(symbols) > max_symbols:
        stats["limited"] = len(symbols) - max_symbols
        symbols = symbols[:max_symbols]
    stats["kept"] = len(symbols)
    return symbols, stats


def _load_environment() -> None:
    # Load local settings before importing Config or any Atlas runtime modules.
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("python-dotenv is required; install requirements.txt") from exc
    load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)


def main() -> int:
    _load_environment()

    logging.basicConfig(
        level=os.getenv("ATLAS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("atlas.service")

    from config import Config
    from data_engine import exchange
    from atlas_runtime import AtlasRuntime
    from telegram_command_service import create_telegram_command_service
    from telegram_botfather import auto_register_on_startup

    # The VPS Telegram integration is command/reply only. Never enable the
    # legacy automatic signal notifier or its independent polling integration.
    Config.TELEGRAM_ENABLED = False
    Config.TELEGRAM_POLLING_ENABLED = False
    Config.TELEGRAM_WEBHOOK_ENABLED = False

    # Register BotFather command menu on startup
    auto_register_on_startup()

    max_symbols = configured_max_symbols(os.getenv("ATLAS_MAX_SYMBOLS"))
    interval = float(os.getenv("ATLAS_SCAN_INTERVAL_SECONDS", str(DEFAULT_SCAN_INTERVAL_SECONDS)))
    if interval <= 0:
        raise ValueError("ATLAS_SCAN_INTERVAL_SECONDS must be greater than zero")

    logger.info("Loading Gate.io public perpetual market metadata")
    markets = exchange.load_markets()
    symbols, selection_stats = select_live_symbols(markets, max_symbols=max_symbols, exchange_client=exchange)
    if not symbols:
        raise RuntimeError("No active USDT perpetual swap symbols were found on Gate.io")

    runtime = AtlasRuntime(symbols=symbols, logger=logger, full_scan=True)
    telegram_commands = create_telegram_command_service(runtime, logger=logger)
    if telegram_commands is not None:
        runtime.attach_telegram_service(telegram_commands)

    stop_event = threading.Event()

    def request_stop(signum, _frame):
        logger.info("Shutdown requested (signal=%s)", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    logger.info(
        "Atlas live analysis service starting | symbols=%s cap=%s interval=%ss "
        "market_count=%s skipped_inactive=%s skipped_non_swap=%s "
        "skipped_non_crypto=%s ranking=%s",
        len(symbols),
        "unlimited" if max_symbols == 0 else max_symbols,
        int(interval),
        selection_stats["total_markets"],
        selection_stats["skipped_inactive"],
        selection_stats["skipped_not_swap"],
        selection_stats["skipped_non_crypto"],
        selection_stats.get("ranking_source", "unknown"),
    )
    logger.info("Selected symbols: %s", ", ".join(symbols))

    runtime.start(daemon=True)
    if telegram_commands is not None:
        telegram_commands.start()
    last_cycle = 0
    try:
        while not stop_event.wait(5):
            worker = runtime._thread
            if worker is None or not worker.is_alive():
                raise RuntimeError("Atlas scanner worker stopped unexpectedly")
            snapshot = runtime.snapshot()
            stats = snapshot.get("scanner") or {}
            cycle = int(stats.get("cycle") or 0)
            if cycle > last_cycle and stats.get("status") == "SLEEP":
                last_cycle = cycle
                logger.info(
                    "Scan cycle %s complete | processed=%s success=%s failed=%s skipped=%s",
                    cycle,
                    stats.get("processed", 0),
                    stats.get("success", 0),
                    stats.get("failed", 0),
                    stats.get("skipped", 0),
                )
    finally:
        logger.info("Stopping Atlas runtime")
        runtime.stop(timeout=30.0)
        logger.info("Atlas runtime stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
