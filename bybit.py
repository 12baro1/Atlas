"""
Shared Bybit exchange builders used by Atlas modules.
"""

import ccxt


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
    elif hasattr(exchange, "set_sandbox_mode"):
        exchange.set_sandbox_mode(bool(testnet))
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
