"""
Shared Bybit exchange builders used by Atlas modules.
"""

import ccxt


def _apply_sandbox(exchange, testnet):
    if hasattr(exchange, "set_sandbox_mode"):
        exchange.set_sandbox_mode(bool(testnet))
    return exchange


def create_public_swap_exchange(testnet=False, enable_rate_limit=True):
    exchange = ccxt.bybit(
        {
            "options": {"defaultType": "swap"},
            "enableRateLimit": bool(enable_rate_limit),
        }
    )
    return _apply_sandbox(exchange, testnet)


def create_private_swap_exchange(api_key, api_secret, testnet=True, enable_rate_limit=True):
    exchange = ccxt.bybit(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "swap"},
            "enableRateLimit": bool(enable_rate_limit),
        }
    )
    return _apply_sandbox(exchange, testnet)
