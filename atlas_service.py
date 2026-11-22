"""Headless long-running Atlas market-analysis service.

This service runs the same five-strategy + two-specialist AtlasRuntime used by the terminal UI.
It only reads public Gate.io market data and never submits exchange orders.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from pathlib import Path


DEFAULT_MAX_SYMBOLS = 50
DEFAULT_SCAN_INTERVAL_SECONDS = 900


def notify_systemd(message):
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        if address.startswith("@"):
            address = "\0" + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.sendto(message.encode(), address)


def configured_max_symbols(raw_value: str | None) -> int:
    """Return the scanner cap; legacy zero/unlimited settings are clamped to the top 50."""
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



def load_startup_symbols(
    inventory,
    max_symbols: int,
    stop_event: threading.Event,
    logger,
    retry_interval_seconds: float = 30.0,
):
    """Wait for a successful Gate.io inventory refresh instead of crashing startup."""
    last_status = {}
    while not stop_event.is_set():
        try:
            last_status = inventory.refresh(force=True) or {}
            if not last_status.get("last_error") and int(last_status.get("symbol_count") or 0) > 0:
                symbols = inventory.get_ranked_symbols(limit=max_symbols, require_volume=True)
                required = min(max_symbols, int(last_status.get("symbol_count") or 0))
                if len(symbols) >= required and symbols:
                    return symbols, inventory.status()
                logger.warning(
                    "Gate.io 24h USDT volume ranking incomplete (%s/%s); retrying",
                    len(symbols), required,
                )
            else:
                logger.warning(
                    "Gate.io inventory unavailable; keeping Atlas alive and retrying | error=%s",
                    last_status.get("last_error") or "empty_inventory",
                )
        except Exception as exc:
            logger.warning("Gate.io startup inventory request failed; retrying | %s", exc)
        if stop_event.wait(max(1.0, float(retry_interval_seconds))):
            break
    return [], last_status


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
    from market_inventory import get_market_inventory
    from telegram_command_service import create_telegram_command_service
    from telegram_botfather import auto_register_on_startup

    stop_event = threading.Event()

    def request_stop(signum, _frame):
        logger.info("Shutdown requested (signal=%s)", signum)
        stop_event.set()

    # Install signal handlers before any network operation so systemd can stop
    # Atlas cleanly even while Gate.io is temporarily unavailable.
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    # The VPS Telegram integration is command/reply only. Never enable the
    # legacy automatic signal notifier or its independent polling integration.
    Config.TELEGRAM_ENABLED = False
    Config.TELEGRAM_POLLING_ENABLED = False
    Config.TELEGRAM_WEBHOOK_ENABLED = False

    max_symbols = configured_max_symbols(os.getenv("ATLAS_MAX_SYMBOLS"))
    interval = float(os.getenv("ATLAS_SCAN_INTERVAL_SECONDS", str(DEFAULT_SCAN_INTERVAL_SECONDS)))
    if interval <= 0:
        raise ValueError("ATLAS_SCAN_INTERVAL_SECONDS must be greater than zero")

    # Reuse the same persistent inventory instance as ScanService. The adapter
    # owns endpoint retries; avoid multiplying them with inventory-level retries.
    # The inventory still persists and preserves its last successful snapshot.
    inventory = get_market_inventory(exchange=exchange, max_retries=1)
    logger.info("Loading Gate.io public perpetual market metadata")
    symbols, selection_stats = load_startup_symbols(
        inventory,
        max_symbols=max_symbols,
        stop_event=stop_event,
        logger=logger,
    )
    if stop_event.is_set():
        logger.info("Shutdown requested before market inventory became available")
        return 0
    if not symbols:
        raise RuntimeError("No active USDT perpetual swap symbols were found on Gate.io")

    # Preserve the BotFather command menu registration from the previous startup.
    auto_register_on_startup()

    # The durable ScanService is the only background analysis pipeline.
    # The legacy full_scan loop would analyze the same 50 symbols a second time.
    runtime = AtlasRuntime(symbols=symbols, logger=logger, full_scan=False)
    telegram_commands = create_telegram_command_service(runtime, logger=logger)
    if telegram_commands is not None:
        runtime.attach_telegram_service(telegram_commands)

    logger.info(
        "Atlas live analysis service starting | symbols=%s cap=%s interval=%ss "
        "market_count=%s ranking=%s scan_pipeline=durable_queue",
        len(symbols),
        "unlimited" if max_symbols == 0 else max_symbols,
        int(interval),
        selection_stats.get("symbol_count", 0),
        selection_stats.get("ranking_source", "unknown"),
    )
    logger.info("Selected symbols: %s", ", ".join(symbols))

    # Migration: old persisted 300-symbol queues must not resume after this
    # service switches to the top-50 market universe. Older generations remain
    # intact in SQLite, and Telegram trade tracking is not touched.
    migrated = runtime._scan_service.enforce_universe_limit()
    if (migrated is not None and not migrated.get("rebuilt")
            and int(runtime._scan_queue.progress().get("total") or 0) > max_symbols):
        raise RuntimeError("Cannot migrate legacy scan queue to top-50 volume ranking")

    runtime.start(daemon=True)
    if telegram_commands is not None:
        telegram_commands.start()
    last_generation = None
    last_complete = False
    next_scheduled_scan = time.monotonic() + interval
    try:
        notify_systemd("READY=1")
        while not stop_event.wait(5):
            scan_status = runtime.scan_progress()
            if scan_status.get("stalled_symbol"):
                raise RuntimeError(f"Scan worker stalled across two lease periods: {scan_status['stalled_symbol']}")
            if not scan_status.get("workers_running"):
                logger.error("Durable scan worker stopped; attempting recovery")
                runtime.resume_scan()
                scan_status = runtime.scan_progress()
                if not scan_status.get("workers_running"):
                    raise RuntimeError("Atlas durable scan worker stopped unexpectedly")

            generation = int(scan_status.get("generation") or 0)
            complete = bool(scan_status.get("complete"))
            if generation != last_generation or (complete and not last_complete):
                logger.info(
                    "Scan queue status | generation=%s total=%s done=%s failed=%s pending=%s running=%s",
                    generation,
                    scan_status.get("total", 0),
                    scan_status.get("done", 0),
                    scan_status.get("failed", 0),
                    scan_status.get("pending", 0),
                    scan_status.get("running", 0),
                )
            last_generation = generation
            last_complete = complete

            # Replace the old parallel full-scan loop with a scheduled enqueue
            # into the same durable queue. No second set of analysis workers.
            if time.monotonic() >= next_scheduled_scan:
                if complete:
                    scheduled = runtime.start_scan(limit=max_symbols)
                    logger.info(
                        "Scheduled scan enqueued | started=%s selected=%s generation=%s",
                        scheduled.get("started", False),
                        scheduled.get("selected", 0),
                        scheduled.get("scan_generation"),
                    )
                else:
                    logger.info(
                        "Scheduled scan deferred; current generation still has work | "
                        "pending=%s running=%s",
                        scan_status.get("pending", 0),
                        scan_status.get("running", 0),
                    )
                next_scheduled_scan = time.monotonic() + interval
            notify_systemd("WATCHDOG=1")
    finally:
        logger.info("Stopping Atlas runtime")
        runtime.stop(timeout=30.0)
        logger.info("Atlas runtime stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
