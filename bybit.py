"""
Shared Bybit exchange builders used by Atlas modules.

Bybit üç ayrı ortam sunar:
  - Mainnet   : ATLAS_BYBIT_TESTNET=0  ATLAS_BYBIT_DEMO_TRADING=0  → api.bybit.com
  - Testnet   : ATLAS_BYBIT_TESTNET=1  ATLAS_BYBIT_DEMO_TRADING=0  → api-testnet.bybit.com
                (Anahtarlar testnet.bybit.com adresinden oluşturulmalıdır)
  - Demo Trade: ATLAS_BYBIT_TESTNET=0  ATLAS_BYBIT_DEMO_TRADING=1  → api-demo.bybit.com
                (Anahtarlar ana Bybit hesabınızda Demo Trading bölümünden oluşturulmalıdır)

retCode 10003 (API key is invalid) → anahtarın türü ile endpoint uyuşmuyor demektir.
"""

import logging

import ccxt

_LOG = logging.getLogger("atlas.bybit")


def _resolve_endpoint_url(exchange) -> str:
    """Exchange'in fiilen kullandığı endpoint URL'ini döndürür (loglama için)."""
    try:
        urls = exchange.urls.get("api") or {}
        hostname = getattr(exchange, "hostname", "bybit.com")
        if isinstance(urls, str):
            return urls.replace("{hostname}", hostname)
        spot = urls.get("spot") or urls.get("public") or (list(urls.values())[0] if urls else "unknown")
        return str(spot).replace("{hostname}", hostname)
    except Exception:
        return "unknown"


def _apply_trading_mode(exchange, testnet, demo_trading=False):
    """Apply Bybit environment mode to a ccxt exchange instance.

    Bybit demo trading and testnet/sandbox are different environments.
    Demo API keys must use ccxt's demo-trading mode, while testnet keys
    use sandbox mode.
    """
    if demo_trading:
        if hasattr(exchange, "enable_demo_trading"):
            exchange.enable_demo_trading(True)
        elif hasattr(exchange, "enableDemoTrading"):
            exchange.enableDemoTrading(True)
        else:
            _LOG.warning(
                "Bybit demo trading metodu bulunamadi (ccxt surumu eski olabilir); "
                "mainnet endpoint kullaniliyor. ccxt'yi guncelleyin."
            )
    elif testnet:
        if hasattr(exchange, "set_sandbox_mode"):
            exchange.set_sandbox_mode(True)
        else:
            _LOG.warning("set_sandbox_mode desteklenmiyor; mainnet endpoint kullaniliyor.")

    endpoint = _resolve_endpoint_url(exchange)
    _LOG.info(
        "Bybit exchange modu ayarlandi | testnet=%s demo_trading=%s endpoint=%s",
        testnet,
        demo_trading,
        endpoint,
    )
    return exchange


def create_public_swap_exchange(testnet=False, enable_rate_limit=True, demo_trading=False):
    exchange = ccxt.bybit(
        {
            "options": {"defaultType": "swap"},
            "enableRateLimit": bool(enable_rate_limit),
        }
    )
    return _apply_trading_mode(exchange, testnet, demo_trading=demo_trading)


def create_private_swap_exchange(api_key, api_secret, testnet=True, enable_rate_limit=True, demo_trading=False):
    exchange = ccxt.bybit(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "swap"},
            "enableRateLimit": bool(enable_rate_limit),
        }
    )
    return _apply_trading_mode(exchange, testnet, demo_trading=demo_trading)
