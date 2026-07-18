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
    TELEGRAM_ENABLED = True
    TELEGRAM_BOT_TOKEN = "8451423294:AAFJ8gmvKPk23ierRsh4u5sX3SRIXk2uDWY"
    TELEGRAM_CHAT_ID = ""   # Boş bırakılacak

    # Yetkilendirme
    BOT_PASSWORD = "313131"
    ADMIN_CHAT_ID = 6378242540
    TELEGRAM_ADMIN_IDS = [ADMIN_CHAT_ID]
    BOT_PASSWORD_HASH = ""
    TELEGRAM_AUTH_DB_FILE = "telegram_auth.db"

    # Kullanıcı kayıt dosyası
    CHAT_IDS_FILE = "chat_ids.json"

    # Backtest
    INITIAL_BALANCE = 10000
