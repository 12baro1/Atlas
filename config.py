"""
config.py
Atlas SMC Engine Configuration
"""

import os


def _strip_shell_quotes(value):
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _read_export_from_rc(var_name):
    """Export edilmemis olsa bile kullanici rc dosyalarindan deger okumayi dener."""
    home = os.path.expanduser("~")
    rc_files = (
        os.path.join(home, ".bashrc"),
        os.path.join(home, ".profile"),
        os.path.join(home, ".zshrc"),
    )

    prefix = f"export {var_name}="
    for path in rc_files:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line.startswith(prefix):
                        continue
                    return _strip_shell_quotes(line[len(prefix):])
        except Exception:
            continue
    return ""


def _env_or_rc(var_name, default=""):
    value = os.getenv(var_name, "")
    if value:
        return value
    fallback = _read_export_from_rc(var_name)
    if fallback:
        return fallback
    return default

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
    TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS = float(os.getenv("ATLAS_TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", "0.5"))

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

    @classmethod
    def refresh_from_env(cls):
        """Runtime'da environment değişikliklerini Config sınıfına yeniden yükler."""
        cls.TELEGRAM_MIN_CONFIDENCE = float(_env_or_rc("ATLAS_TELEGRAM_MIN_CONFIDENCE", "75"))
        cls.TELEGRAM_REQUIRE_DECISION_ACTION = _env_or_rc("ATLAS_TELEGRAM_REQUIRE_DECISION_ACTION", "0").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_BOT_TOKEN = _env_or_rc("ATLAS_TELEGRAM_BOT_TOKEN", "")
        cls.TELEGRAM_CHAT_ID = _env_or_rc("ATLAS_TELEGRAM_CHAT_ID", "")
        cls.TELEGRAM_HTTP_TIMEOUT_SECONDS = float(_env_or_rc("ATLAS_TELEGRAM_HTTP_TIMEOUT_SECONDS", "3"))
        cls.TELEGRAM_ASYNC_SEND = _env_or_rc("ATLAS_TELEGRAM_ASYNC_SEND", "1").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS = float(_env_or_rc("ATLAS_TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", "0.5"))
        cls.BOT_PASSWORD = os.getenv("ATLAS_BOT_PASSWORD", "")
        cls.ADMIN_CHAT_ID = int(os.getenv("ATLAS_ADMIN_CHAT_ID", "0"))
        cls.TELEGRAM_ADMIN_IDS = [cls.ADMIN_CHAT_ID]
