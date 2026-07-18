"""
config.py
Atlas SMC Engine Configuration
"""

import os

class Config:

    # Risk
    RISK_PERCENT = 1.0
    MINIMUM_RR = 3.0
    ROUND_TRIP_COST_RATE = 0.0020

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
    TELEGRAM_ENABLED = True
    TELEGRAM_COMPACT_MODE = True
    TELEGRAM_MAX_DECISION_REASON_LENGTH = 140
    TELEGRAM_SIGNAL_DEDUP_ENABLED = True
    TELEGRAM_SIGNAL_COOLDOWN_MINUTES = 180
    TELEGRAM_MIN_CONFIDENCE = float(os.getenv("ATLAS_TELEGRAM_MIN_CONFIDENCE", "75"))
    TELEGRAM_REQUIRE_DECISION_ACTION = os.getenv("ATLAS_TELEGRAM_REQUIRE_DECISION_ACTION", "0").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_BOT_TOKEN = os.getenv("ATLAS_TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("ATLAS_TELEGRAM_CHAT_ID", "")
    TELEGRAM_HTTP_TIMEOUT_SECONDS = float(os.getenv("ATLAS_TELEGRAM_HTTP_TIMEOUT_SECONDS", "3"))
    TELEGRAM_ASYNC_SEND = os.getenv("ATLAS_TELEGRAM_ASYNC_SEND", "1").strip().lower() in {"1", "true", "yes"}

    # Yetkilendirme
    BOT_PASSWORD = os.getenv("ATLAS_BOT_PASSWORD", "")
    ADMIN_CHAT_ID = int(os.getenv("ATLAS_ADMIN_CHAT_ID", "0"))
    TELEGRAM_ADMIN_IDS = [ADMIN_CHAT_ID]
    BOT_PASSWORD_HASH = ""
    TELEGRAM_AUTH_DB_FILE = "telegram_auth.db"

    # Kullanıcı kayıt dosyası
    CHAT_IDS_FILE = "chat_ids.json"

    # Backtest
    INITIAL_BALANCE = 10000
