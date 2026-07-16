"""
config.py
Atlas SMC Engine Configuration
"""

class Config:

    # Risk
    RISK_PERCENT = 1.0
    MINIMUM_RR = 3.0

    # Confidence
    MINIMUM_CONFIDENCE = 80

    # Sessions (UTC)
    LONDON_START = 7
    LONDON_END = 10

    NEWYORK_START = 12
    NEWYORK_END = 15

    # Timeframes
    WEEKLY = "1w"
    DAILY = "1d"
    H4 = "4h"
    H1 = "1h"
    M15 = "15m"

    # Scanner
    MAX_SYMBOLS = 1000

    # Telegram
    TELEGRAM_ENABLED = False
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""

    # Backtest
    INITIAL_BALANCE = 10000
