"""
bybit_execution_engine.py
Atlas Bybit Canlı İşlem Motoru

Bybit üzerinde sinyal doğrulandıktan sonra emir gönderimi, pozisyon
yönetimi (kaldıraç, SL/TP, kapanış) ve risk-guard'larını yönetir.

Modlar (Config üzerinden):
  - LIVE:    gerçek API anahtarları (ATLAS_BYBIT_TESTNET=0)
  - TESTNET: testnet ağı (varsayılan, ATLAS_BYBIT_TESTNET=1)
  - DEMO:    Bybit demo trading (ATLAS_BYBIT_DEMO_TRADING=1)

GÜVENLİK:
  - API anahtarı / otomatik işlem yetkisi yoksa hiçbir emir gönderilmez.
  - Her emir öncesi ``validate`` zorunludur; hatalıysa emir engellenir.
  - Kaldıraç sınırları Config'den alınır.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from config import Config

LOGGER = logging.getLogger("atlas.bybit.execution")


@dataclass
class OrderResult:
    """Bir emir girişiminin sonucu."""

    success: bool
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    order_type: Optional[str] = None
    price: Optional[float] = None
    amount: Optional[float] = None
    filled: Optional[float] = None
    average: Optional[float] = None
    status: Optional[str] = None
    info: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class BybitExecutionEngine:
    """Bybit emir ve pozisyon yönetimi.

    ``exchange`` verilmezse Config'den uygun bir ccxt Bybit client'ı
    kurulur. Testlerde sahte client enjekte etmek için bu parametre
    kullanılır.
    """

    def __init__(self, exchange: Any = None, config: Union[Config, type, None] = None):
        self.config = config or Config
        Config.refresh_from_env()
        self.logger = logging.getLogger("atlas.bybit.execution")
        if exchange is not None:
            self._client = exchange
        else:
            self._client = self._build_client()

    # ------------------------------------------------------------------ #
    # Client kurulumu
    # ------------------------------------------------------------------ #
    def _build_client(self) -> Any:
        import ccxt

        testnet = bool(getattr(self.config, "BYBIT_TESTNET", True))
        demo = bool(getattr(self.config, "BYBIT_DEMO_TRADING", False))

        client = ccxt.bybit(
            {
                "apiKey": str(getattr(self.config, "BYBIT_API_KEY", "") or "").strip(),
                "secret": str(getattr(self.config, "BYBIT_API_SECRET", "") or "").strip(),
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            }
        )
        if demo:
            setter = getattr(client, "set_demo_trading", None)
            if callable(setter):
                setter(True)
        elif testnet:
            client.set_sandbox_mode(True)
        return client

    # ------------------------------------------------------------------ #
    # Yetkilendirme / sağlık
    # ------------------------------------------------------------------ #
    def has_credentials(self) -> bool:
        key = str(getattr(self.config, "BYBIT_API_KEY", "") or "").strip()
        secret = str(getattr(self.config, "BYBIT_API_SECRET", "") or "").strip()
        return bool(key and secret)

    def enabled(self) -> bool:
        return bool(getattr(self.config, "AUTO_TRADING_ENABLED", False))

    def is_demo(self) -> bool:
        return bool(getattr(self.config, "BYBIT_DEMO_TRADING", False))

    def is_testnet(self) -> bool:
        return bool(getattr(self.config, "BYBIT_TESTNET", True))

    def live_trading(self) -> bool:
        return self.enabled() and self.has_credentials() and not self.is_demo() and not self.is_testnet()

    # ------------------------------------------------------------------ #
    # Doğrulama
    # ------------------------------------------------------------------ #
    @staticmethod
    def _valid_symbol(symbol: str) -> bool:
        return bool(symbol and isinstance(symbol, str) and ":" in symbol)

    def validate(
        self,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        amount: Optional[float] = None,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> List[str]:
        """Emir öncesi doğrulama; boş liste = emir güvenli."""
        issues: List[str] = []

        if not self.enabled():
            issues.append("AUTO_TRADING_ENABLED kapalı")
        if not self.has_credentials():
            issues.append("API anahtarı tanımlı değil")

        if symbol is not None and not self._valid_symbol(symbol):
            issues.append(f"Geçersiz sembol: {symbol!r}")
        if side is not None and str(side).lower() not in ("buy", "sell"):
            issues.append(f"Geçersiz yön: {side!r}")
        if amount is not None and (not isinstance(amount, (int, float)) or amount <= 0):
            issues.append(f"Geçersiz boyut: {amount!r}")
        if price is not None and price <= 0:
            issues.append(f"Geçersiz fiyat: {price}")
        if stop_loss is not None and stop_loss <= 0:
            issues.append(f"Geçersiz SL: {stop_loss}")
        if take_profit is not None and take_profit <= 0:
            issues.append(f"Geçersiz TP: {take_profit}")

        min_lev = int(getattr(self.config, "AUTO_TRADING_MIN_LEVERAGE", 1))
        max_lev = int(getattr(self.config, "AUTO_TRADING_MAX_LEVERAGE", 20))
        if min_lev < 1 or max_lev < 1 or min_lev > max_lev:
            issues.append(f"Geçersiz kaldıraç aralığı: {min_lev}-{max_lev}")

        return issues

    def validate_or_raise(self, **kwargs) -> None:
        issues = self.validate(**kwargs)
        if issues:
            raise ValueError("; ".join(issues))

    # ------------------------------------------------------------------ #
    # Emirler
    # ------------------------------------------------------------------ #
    def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        order_type: str = "market",
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> OrderResult:
        issues = self.validate(symbol=symbol, side=side, amount=amount, price=price)
        if issues:
            self.logger.warning("Emir engellendi: %s", "; ".join(issues))
            return OrderResult(success=False, symbol=symbol, side=side, error="; ".join(issues))

        params = dict(params or {})
        try:
            created = self._client.create_order(
                symbol=symbol,
                type=order_type,
                side=side.lower(),
                amount=amount,
                price=price,
                params=params,
            )
            return OrderResult(
                success=True,
                order_id=created.get("id"),
                client_order_id=created.get("clientOrderId") or created.get("client_order_id"),
                symbol=symbol,
                side=side,
                order_type=order_type,
                price=created.get("price"),
                amount=created.get("amount"),
                filled=created.get("filled"),
                average=created.get("average"),
                status=created.get("status"),
                info=created,
            )
        except Exception as exc:
            self.logger.exception("Emir hatası %s %s", symbol, side)
            return OrderResult(success=False, symbol=symbol, side=side, error=str(exc))

    def open_position(
        self,
        symbol: str,
        side: str,
        amount: float,
        leverage: int = 1,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        """Risk-guard'lı pozisyon açar; SL/TP emirle birlikte bağlanır."""
        issues = self.validate(symbol=symbol, side=side, amount=amount, price=price)
        if issues:
            self.logger.warning("Pozisyon engellendi: %s", "; ".join(issues))
            return OrderResult(success=False, symbol=symbol, side=side, error="; ".join(issues))

        self._set_leverage(symbol, self._clamp_leverage(leverage))

        params: Dict[str, Any] = {}
        if stop_loss is not None:
            params["stopLoss"] = str(stop_loss)
        if take_profit is not None:
            params["takeProfit"] = str(take_profit)

        return self.create_order(
            symbol=symbol,
            side=side,
            amount=amount,
            order_type=order_type,
            price=price,
            params=params or None,
        )

    def close_position(self, symbol: str, side: str, amount: Optional[float] = None) -> OrderResult:
        """Açık pozisyonu reduce-only emirle kapatmayı dener."""
        opposite = "sell" if str(side).lower() in ("buy", "long") else "buy"
        params = {"reduceOnly": True}
        if amount is not None:
            issues = self.validate(symbol=symbol, side=opposite, amount=amount)
            if issues:
                self.logger.warning("Kapatma engellendi: %s", "; ".join(issues))
                return OrderResult(success=False, symbol=symbol, side=side, error="; ".join(issues))
        return self.create_order(
            symbol=symbol,
            side=opposite,
            amount=amount or 0,
            order_type="market",
            params=params,
        )

    # ------------------------------------------------------------------ #
    # Kaldıraç / veri
    # ------------------------------------------------------------------ #
    def _clamp_leverage(self, leverage: Union[int, float]) -> int:
        if not leverage or leverage < 1:
            return 1
        max_lev = int(getattr(self.config, "AUTO_TRADING_MAX_LEVERAGE", 20))
        return min(int(leverage), max_lev)

    def _set_leverage(self, symbol: str, leverage: int) -> Optional[Dict[str, Any]]:
        try:
            return self._client.set_leverage(leverage, symbol)
        except Exception:
            self.logger.warning("Kaldıraç set edilemedi %s %s", symbol, leverage)
            return None

    def fetch_balance(self) -> Dict[str, Any]:
        try:
            return self._client.fetch_balance()
        except Exception:
            self.logger.exception("Bakiye çekilemedi")
            return {}

    def fetch_position(self, symbol: str) -> Dict[str, Any]:
        try:
            positions = self._client.fetch_positions([symbol])
            return positions[0] if positions else {}
        except Exception:
            self.logger.exception("Pozisyon çekilemedi %s", symbol)
            return {}

    def total_equity(self) -> float:
        try:
            balance = self.fetch_balance()
            total = balance.get("total") or {}
            if total:
                return float(total.get("USDT") or 0.0)
            info = balance.get("info") or {}
            return float(info.get("totalEquity") or info.get("walletBalance") or 0.0)
        except Exception:
            self.logger.exception("Equity hesaplanamadi")
            return 0.0

    # ------------------------------------------------------------------ #
    # ccxt proxy
    # ------------------------------------------------------------------ #
    def __getattr__(self, name: str):
        if name.startswith("_") or self._client is None:
            raise AttributeError(name)
        if hasattr(self._client, name):
            return getattr(self._client, name)
        raise AttributeError(name)