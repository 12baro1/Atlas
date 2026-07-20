"""
Bybit execution engine for Atlas.

Env flags (read via Config.refresh_from_env):
- ATLAS_AUTO_TRADING_ENABLED=1
- ATLAS_BYBIT_TESTNET=1
- ATLAS_BYBIT_API_KEY=...
- ATLAS_BYBIT_API_SECRET=...
"""

import logging
from typing import Any, Dict, Optional

import ccxt

from config import Config


class BybitExecutionEngine:
    """Places and manages simple market orders on Bybit swap."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("atlas.execution")
        self.enabled = bool(getattr(Config, "AUTO_TRADING_ENABLED", False))
        self.testnet = bool(getattr(Config, "BYBIT_TESTNET", True))
        self.api_key = str(getattr(Config, "BYBIT_API_KEY", "") or "").strip()
        self.api_secret = str(getattr(Config, "BYBIT_API_SECRET", "") or "").strip()
        self.min_confidence = float(getattr(Config, "AUTO_TRADING_MIN_CONFIDENCE", 85.0))
        self.allow_execute_with_caution = bool(getattr(Config, "AUTO_TRADING_ALLOW_EXECUTE_WITH_CAUTION", False))

        self.exchange = None
        if self.enabled:
            self.exchange = self._build_exchange()

    def _build_exchange(self):
        if not self.api_key or not self.api_secret:
            self.logger.error("Auto trading aktif fakat Bybit API key/secret tanimli degil.")
            return None

        exchange = ccxt.bybit(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "options": {"defaultType": "swap"},
                "enableRateLimit": True,
            }
        )
        if hasattr(exchange, "set_sandbox_mode"):
            exchange.set_sandbox_mode(self.testnet)

        self.logger.info("Bybit execution hazir | testnet=%s", self.testnet)
        return exchange

    def _decision_allows_execution(self, result: Dict[str, Any]) -> bool:
        decision = (result or {}).get("decision") or {}
        action = str(decision.get("action") or "").upper()
        if action == "EXECUTE":
            return True
        if action == "EXECUTE_WITH_CAUTION" and self.allow_execute_with_caution:
            return True
        return False

    def _extract_side(self, result: Dict[str, Any]) -> Optional[str]:
        signal = (result or {}).get("signal") or {}
        raw = str(signal.get("signal") or "").upper()
        if raw == "LONG":
            return "buy"
        if raw == "SHORT":
            return "sell"
        return None

    def _extract_amount(self, result: Dict[str, Any]) -> Optional[float]:
        risk = (result or {}).get("risk") or {}
        entry_data = ((result or {}).get("analysis") or {}).get("entry") or {}

        position_size = risk.get("position_size")
        entry_price = entry_data.get("entry")
        if not isinstance(position_size, (int, float)) or position_size <= 0:
            return None
        if not isinstance(entry_price, (int, float)) or entry_price <= 0:
            return None

        amount = float(position_size) / float(entry_price)
        if amount <= 0:
            return None
        return amount

    def _extract_symbol_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        if self.exchange is None:
            return None

        try:
            positions = self.exchange.fetch_positions([symbol])
        except Exception as exc:
            self.logger.warning("Pozisyonlar alinmadi | symbol=%s err=%s", symbol, exc)
            return None

        for pos in positions or []:
            contracts = float(pos.get("contracts") or 0)
            if contracts <= 0:
                continue
            side = str(pos.get("side") or "").lower()
            if side not in {"long", "short"}:
                continue
            return {"side": side, "contracts": contracts}
        return None

    def _close_position_if_needed(self, symbol: str, desired_side: str, open_pos: Dict[str, Any]) -> bool:
        if self.exchange is None:
            return False

        current_side = open_pos.get("side")
        contracts = float(open_pos.get("contracts") or 0)
        if contracts <= 0:
            return False

        if (current_side == "long" and desired_side == "buy") or (
            current_side == "short" and desired_side == "sell"
        ):
            return False

        close_side = "sell" if current_side == "long" else "buy"
        try:
            self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=close_side,
                amount=contracts,
                params={"reduceOnly": True},
            )
            self.logger.info("Pozisyon kapatildi | symbol=%s side=%s amount=%s", symbol, close_side, contracts)
            return True
        except Exception as exc:
            self.logger.error("Pozisyon kapatma hatasi | symbol=%s err=%s", symbol, exc)
            return False

    def _entry_confidence_ok(self, result: Dict[str, Any]) -> bool:
        signal = (result or {}).get("signal") or {}
        confidence = float(signal.get("confidence") or 0)
        return confidence >= self.min_confidence

    def process(self, symbol: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates analysis result and executes trade if rules match."""
        if not self.enabled:
            return {"executed": False, "reason": "auto_trading_disabled"}
        if self.exchange is None:
            return {"executed": False, "reason": "exchange_not_ready"}
        if not self._decision_allows_execution(result):
            return {"executed": False, "reason": "decision_blocked"}
        if not self._entry_confidence_ok(result):
            return {"executed": False, "reason": "low_confidence"}

        side = self._extract_side(result)
        amount = self._extract_amount(result)
        if side is None:
            return {"executed": False, "reason": "invalid_signal"}
        if amount is None:
            return {"executed": False, "reason": "invalid_amount"}

        open_pos = self._extract_symbol_position(symbol)
        if open_pos:
            closed = self._close_position_if_needed(symbol, side, open_pos)
            if not closed and ((open_pos.get("side") == "long" and side == "buy") or (open_pos.get("side") == "short" and side == "sell")):
                return {"executed": False, "reason": "same_side_position_exists"}

        entry = ((result or {}).get("analysis") or {}).get("entry") or {}
        dynamic_tp = (result or {}).get("dynamic_tp") or {}
        stop_loss = entry.get("stop_loss")
        take_profit = dynamic_tp.get("tp3")

        params: Dict[str, Any] = {}
        if isinstance(stop_loss, (int, float)) and stop_loss > 0:
            params["stopLoss"] = stop_loss
        if isinstance(take_profit, (int, float)) and take_profit > 0:
            params["takeProfit"] = take_profit

        try:
            order = self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=amount,
                params=params,
            )
            self.logger.info("Emir acildi | symbol=%s side=%s amount=%.8f", symbol, side, amount)
            return {
                "executed": True,
                "reason": "order_opened",
                "side": side,
                "amount": amount,
                "order_id": order.get("id") if isinstance(order, dict) else None,
            }
        except Exception as exc:
            self.logger.error("Emir acma hatasi | symbol=%s err=%s", symbol, exc)
            return {"executed": False, "reason": "order_failed", "error": str(exc)}
