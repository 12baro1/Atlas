# ==========================
# SMC-X CONFIG
# ==========================

DEMO = True

EXCHANGE = "bybit"

TIMEFRAMES = {
    "weekly": "1w",
    "daily": "1d",
    "h4": "4h",
    "h1": "1h",
    "m15": "15m"
}

CANDLE_LIMITS = {
    "weekly": 300,
    "daily": 500,
    "h4": 1000,
    "h1": 1000,
    "m15": 1000
}

MIN_SCORE = 90

MAX_OPEN_TRADES = 2

RISK_PERCENT = 1

RR = 3

ENABLE_TELEGRAM = False

ENABLE_NEWS_FILTER = True

ENABLE_VOLUME_FILTER = True

ENABLE_SESSION_FILTER = True

ENABLE_SMT = True

ENABLE_LIQUIDITY = True

ENABLE_ORDERBLOCK = True

ENABLE_FVG = True

ENABLE_CHOCH = True

ENABLE_BOS = True
