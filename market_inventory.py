"""Gate.io-only market inventory for Atlas.

Discovers the full set of tradable USDT linear perpetual contracts on
Gate.io dynamically (no fixed symbol cap), excludes delisted/suspended
contracts, respects API rate limits through a refresh TTL, retries
temporary failures with backoff and persists the last snapshot so a VPS
restart can still enumerate the universe.

This module never touches trading credentials: it is public market data
only, and it never falls back to any other exchange.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("atlas.market_inventory")

STATE_FILE = "inventory_state.json"
DEFAULT_TTL_SECONDS = 15 * 60          # refresh at most every 15 minutes
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0


class MarketInventory:
    """Persistent, rate-limit-aware Gate.io USDT perpetual universe."""

    def __init__(
        self,
        base_path: str = "market_inventory",
        exchange=None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.max_retries = max(1, int(max_retries))
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self._lock = threading.RLock()

        # Gate.io only; no Bybit/Binance/MEXC fallback by design.
        if exchange is None:
            from gateio_futures import GateFuturesExchange
            exchange = GateFuturesExchange()
        self._exchange = exchange

        # symbol -> market info
        self._snapshot: Dict[str, Dict[str, Any]] = {}
        self._last_refresh_ms: int = 0
        self._last_error: Optional[str] = None
        self._last_error_ms: int = 0
        self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_symbols(self, force_refresh: bool = False) -> List[str]:
        """Current tradable symbols, refreshing when the TTL has expired.

        Returns the cached snapshot on refresh failure so a temporary API
        outage never empties the scanning universe.
        """
        with self._lock:
            stale = (int(time.time() * 1000) - self._last_refresh_ms) >= self.ttl_seconds * 1000
            if force_refresh or stale or not self._snapshot:
                self._refresh_locked(force=force_refresh)
            return sorted(self._snapshot.keys())

    def refresh(self, force: bool = True) -> Dict[str, Any]:
        """Force a refresh and return a status summary.

        force=True ignores the TTL so an explicit user request ("yenile")
        always attempts a real Gate.io refresh; rate-limit backoff still
        applies between retries.
        """
        with self._lock:
            if force or (int(time.time() * 1000) - self._last_refresh_ms) >= self.ttl_seconds * 1000:
                self._refresh_locked(force=force)
            return self.status()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "symbol_count": len(self._snapshot),
                "last_refresh_ms": self._last_refresh_ms,
                "last_refresh_age_seconds": (
                    max(0, int(int(time.time() * 1000) - self._last_refresh_ms) // 1000)
                    if self._last_refresh_ms else None
                ),
                "ttl_seconds": self.ttl_seconds,
                "last_error": self._last_error,
                "last_error_ms": self._last_error_ms,
                "source": "gateio_usdt_perpetuals",
            }

    def market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._snapshot.get(symbol)

    # ------------------------------------------------------------------
    # Refresh with retries (rate-limit friendly)
    # ------------------------------------------------------------------

    def _refresh_locked(self, force: bool = False):
        now_ms = int(time.time() * 1000)
        # Honor the TTL unless explicitly forced: protects Gate.io rate limits
        # while still honoring an explicit user refresh request.
        if not force and self._last_refresh_ms and (now_ms - self._last_refresh_ms) < self.ttl_seconds * 1000:
            return
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                markets = self._exchange.load_markets(reload=True) or {}
                tradable = {
                    symbol: info
                    for symbol, info in markets.items()
                    if self._is_tradable_usdt_perp(info)
                }
                if tradable:
                    self._snapshot = tradable
                    self._last_refresh_ms = now_ms
                    self._last_error = None
                    self._last_error_ms = 0
                    self._save_state()
                    logger.info(
                        f"Gate.io inventory refreshed: {len(tradable)} USDT perpetuals"
                    )
                    return
                last_error = RuntimeError("empty tradable universe from Gate.io")
            except Exception as exc:
                last_error = exc
                logger.warning(
                    f"Gate.io inventory refresh attempt {attempt}/{self.max_retries} "
                    f"failed: {exc}"
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
        self._last_error = str(last_error) if last_error else "refresh_failed"
        self._last_error_ms = now_ms
        # Keep the previous snapshot; never return an empty universe on a
        # temporary outage.

    @staticmethod
    def _is_tradable_usdt_perp(info: Dict[str, Any]) -> bool:
        if not isinstance(info, dict):
            return False
        if not info.get("swap") or not info.get("linear"):
            return False
        if str(info.get("quote") or "").upper() != "USDT":
            return False
        if str(info.get("settle") or "").upper() != "USDT":
            return False
        if info.get("active") is False:
            return False
        raw = info.get("info") or {}
        if isinstance(raw, dict):
            # Gate.io marks suspended contracts with a non-trading trade_status.
            trade_status = str(raw.get("trade_status") or "trading").lower()
            if trade_status and trade_status != "trading":
                return False
            if raw.get("in_delisting"):
                return False
        return True

    # ------------------------------------------------------------------
    # Persistence (atomic writes; survives VPS restarts)
    # ------------------------------------------------------------------

    def _save_state(self):
        path = self.base_path / STATE_FILE
        tmp_path = path.with_name(f".{path.stem}.{os.getpid()}.tmp")
        payload = {
            "version": 1,
            "last_refresh_ms": self._last_refresh_ms,
            "last_error": self._last_error,
            "last_error_ms": self._last_error_ms,
            "symbols": {
                symbol: {
                    "id": info.get("id"),
                    "contract_size": info.get("contractSize"),
                }
                for symbol, info in self._snapshot.items()
            },
        }
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)

    def _load_state(self):
        path = self.base_path / STATE_FILE
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._last_refresh_ms = int(data.get("last_refresh_ms") or 0)
            self._last_error = data.get("last_error")
            self._last_error_ms = int(data.get("last_error_ms") or 0)
            symbols = data.get("symbols") or {}
            if isinstance(symbols, dict):
                self._snapshot = {
                    str(symbol): {
                        "id": str(info.get("id") or ""),
                        "symbol": str(symbol),
                        "contractSize": float(info.get("contract_size") or 1.0),
                    }
                    for symbol, info in symbols.items()
                    if isinstance(info, dict)
                }
        except (OSError, TypeError, ValueError) as exc:
            logger.error(f"Could not restore market inventory state: {exc}")


_inventory_instance: Optional[MarketInventory] = None
_inventory_lock = threading.Lock()


def get_market_inventory(**kwargs) -> MarketInventory:
    global _inventory_instance
    with _inventory_lock:
        if _inventory_instance is None:
            _inventory_instance = MarketInventory(**kwargs)
        return _inventory_instance


def reset_market_inventory():
    global _inventory_instance
    with _inventory_lock:
        _inventory_instance = None
