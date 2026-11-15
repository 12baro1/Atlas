"""Headless long-running Atlas market-analysis service.

This service runs the same seven-strategy AtlasRuntime used by the terminal UI.
It only reads public Bybit market data and never submits exchange orders.
"""
from __future__ import annotations

import logging
import os
import signal
import threading
from pathlib import Path


DEFAULT_MAX_SYMBOLS = 0
DEFAULT_SCAN_INTERVAL_SECONDS = 900


def configured_max_symbols(raw_value: str | None) -> int:
    """Return the configured symbol cap; zero explicitly means unlimited."""
    if raw_value is None or not str(raw_value).strip():
        return DEFAULT_MAX_SYMBOLS
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("ATLAS_MAX_SYMBOLS must be a non-negative integer") from exc
    if value < 0:
        raise ValueError("ATLAS_MAX_SYMBOLS must be zero (unlimited) or a positive integer")
    return value


def select_live_symbols(markets, max_symbols: int = DEFAULT_MAX_SYMBOLS):
    """Select active Bybit USDT perpetual swaps for the headless scanner."""
    from universe_engine import select_symbols

    return select_symbols(
        markets,
        suffix="/USDT:USDT",
        require_active=True,
        require_swap=True,
        max_symbols=max_symbols,
    )


def _load_environment() -> None:
    # Load local settings before importing Config or any Atlas runtime modules.
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("python-dotenv is required; install requirements.txt") from exc
    load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

    # Preserve the repository's existing optional integrations and settings.
    # Order execution remains disabled by Atlas' own Config safety contract.


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

    max_symbols = configured_max_symbols(os.getenv("ATLAS_MAX_SYMBOLS"))
    interval = float(os.getenv("ATLAS_SCAN_INTERVAL_SECONDS", str(DEFAULT_SCAN_INTERVAL_SECONDS)))
    if interval <= 0:
        raise ValueError("ATLAS_SCAN_INTERVAL_SECONDS must be greater than zero")

    logger.info("Loading Bybit public market metadata")
    markets = exchange.load_markets()
    symbols, selection_stats = select_live_symbols(markets, max_symbols=max_symbols)
    if not symbols:
        raise RuntimeError("No active USDT perpetual swap symbols were found on Bybit")

    runtime = AtlasRuntime(symbols=symbols, logger=logger, full_scan=True)
    stop_event = threading.Event()

    def request_stop(signum, _frame):
        logger.info("Shutdown requested (signal=%s)", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    logger.info(
        "Atlas live analysis service starting | symbols=%s cap=%s interval=%ss "
        "market_count=%s skipped_inactive=%s skipped_non_swap=%s",
        len(symbols),
        "unlimited" if max_symbols == 0 else max_symbols,
        int(interval),
        selection_stats["total_markets"],
        selection_stats["skipped_inactive"],
        selection_stats["skipped_not_swap"],
    )
    logger.info("Selected symbols: %s", ", ".join(symbols))

    runtime.start(daemon=True)
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
