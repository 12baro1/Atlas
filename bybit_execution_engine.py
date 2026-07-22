"""
Bybit execution engine for Atlas.

Env flags (read via Config.refresh_from_env):
- ATLAS_AUTO_TRADING_ENABLED=1
- ATLAS_BYBIT_TESTNET=1
- ATLAS_BYBIT_DEMO_TRADING=1  # Bybit Demo Trading hesabi icin
- ATLAS_BYBIT_API_KEY=...
- ATLAS_BYBIT_API_SECRET=...
"""

import logging
import math
import json
from typing import Tuple
from typing import Any, Dict, Optional

from bybit import create_private_swap_exchange

from config import Config


class BybitExecutionEngine:
    """Places and manages simple market orders on Bybit swap."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("atlas.execution")
        self.enabled = bool(getattr(Config, "AUTO_TRADING_ENABLED", False))
        self.auto_enable_with_keys = bool(getattr(Config, "AUTO_TRADING_AUTO_ENABLE_WITH_KEYS", True))
        self.testnet = bool(getattr(Config, "BYBIT_TESTNET", True))
        self.demo_trading = bool(getattr(Config, "BYBIT_DEMO_TRADING", False))
        self.api_key = str(getattr(Config, "BYBIT_API_KEY", "") or "").strip()
        self.api_secret = str(getattr(Config, "BYBIT_API_SECRET", "") or "").strip()
        self.min_confidence = float(getattr(Config, "AUTO_TRADING_MIN_CONFIDENCE", 85.0))
        self.allow_execute_with_caution = bool(getattr(Config, "AUTO_TRADING_ALLOW_EXECUTE_WITH_CAUTION", False))
        self.min_leverage = max(1, int(getattr(Config, "AUTO_TRADING_MIN_LEVERAGE", 1)))
        self.max_leverage = min(125, max(self.min_leverage, int(getattr(Config, "AUTO_TRADING_MAX_LEVERAGE", 20))))
        self.position_mode = str(getattr(Config, "BYBIT_POSITION_MODE", "one_way") or "one_way").strip().lower()
        self.log_http = bool(getattr(Config, "BYBIT_LOG_HTTP", False))
        self.preflight_status: Dict[str, Any] = {
            "ok": False,
            "steps": {},
            "errors": [],
        }

        if not self.enabled and self.auto_enable_with_keys and self.api_key and self.api_secret:
            self.enabled = True
            self.logger.warning(
                "Auto trading env kapali ama key/secret bulundu; AUTO_TRADING_AUTO_ENABLE_WITH_KEYS ile aktif edildi."
            )

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
            demo_trading=self.demo_trading,
        )
        exchange.verbose = self.log_http

        self.logger.info(
            "Bybit execution hazir | testnet=%s demo_trading=%s position_mode=%s leverage_range=%sx-%sx log_http=%s",
            self.testnet,
            self.demo_trading,
            self.position_mode,
            self.min_leverage,
            self.max_leverage,
            self.log_http,
        )
        self._log_endpoint_hint(exchange)
        self._preflight_exchange(exchange)
        return exchange


    def _execution_context(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "testnet": self.testnet,
            "demo_trading": self.demo_trading,
            "key_set": bool(self.api_key),
            "secret_set": bool(self.api_secret),
            "min_confidence": self.min_confidence,
            "allow_execute_with_caution": self.allow_execute_with_caution,
            "preflight_ok": bool(self.preflight_status.get("ok", False)),
        }

    def _skip(self, reason: str, **details: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "executed": False,
            "reason": reason,
            "execution_context": self._execution_context(),
        }
        payload.update(details)
        return payload

    def _log_endpoint_hint(self, exchange) -> None:
        """Exchange'in kullandığı endpoint URL'ini loglar; yanlış mod seçimini kolayca fark ettirmek için."""
        try:
            from bybit import _resolve_endpoint_url
            endpoint = _resolve_endpoint_url(exchange)
        except Exception:
            endpoint = "unknown"
        self.logger.info(
            "Bybit aktif endpoint | url=%s  "
            "[Demo Trading icin: ATLAS_BYBIT_DEMO_TRADING=1 ATLAS_BYBIT_TESTNET=0]  "
            "[Testnet icin: ATLAS_BYBIT_TESTNET=1 ATLAS_BYBIT_DEMO_TRADING=0]  "
            "[Mainnet icin: ATLAS_BYBIT_TESTNET=0 ATLAS_BYBIT_DEMO_TRADING=0]",
            endpoint,
        )

    def _check_retcode_10003(self, details: Dict[str, Any]) -> None:
        """retCode 10003 ise endpoint/anahtar uyumsuzluğunu açıkça loglar."""
        ret_code = details.get("retCode")
        msg = str(details.get("message", ""))
        if ret_code == 10003 or "10003" in msg:
            self.logger.error(
                "\n"
                "========================================================\n"
                "  Bybit retCode 10003 - API key is invalid\n"
                "  Anahtar turune gore dogru modu secin:\n"
                "  - Demo Trading anahtari (ana Bybit hesabi > API Management > Demo):\n"
                "      ATLAS_BYBIT_DEMO_TRADING=1\n"
                "      ATLAS_BYBIT_TESTNET=0\n"
                "  - Testnet anahtari (testnet.bybit.com'dan olusturulmus):\n"
                "      ATLAS_BYBIT_TESTNET=1\n"
                "      ATLAS_BYBIT_DEMO_TRADING=0\n"
                "  - Mainnet anahtari:\n"
                "      ATLAS_BYBIT_TESTNET=0\n"
                "      ATLAS_BYBIT_DEMO_TRADING=0\n"
                "  Mevcut mod: testnet=%s demo_trading=%s\n"
                "========================================================",
                self.testnet,
                self.demo_trading,
            )

    def _preflight_exchange(self, exchange):
        steps = self.preflight_status["steps"]
        errors = self.preflight_status["errors"]

        try:
            exchange.load_markets()
            self.logger.info("Bybit preflight OK | markets loaded")
            steps["markets"] = "ok"
        except Exception as exc:
            details = self._log_exchange_exception("Bybit preflight market load hatasi", exc)
            steps["markets"] = "failed"
            errors.append({"step": "markets", "details": details})
            self._check_retcode_10003(details)

        try:
            exchange.fetch_balance()
            self.logger.info("Bybit preflight OK | balance fetched")
            steps["balance"] = "ok"
        except Exception as exc:
            details = self._log_exchange_exception("Bybit preflight balance hatasi (izin/key kontrol edin)", exc)
            steps["balance"] = "failed"
            errors.append({"step": "balance", "details": details})
            self._check_retcode_10003(details)

        self.preflight_status["ok"] = len(errors) == 0
        if not self.preflight_status["ok"]:
            self.logger.error("Bybit preflight failed | status=%s", self.preflight_status)

    def _symbol_market(self, symbol: str) -> Optional[Dict[str, Any]]:
        if self.exchange is None:
            return None

        markets = getattr(self.exchange, "markets", None) or {}
        market = markets.get(symbol)
        if market is None:
            try:
                market = self.exchange.market(symbol)
            except Exception:
                return None
        return market

    def _format_amount_for_market(self, symbol: str, raw_amount: float) -> Tuple[Optional[float], Optional[str]]:
        market = self._symbol_market(symbol)
        if market is None:
            return raw_amount, None

        min_amount = (((market.get("limits") or {}).get("amount") or {}).get("min"))
        max_amount = (((market.get("limits") or {}).get("amount") or {}).get("max"))
        precision_amount = (market.get("precision") or {}).get("amount")

        amount = float(raw_amount)
        if isinstance(max_amount, (int, float)) and max_amount > 0:
            amount = min(amount, float(max_amount))

        if precision_amount is not None:
            try:
                amount = float(self.exchange.amount_to_precision(symbol, amount))
            except Exception:
                if isinstance(precision_amount, int) and precision_amount >= 0:
                    factor = 10 ** precision_amount
                    amount = math.floor(amount * factor) / factor

        if isinstance(min_amount, (int, float)) and min_amount > 0 and amount < float(min_amount):
            return None, f"amount_below_min_lot:{amount}<{min_amount}"

        if amount <= 0:
            return None, "amount_non_positive"

        return amount, None

    def _balance_snapshot(self) -> Dict[str, Any]:
        if self.exchange is None:
            return {}

        try:
            balance = self.exchange.fetch_balance()
        except Exception as exc:
            details = self._log_exchange_exception("Bakiye sorgu hatasi", exc)
            return {"ok": False, "error": details}

        free_usdt = None
        total_usdt = None
        if isinstance(balance, dict):
            free_usdt = (((balance.get("free") or {}).get("USDT")) if isinstance(balance.get("free"), dict) else None)
            total_usdt = (((balance.get("total") or {}).get("USDT")) if isinstance(balance.get("total"), dict) else None)

        snapshot = {
            "ok": True,
            "free_usdt": free_usdt,
            "total_usdt": total_usdt,
        }
        self.logger.info("Bybit balance snapshot | %s", snapshot)
        return snapshot

    def _sync_position_mode(self, symbol: str) -> bool:
        if self.exchange is None:
            return False

        hedged = self.position_mode == "hedge"
        try:
            if hasattr(self.exchange, "set_position_mode"):
                response = self.exchange.set_position_mode(hedged, symbol=symbol)
                self.logger.info("Bybit position mode set | symbol=%s hedged=%s response=%s", symbol, hedged, response)
            else:
                self.logger.info("Bybit position mode set skipped | exchange method unavailable")
            return True
        except Exception as exc:
            self._log_exchange_exception(
                "Position mode ayarlama hatasi",
                exc,
                context={"symbol": symbol, "position_mode": self.position_mode, "hedged": hedged},
            )
            return False

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
            return self._skip("auto_trading_disabled")
        if self.exchange is None:
            self.logger.error("Execution skipped | reason=exchange_not_ready testnet=%s demo_trading=%s key_set=%s secret_set=%s", self.testnet, self.demo_trading, bool(self.api_key), bool(self.api_secret))
            return self._skip("exchange_not_ready")
        if not self.preflight_status.get("ok", False):
            self.logger.error("Execution skipped | reason=preflight_failed status=%s", self.preflight_status)
            return self._skip("preflight_failed", details=self.preflight_status)
        if not self._decision_allows_execution(result):
            decision = (result or {}).get("decision") or {}
            self.logger.info("Execution skipped | reason=decision_blocked action=%s", decision.get("action"))
            return self._skip("decision_blocked", decision_action=decision.get("action"), decision_reason=decision.get("reason"))
        if not self._entry_confidence_ok(result):
            confidence = ((result or {}).get("signal") or {}).get("confidence")
            self.logger.info("Execution skipped | reason=low_confidence confidence=%s min=%s", confidence, self.min_confidence)
            return self._skip("low_confidence", confidence=confidence, required_confidence=self.min_confidence)

        risk = (result or {}).get("risk") or {}
        if risk.get("risk_setup_valid") is False:
            reason = risk.get("risk_setup_reason", "Invalid Risk Setup")
            self.logger.info("Execution skipped | reason=risk_blocked risk_reason=%s", reason)
            return self._skip("risk_blocked", risk_reason=reason)

        side = self._extract_side(result)
        amount = self._extract_amount(result)
        if side is None:
            self.logger.info("Execution skipped | reason=invalid_signal")
            return self._skip("invalid_signal", signal=((result or {}).get("signal") or {}).get("signal"))
        if amount is None:
            self.logger.info("Execution skipped | reason=invalid_amount")
            return self._skip("invalid_amount", position_size=((result or {}).get("risk") or {}).get("position_size"))

        amount, lot_error = self._format_amount_for_market(symbol, amount)
        if amount is None:
            self.logger.info("Execution skipped | reason=min_lot_check_failed detail=%s", lot_error)
            return self._skip("min_lot_check_failed", details=lot_error)

        leverage = self._resolve_leverage(result)
        leverage_applied = self._apply_leverage(symbol=symbol, side=side, leverage=leverage)
        position_mode_synced = self._sync_position_mode(symbol)
        balance = self._balance_snapshot()
        if balance.get("ok") is not True:
            return self._skip("balance_check_failed", details=balance)

        open_pos = self._extract_symbol_position(symbol)
        if open_pos:
            closed = self._close_position_if_needed(symbol, side, open_pos)
            if not closed and ((open_pos.get("side") == "long" and side == "buy") or (open_pos.get("side") == "short" and side == "sell")):
                return self._skip("same_side_position_exists", open_position=open_pos)

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
            order_id = None
            if isinstance(order, dict):
                avg_price = order.get("average") or order.get("price")
                order_id = order.get("id")
            ret_code = self._extract_ret_code(order)
            ret_msg = self._extract_ret_msg(order)
            self.logger.info(
                "Emir acildi | symbol=%s side=%s leverage=%sx leverage_applied=%s amount=%.8f order_id=%s price=%s response=%s",
                symbol,
                side,
                leverage,
                leverage_applied,
                amount,
                order_id,
                avg_price,
                order,
            )
            self.logger.info(
                "Bybit order ack | symbol=%s order_id=%s retCode=%s retMsg=%s",
                symbol,
                order_id,
                ret_code,
                ret_msg,
            )
            return {
                "executed": True,
                "reason": "order_opened",
                "message": "Order Executed Successfully",
                "side": side,
                "amount": amount,
                "leverage": leverage,
                "leverage_applied": leverage_applied,
                "position_mode_synced": position_mode_synced,
                "balance": balance,
                "order_id": order_id,
                "price": avg_price,
                "ret_code": ret_code,
                "ret_msg": ret_msg,
            }
        except Exception as exc:
            details = self._log_exchange_exception(
                "Emir acma hatasi",
                exc,
                context={"symbol": symbol, "payload": request_payload},
            )
            return self._skip(
                "order_failed",
                error=str(exc),
                exchange_error=details,
                ret_code=details.get("retCode"),
                ret_msg=details.get("retMsg"),
            )

    def _resolve_leverage(self, result: Dict[str, Any]) -> int:
        signal = (result or {}).get("signal") or {}
        decision = (result or {}).get("decision") or {}
        risk = (result or {}).get("risk") or {}

        confidence = float(signal.get("confidence") or 0)
        strength = str(signal.get("strength") or "").upper()
        grade = str(signal.get("grade") or "").upper()
        action = str(decision.get("action") or "").upper()
        rr = risk.get("selected_rr") if isinstance(risk.get("selected_rr"), (int, float)) else risk.get("rr")
        rr_value = float(rr) if isinstance(rr, (int, float)) else 0.0

        score = 0.0
        score += min(1.0, max(0.0, confidence / 100.0)) * 0.45
        score += min(1.0, max(0.0, rr_value / 6.0)) * 0.30

        strength_weights = {
            "ELITE": 1.0,
            "STRONG": 0.8,
            "GOOD": 0.65,
            "NORMAL": 0.5,
            "WEAK": 0.35,
            "VERY WEAK": 0.2,
        }
        score += strength_weights.get(strength, 0.35) * 0.15

        grade_weights = {
            "S+": 1.0,
            "A+": 0.9,
            "A": 0.8,
            "B": 0.6,
            "C": 0.4,
            "D": 0.25,
        }
        score += grade_weights.get(grade, 0.35) * 0.10

        if action == "EXECUTE_WITH_CAUTION":
            score *= 0.75

        leverage_span = max(0, self.max_leverage - self.min_leverage)
        leverage = self.min_leverage + int(round(leverage_span * min(1.0, max(0.0, score))))
        leverage = max(self.min_leverage, min(self.max_leverage, leverage))

        self.logger.info(
            "Leverage resolved | symbol_decision=%s confidence=%s rr=%s strength=%s grade=%s leverage=%sx",
            action,
            confidence,
            rr_value,
            strength,
            grade,
            leverage,
        )
        return leverage

    def _apply_leverage(self, symbol: str, side: str, leverage: int) -> bool:
        if self.exchange is None:
            return False

        params = {"buyLeverage": str(leverage), "sellLeverage": str(leverage)}
        position_idx = self._resolve_position_idx(side)
        if position_idx is not None:
            params["positionIdx"] = position_idx

        try:
            self.logger.info("Bybit leverage request | symbol=%s leverage=%sx params=%s", symbol, leverage, params)
            response = self.exchange.set_leverage(leverage, symbol, params=params)
            self.logger.info("Bybit leverage response | symbol=%s response=%s", symbol, response)
            return True
        except Exception as exc:
            self._log_exchange_exception(
                "Leverage ayarlama hatasi",
                exc,
                context={"symbol": symbol, "leverage": leverage, "params": params},
            )
            return False

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

        ret_code, ret_msg = self._extract_ret_fields_from_payload(details)
        if ret_code is not None:
            details["retCode"] = ret_code
        if ret_msg is not None:
            details["retMsg"] = ret_msg

        self.logger.exception("%s | details=%s", prefix, details)
        return details

    def _decode_payload_to_dict(self, payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, dict):
            return payload

        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8", errors="replace")
            except Exception:
                return None

        if not isinstance(payload, str):
            return None

        text = payload.strip()
        if not text:
            return None

        try:
            parsed = json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(text[start : end + 1])
            except Exception:
                return None

        if isinstance(parsed, dict):
            return parsed
        return None

    def _extract_ret_fields_from_payload(self, payload: Any) -> Tuple[Any, Any]:
        candidates = []
        if isinstance(payload, dict):
            candidates.append(payload)
            info = payload.get("info")
            if isinstance(info, dict):
                candidates.append(info)
        else:
            parsed = self._decode_payload_to_dict(payload)
            if isinstance(parsed, dict):
                candidates.append(parsed)

        if isinstance(payload, dict):
            for key in ("body", "response", "message", "reason"):
                parsed = self._decode_payload_to_dict(payload.get(key))
                if isinstance(parsed, dict):
                    candidates.append(parsed)

        for candidate in list(candidates):
            result = candidate.get("result") if isinstance(candidate.get("result"), dict) else None
            if result is not None:
                candidates.append(result)

        ret_code = None
        ret_msg = None
        for candidate in candidates:
            has_code = any(key in candidate for key in ("retCode", "ret_code", "code"))
            if ret_code is None:
                for key in ("retCode", "ret_code", "code"):
                    if key in candidate:
                        ret_code = candidate.get(key)
                        break
            if ret_msg is None:
                for key in ("retMsg", "ret_msg", "msg", "message"):
                    if key == "message" and not has_code:
                        continue
                    if key in candidate:
                        ret_msg = candidate.get(key)
                        break
            if ret_code is not None and ret_msg is not None:
                break

        return ret_code, ret_msg

    def _extract_ret_code(self, order: Any) -> Any:
        ret_code, _ = self._extract_ret_fields_from_payload(order)
        return ret_code

    def _extract_ret_msg(self, order: Any) -> Any:
        _, ret_msg = self._extract_ret_fields_from_payload(order)
        return ret_msg
