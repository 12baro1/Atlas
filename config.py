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
    last_value = ""
    for path in rc_files:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line.startswith(prefix):
                        continue
                    last_value = _strip_shell_quotes(line[len(prefix):])
        except Exception:
            continue
    return last_value


def _read_from_dotenv(var_name):
    """Proje .env dosyasindan anahtar deger okur."""
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(__file__), ".env"),
    ]

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip() != var_name:
                        continue
                    return _strip_shell_quotes(value)
        except Exception:
            continue
    return ""


def _env_or_rc(var_name, default=""):
    value = os.getenv(var_name, "")
    if value:
        return value
    dotenv_value = _read_from_dotenv(var_name)
    if dotenv_value:
        return dotenv_value
    fallback = _read_export_from_rc(var_name)
    if fallback:
        return fallback
    return default

class Config:
    DEFAULT_TELEGRAM_BOT_TOKEN = "8451423294:AAFJ8gmvKPk23ierRsh4u5sX3SRIXk2uDWY"
    DEFAULT_TELEGRAM_CHAT_ID = "6378242540"

    # Risk
    RISK_PERCENT = 1.0
    MINIMUM_RR = 3.0
    ROUND_TRIP_COST_RATE = 0.0020
    ATR_PERIOD = 14
    MIN_STOP_ATR_MULTIPLIER = 0.25
    MIN_TICK_DISTANCE_FALLBACK = 0.01
    STOP_SPREAD_BUFFER_RATE = 0.0002
    STOP_SLIPPAGE_BUFFER_RATE = 0.0003
    AUTO_EXPAND_TIGHT_STOPS = True
    MAX_POSITION_SIZE = 1000.0

    # Confidence
    MINIMUM_CONFIDENCE = 80

    # Decision
    DECISION_SCORE_EXECUTE = 90
    DECISION_SCORE_EXECUTE_WITH_CAUTION = 75
    DECISION_SCORE_WAIT = 60
    DECISION_SCORE_MIN = 0
    DECISION_SCORE_MAX = 100

    DECISION_EXCEPTION_MIN_CONFIDENCE = 95
    DECISION_EXCEPTION_MIN_RR = 3.0
    DECISION_EXCEPTION_MAX_SOFT_BLOCKERS = 1

    DECISION_BONUS_GRADE_S_PLUS = 10
    DECISION_BONUS_ELITE = 10
    DECISION_BONUS_CONFIDENCE_95 = 10
    DECISION_BONUS_RR_3 = 10
    DECISION_BONUS_RR_5 = 15
    DECISION_BONUS_HTF_LTF_ALIGNMENT = 10
    DECISION_BONUS_UNICORN_ALIGNMENT = 8
    DECISION_BONUS_CISD_ALIGNMENT = 8
    DECISION_BONUS_VOLUME_PROFILE_ALIGNMENT = 6

    DECISION_PENALTY_UNICORN_MISMATCH = -10
    DECISION_PENALTY_CISD_MISMATCH = -10
    DECISION_PENALTY_VOLUME_PROFILE_MISMATCH = -8
    DECISION_PENALTY_OTE_MISSING = -5
    DECISION_PENALTY_HTF_ORDERBLOCK_MISSING = -5
    DECISION_PENALTY_SMT_MISSING = -5
    DECISION_PENALTY_LIQUIDITY_SWEEP_MISSING = -4
    DECISION_PENALTY_STACK_CONFLUENCE_MISSING = -4
    DECISION_BONUS_INSTITUTIONAL_ALIGNMENT = 8
    DECISION_PENALTY_INSTITUTIONAL_MISMATCH = -10
    DECISION_BONUS_MARKET_PHASE_FRIENDLY = 5
    DECISION_PENALTY_MARKET_PHASE_UNFRIENDLY = -8

    # Quality Filters
    QUALITY_FILTERS_ENABLED = True
    QUALITY_MIN_GRADE = "S"
    QUALITY_MIN_CONFIDENCE = 95
    QUALITY_MIN_RR = 3.0
    QUALITY_MIN_CONFLUENCE_SCORE = 80
    QUALITY_REQUIRE_MTF_ALIGNMENT = True
    QUALITY_REQUIRE_CISD_ALIGNMENT = True
    QUALITY_REQUIRE_STACK_CONFLUENCE = True
    QUALITY_ALLOWED_MARKET_PHASES = ("Expansion", "Trending", "Reversal")

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
    TELEGRAM_BOT_TOKEN = os.getenv("ATLAS_TELEGRAM_BOT_TOKEN", DEFAULT_TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = os.getenv("ATLAS_TELEGRAM_CHAT_ID", DEFAULT_TELEGRAM_CHAT_ID)
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
        cls.TELEGRAM_BOT_TOKEN = _env_or_rc("ATLAS_TELEGRAM_BOT_TOKEN", cls.DEFAULT_TELEGRAM_BOT_TOKEN)
        cls.TELEGRAM_CHAT_ID = _env_or_rc("ATLAS_TELEGRAM_CHAT_ID", cls.DEFAULT_TELEGRAM_CHAT_ID)
        cls.TELEGRAM_HTTP_TIMEOUT_SECONDS = float(_env_or_rc("ATLAS_TELEGRAM_HTTP_TIMEOUT_SECONDS", "3"))
        cls.TELEGRAM_ASYNC_SEND = _env_or_rc("ATLAS_TELEGRAM_ASYNC_SEND", "1").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS = float(_env_or_rc("ATLAS_TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", "0.5"))
        cls.BOT_PASSWORD = os.getenv("ATLAS_BOT_PASSWORD", "")
        cls.ADMIN_CHAT_ID = int(os.getenv("ATLAS_ADMIN_CHAT_ID", "0"))
        cls.TELEGRAM_ADMIN_IDS = [cls.ADMIN_CHAT_ID]
