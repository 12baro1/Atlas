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

from bybit import create_private_swap_exchange

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
        self.position_mode = str(getattr(Config, "BYBIT_POSITION_MODE", "one_way") or "one_way").strip().lower()
        self.log_http = bool(getattr(Config, "BYBIT_LOG_HTTP", False))

        self.exchange = None
        if self.enabled:
            self.exchange = self._build_exchange()

    def _build_exchange(self):
        if not self.api_key or not self.api_secret:
            self.logger.error("Auto trading aktif fakat Bybit API key/secret tanimli degil.")
            return None

        exchange = create_private_swap_exchange(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet,
            enable_rate_limit=True,
        )
        exchange.verbose = self.log_http

        self.logger.info(
            "Bybit execution hazir | testnet=%s position_mode=%s log_http=%s",
            self.testnet,
            self.position_mode,
            self.log_http,
        )
        self._preflight_exchange(exchange)
        return exchange

    def _preflight_exchange(self, exchange):
        try:
            exchange.load_markets()
            self.logger.info("Bybit preflight OK | markets loaded")
        except Exception as exc:
            self._log_exchange_exception("Bybit preflight market load hatasi", exc)

        try:
            exchange.fetch_balance()
            self.logger.info("Bybit preflight OK | balance fetched")
        except Exception as exc:
            self._log_exchange_exception("Bybit preflight balance hatasi (izin/key kontrol edin)", exc)

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

        position_size = risk.get("position_size")
        if not isinstance(position_size, (int, float)) or position_size <= 0:
            return None

        amount = float(position_size)
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
        params = {"reduceOnly": True}
        position_idx = self._resolve_position_idx(close_side)
        if position_idx is not None:
            params["positionIdx"] = position_idx

        request_payload = {
            "symbol": symbol,
            "type": "market",
            "side": close_side,
            "amount": contracts,
            "params": params,
        }
        try:
            self.logger.info("Bybit close request | payload=%s", request_payload)
            response = self.exchange.create_order(**request_payload)
            self.logger.info("Pozisyon kapatildi | symbol=%s side=%s amount=%s response=%s", symbol, close_side, contracts, response)
            return True
        except Exception as exc:
            self._log_exchange_exception("Pozisyon kapatma hatasi", exc, context={"symbol": symbol, "payload": request_payload})
            return False

    def _entry_confidence_ok(self, result: Dict[str, Any]) -> bool:
        signal = (result or {}).get("signal") or {}
        confidence = float(signal.get("confidence") or 0)
        return confidence >= self.min_confidence

    def process(self, symbol: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates analysis result and executes trade if rules match."""
        if not self.enabled:
            self.logger.warning(
                "Execution skipped | reason=auto_trading_disabled env_ATLAS_AUTO_TRADING_ENABLED=%s",
                getattr(Config, "AUTO_TRADING_ENABLED", False),
            )
            return {"executed": False, "reason": "auto_trading_disabled"}
        if self.exchange is None:
            self.logger.error("Execution skipped | reason=exchange_not_ready testnet=%s key_set=%s secret_set=%s", self.testnet, bool(self.api_key), bool(self.api_secret))
            return {"executed": False, "reason": "exchange_not_ready"}
        if not self._decision_allows_execution(result):
            decision = (result or {}).get("decision") or {}
            self.logger.info("Execution skipped | reason=decision_blocked action=%s", decision.get("action"))
            return {"executed": False, "reason": "decision_blocked"}
        if not self._entry_confidence_ok(result):
            confidence = ((result or {}).get("signal") or {}).get("confidence")
            self.logger.info("Execution skipped | reason=low_confidence confidence=%s min=%s", confidence, self.min_confidence)
            return {"executed": False, "reason": "low_confidence"}

        risk = (result or {}).get("risk") or {}
        if risk.get("risk_setup_valid") is False:
            reason = risk.get("risk_setup_reason", "Invalid Risk Setup")
            self.logger.info("Execution skipped | reason=risk_blocked risk_reason=%s", reason)
            return {"executed": False, "reason": "risk_blocked", "risk_reason": reason}

        side = self._extract_side(result)
        amount = self._extract_amount(result)
        if side is None:
            self.logger.info("Execution skipped | reason=invalid_signal")
            return {"executed": False, "reason": "invalid_signal"}
        if amount is None:
            self.logger.info("Execution skipped | reason=invalid_amount")
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
        position_idx = self._resolve_position_idx(side)
        if position_idx is not None:
            params["positionIdx"] = position_idx
        if isinstance(stop_loss, (int, float)) and stop_loss > 0:
            params["stopLoss"] = stop_loss
        if isinstance(take_profit, (int, float)) and take_profit > 0:
            params["takeProfit"] = take_profit

        request_payload = {
            "symbol": symbol,
            "type": "market",
            "side": side,
            "amount": amount,
            "params": params,
        }

        try:
            self.logger.info("Bybit order request | payload=%s", request_payload)
            order = self.exchange.create_order(**request_payload)
            avg_price = None
            if isinstance(order, dict):
                avg_price = order.get("average") or order.get("price")
            self.logger.info(
                "Emir acildi | symbol=%s side=%s amount=%.8f order_id=%s price=%s response=%s",
                symbol,
                side,
                amount,
                order.get("id") if isinstance(order, dict) else None,
                avg_price,
                order,
            )
            return {
                "executed": True,
                "reason": "order_opened",
                "side": side,
                "amount": amount,
                "order_id": order.get("id") if isinstance(order, dict) else None,
                "price": avg_price,
            }
        except Exception as exc:
            details = self._log_exchange_exception(
                "Emir acma hatasi",
                exc,
                context={"symbol": symbol, "payload": request_payload},
            )
            return {"executed": False, "reason": "order_failed", "error": str(exc), "exchange_error": details}

    def _resolve_position_idx(self, side: str) -> Optional[int]:
        if self.position_mode != "hedge":
            return None

        if side == "buy":
            return 1
        if side == "sell":
            return 2
        return None

    def _log_exchange_exception(self, prefix: str, exc: Exception, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        details: Dict[str, Any] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "context": context or {},
        }

        for attr in ("code", "status", "http_status", "reason", "body", "response"):
            value = getattr(exc, attr, None)
            if value is not None:
                details[attr] = value

        self.logger.exception("%s | details=%s", prefix, details)
        return details
