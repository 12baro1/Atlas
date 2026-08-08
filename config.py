"""
config.py
Atlas SMC Engine Configuration
"""

import logging
import os

CONFIG_LOGGER = logging.getLogger("atlas.config")


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
    DEFAULT_TELEGRAM_BOT_TOKEN = ""
    DEFAULT_TELEGRAM_CHAT_ID = ""

    # Risk
    RISK_PERCENT = 1.0
    MINIMUM_RR = 3.0
    ROUND_TRIP_COST_RATE = 0.0020
    ATR_PERIOD = 14
    MIN_STOP_ATR_MULTIPLIER = 0.25
    MIN_STOP_PERCENT = 0.0005
    MIN_TICK_DISTANCE_FALLBACK = 0.01
    STOP_SPREAD_BUFFER_RATE = 0.0002
    STOP_SLIPPAGE_BUFFER_RATE = 0.0003
    AUTO_EXPAND_TIGHT_STOPS = True
    REJECT_TIGHT_STOPS = True
    MAX_POSITION_SIZE = 1000.0

    # Confidence
    MINIMUM_CONFIDENCE = 58

    # Decision
    DECISION_SCORE_EXECUTE = 80
    DECISION_SCORE_EXECUTE_WITH_CAUTION = 45
    DECISION_SCORE_WAIT = 35
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
    # HTF/LTF hizalama eksik olduğunda sert engel yerine skor cezası (yumuşak).
    # Güçlü confluence/entry içeren kaliteli contrarian LONG'ların gereksiz SKIP
    # olmasını önlemek için -; skor düşer ama doğrudan sinyali öldürmez.
    DECISION_PENALTY_HTF_ALIGNMENT_MISSING = -40
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
    QUALITY_MIN_GRADE = "C"
    QUALITY_MIN_CONFIDENCE = 58
    QUALITY_MIN_RR = 3.0
    QUALITY_MIN_CONFLUENCE_SCORE = 55
    QUALITY_REQUIRE_MTF_ALIGNMENT = True
    QUALITY_REQUIRE_CISD_ALIGNMENT = False
    QUALITY_REQUIRE_STACK_CONFLUENCE = False
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
    MAX_SYMBOLS = int(os.getenv("ATLAS_MAX_SYMBOLS", "0").strip() or "0")

    # Bybit / Auto Trading
    AUTO_TRADING_ENABLED = os.getenv("ATLAS_AUTO_TRADING_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
    AUTO_TRADING_AUTO_ENABLE_WITH_KEYS = os.getenv("ATLAS_AUTO_TRADING_AUTO_ENABLE_WITH_KEYS", "1").strip().lower() in {"1", "true", "yes"}
    AUTO_TRADING_MIN_CONFIDENCE = float(os.getenv("ATLAS_AUTO_TRADING_MIN_CONFIDENCE", "85"))
    AUTO_TRADING_ALLOW_EXECUTE_WITH_CAUTION = os.getenv("ATLAS_AUTO_TRADING_ALLOW_EXECUTE_WITH_CAUTION", "0").strip().lower() in {"1", "true", "yes"}
    AUTO_TRADING_MIN_LEVERAGE = int(float(os.getenv("ATLAS_AUTO_TRADING_MIN_LEVERAGE", "1")))
    AUTO_TRADING_MAX_LEVERAGE = int(float(os.getenv("ATLAS_AUTO_TRADING_MAX_LEVERAGE", "20")))
    BYBIT_TESTNET = os.getenv("ATLAS_BYBIT_TESTNET", "1").strip().lower() in {"1", "true", "yes"}
    BYBIT_DEMO_TRADING = os.getenv("ATLAS_BYBIT_DEMO_TRADING", "0").strip().lower() in {"1", "true", "yes"}
    BYBIT_API_KEY = _env_or_rc("ATLAS_BYBIT_API_KEY", "")
    BYBIT_API_SECRET = _env_or_rc("ATLAS_BYBIT_API_SECRET", "")
    BYBIT_POSITION_MODE = _env_or_rc("ATLAS_BYBIT_POSITION_MODE", "one_way").strip().lower()
    BYBIT_LOG_HTTP = _env_or_rc("ATLAS_BYBIT_LOG_HTTP", "0").strip().lower() in {"1", "true", "yes"}

    # Telegram
    TELEGRAM_ENABLED = True
    TELEGRAM_COMPACT_MODE = True
    TELEGRAM_MINIMAL_LAYOUT = os.getenv("ATLAS_TELEGRAM_MINIMAL_LAYOUT", "1").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_MAX_DECISION_REASON_LENGTH = 140
    TELEGRAM_SIGNAL_DEDUP_ENABLED = True
    TELEGRAM_SIGNAL_COOLDOWN_MINUTES = 180
    TELEGRAM_MIN_CONFIDENCE = float(os.getenv("ATLAS_TELEGRAM_MIN_CONFIDENCE", "85"))
    TELEGRAM_REQUIRE_DECISION_ACTION = os.getenv("ATLAS_TELEGRAM_REQUIRE_DECISION_ACTION", "1").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_QUALITY_FILTERS_ENABLED = os.getenv("ATLAS_TELEGRAM_QUALITY_FILTERS_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_MIN_GRADE = os.getenv("ATLAS_TELEGRAM_MIN_GRADE", "A").strip().upper()
    TELEGRAM_MIN_RR = float(os.getenv("ATLAS_TELEGRAM_MIN_RR", "3.0"))
    TELEGRAM_ALLOW_CAUTION_SIGNALS = os.getenv("ATLAS_TELEGRAM_ALLOW_CAUTION_SIGNALS", "0").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_MIN_CONFLUENCE_SCORE = float(os.getenv("ATLAS_TELEGRAM_MIN_CONFLUENCE_SCORE", "70"))
    TELEGRAM_REQUIRE_MTF_ALIGNMENT = os.getenv("ATLAS_TELEGRAM_REQUIRE_MTF_ALIGNMENT", "1").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_ALLOWED_MARKET_PHASES = tuple(
        item.strip() for item in os.getenv("ATLAS_TELEGRAM_ALLOWED_MARKET_PHASES", "Expansion,Trending,Reversal").split(",") if item.strip()
    )
    TELEGRAM_MIN_MANUAL_SCORE = float(os.getenv("ATLAS_TELEGRAM_MIN_MANUAL_SCORE", "75"))
    TELEGRAM_HISTORICAL_MIN_TRADES = int(os.getenv("ATLAS_TELEGRAM_HISTORICAL_MIN_TRADES", "20"))
    TELEGRAM_HISTORICAL_MIN_EXPECTANCY = float(os.getenv("ATLAS_TELEGRAM_HISTORICAL_MIN_EXPECTANCY", "0.30"))
    TELEGRAM_HISTORICAL_MIN_PROFIT_FACTOR = float(os.getenv("ATLAS_TELEGRAM_HISTORICAL_MIN_PROFIT_FACTOR", "1.30"))
    TELEGRAM_HISTORICAL_STRICT = os.getenv("ATLAS_TELEGRAM_HISTORICAL_STRICT", "0").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_BOT_TOKEN = os.getenv("ATLAS_TELEGRAM_BOT_TOKEN", DEFAULT_TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = os.getenv("ATLAS_TELEGRAM_CHAT_ID", DEFAULT_TELEGRAM_CHAT_ID)
    TELEGRAM_HTTP_TIMEOUT_SECONDS = float(os.getenv("ATLAS_TELEGRAM_HTTP_TIMEOUT_SECONDS", "3"))
    TELEGRAM_ASYNC_SEND = os.getenv("ATLAS_TELEGRAM_ASYNC_SEND", "1").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS = float(os.getenv("ATLAS_TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", "0.5"))


    # State / Incremental Analysis
    STATE_ENGINE_ENABLED = os.getenv("ATLAS_STATE_ENGINE_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    STATE_ENGINE_FILE = os.getenv("ATLAS_STATE_ENGINE_FILE", "atlas_state.json")
    INCREMENTAL_ANALYSIS_ENABLED = os.getenv("ATLAS_INCREMENTAL_ANALYSIS_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    INCREMENTAL_WARMUP_CANDLES = int(os.getenv("ATLAS_INCREMENTAL_WARMUP_CANDLES", "250"))

    # Macro / correlation / cooldown / learning
    ECONOMIC_NEWS_FILTER_ENABLED = os.getenv("ATLAS_ECONOMIC_NEWS_FILTER_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    ECONOMIC_NEWS_EVENTS_FILE = os.getenv("ATLAS_ECONOMIC_NEWS_EVENTS_FILE", "economic_events.json")
    ECONOMIC_NEWS_BLOCK_BEFORE_MINUTES = int(os.getenv("ATLAS_ECONOMIC_NEWS_BLOCK_BEFORE_MINUTES", "45"))
    ECONOMIC_NEWS_BLOCK_AFTER_MINUTES = int(os.getenv("ATLAS_ECONOMIC_NEWS_BLOCK_AFTER_MINUTES", "30"))
    CORRELATION_ENGINE_ENABLED = os.getenv("ATLAS_CORRELATION_ENGINE_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    # Trend guzun ATR-normalize fark kati olarak olcer (@trade styr dbs ayarlanabilir).
    # Daha yuksek deger = daha az korumaci (yalnizca gercek guclu trend engeller).
    CORRELATION_BTC_BEAR_TREND_MULT = float(os.getenv("ATLAS_CORRELATION_BTC_BEAR_TREND_MULT", "0.30"))
    CORRELATION_BTC_BULL_TREND_MULT = float(os.getenv("ATLAS_CORRELATION_BTC_BULL_TREND_MULT", "0.30"))
    CORRELATION_USDT_RISK_OFF_MULT = float(os.getenv("ATLAS_CORRELATION_USDT_RISK_OFF_MULT", "0.30"))
    TRADE_COOLDOWN_MINUTES = float(os.getenv("ATLAS_TRADE_COOLDOWN_MINUTES", "180"))
    LEARNING_ENGINE_ENABLED = os.getenv("ATLAS_LEARNING_ENGINE_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    LEARNING_ENGINE_FILE = os.getenv("ATLAS_LEARNING_ENGINE_FILE", "atlas_learning.json")

    # Yetkilendirme
    BOT_PASSWORD = os.getenv("ATLAS_BOT_PASSWORD", "")
    ADMIN_CHAT_ID = int(os.getenv("ATLAS_ADMIN_CHAT_ID", "0"))
    TELEGRAM_ADMIN_IDS = [ADMIN_CHAT_ID]
    BOT_PASSWORD_HASH = ""
    TELEGRAM_AUTH_DB_FILE = "telegram_auth.db"
    TELEGRAM_POLLING_ENABLED = os.getenv("ATLAS_TELEGRAM_POLLING_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_POLLING_INTERVAL_SECONDS = float(os.getenv("ATLAS_TELEGRAM_POLLING_INTERVAL_SECONDS", "2"))
    TELEGRAM_WEBHOOK_ENABLED = os.getenv("ATLAS_TELEGRAM_WEBHOOK_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_WEBHOOK_HOST = os.getenv("ATLAS_TELEGRAM_WEBHOOK_HOST", "0.0.0.0")
    TELEGRAM_WEBHOOK_PORT = int(os.getenv("ATLAS_TELEGRAM_WEBHOOK_PORT", "8080"))

    # Kullanıcı kayıt dosyası
    CHAT_IDS_FILE = "chat_ids.json"

    # Backtest
    INITIAL_BALANCE = 10000

    # Canlı sinyal sonuç takibi (trade journal)
    SIGNAL_TRACKING_ENABLED = os.getenv("ATLAS_SIGNAL_TRACKING_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    TRADE_JOURNAL_DB_FILE = os.getenv("ATLAS_TRADE_JOURNAL_DB_FILE", "atlas_journal.db")
    # DB büyüme kontrolü: eski snapshot'lar aten_expiry süresi (gün) sonrası arşive taşınır.
    # JOURNAL_RETENTION_DAYS=0 ise arşivleme devre dışı kalır (her şey kalıcı).
    JOURNAL_RETENTION_DAYS = int(os.getenv("ATLAS_JOURNAL_RETENTION_DAYS", "30"))
    # Bellekte kalan maksimum snapshot sayısı; üzerine çıkanlar en eskiden arşive taşınır.
    # Varsayılan 5000: ~115KB/snapshot → aktif tablo ~575MB'de sınırlanır (önceki 30000
    # aktif tabloyu ~3.4GB'a şişiriyordu). Geçmiş yine gzip'li arşivde kalır.
    JOURNAL_RETENTION_MAX_SNAPSHOTS = int(os.getenv("ATLAS_JOURNAL_RETENTION_MAX_SNAPSHOTS", "5000"))

    @classmethod
    def refresh_from_env(cls):
        """Runtime'da environment değişikliklerini Config sınıfına yeniden yükler."""
        cls.MIN_STOP_PERCENT = float(_env_or_rc("ATLAS_MIN_STOP_PERCENT", str(cls.MIN_STOP_PERCENT)))
        cls.REJECT_TIGHT_STOPS = _env_or_rc("ATLAS_REJECT_TIGHT_STOPS", "1").strip().lower() in {"1", "true", "yes"}
        cls.AUTO_TRADING_ENABLED = _env_or_rc("ATLAS_AUTO_TRADING_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
        cls.AUTO_TRADING_AUTO_ENABLE_WITH_KEYS = _env_or_rc("ATLAS_AUTO_TRADING_AUTO_ENABLE_WITH_KEYS", "1").strip().lower() in {"1", "true", "yes"}
        cls.AUTO_TRADING_MIN_CONFIDENCE = float(_env_or_rc("ATLAS_AUTO_TRADING_MIN_CONFIDENCE", "85"))
        cls.AUTO_TRADING_ALLOW_EXECUTE_WITH_CAUTION = _env_or_rc("ATLAS_AUTO_TRADING_ALLOW_EXECUTE_WITH_CAUTION", "0").strip().lower() in {"1", "true", "yes"}
        cls.AUTO_TRADING_MIN_LEVERAGE = int(float(_env_or_rc("ATLAS_AUTO_TRADING_MIN_LEVERAGE", "1")))
        cls.AUTO_TRADING_MAX_LEVERAGE = int(float(_env_or_rc("ATLAS_AUTO_TRADING_MAX_LEVERAGE", "20")))
        cls.BYBIT_TESTNET = _env_or_rc("ATLAS_BYBIT_TESTNET", "1").strip().lower() in {"1", "true", "yes"}
        cls.BYBIT_DEMO_TRADING = _env_or_rc("ATLAS_BYBIT_DEMO_TRADING", "0").strip().lower() in {"1", "true", "yes"}
        cls.BYBIT_API_KEY = _env_or_rc("ATLAS_BYBIT_API_KEY", "")
        cls.BYBIT_API_SECRET = _env_or_rc("ATLAS_BYBIT_API_SECRET", "")
        cls.BYBIT_POSITION_MODE = _env_or_rc("ATLAS_BYBIT_POSITION_MODE", "one_way").strip().lower()
        cls.BYBIT_LOG_HTTP = _env_or_rc("ATLAS_BYBIT_LOG_HTTP", "0").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_MIN_CONFIDENCE = float(_env_or_rc("ATLAS_TELEGRAM_MIN_CONFIDENCE", "85"))
        cls.TELEGRAM_REQUIRE_DECISION_ACTION = _env_or_rc("ATLAS_TELEGRAM_REQUIRE_DECISION_ACTION", "1").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_QUALITY_FILTERS_ENABLED = _env_or_rc("ATLAS_TELEGRAM_QUALITY_FILTERS_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_MIN_GRADE = _env_or_rc("ATLAS_TELEGRAM_MIN_GRADE", "A").strip().upper()
        cls.TELEGRAM_MIN_RR = float(_env_or_rc("ATLAS_TELEGRAM_MIN_RR", "3.0"))
        cls.TELEGRAM_ALLOW_CAUTION_SIGNALS = _env_or_rc("ATLAS_TELEGRAM_ALLOW_CAUTION_SIGNALS", "0").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_MIN_CONFLUENCE_SCORE = float(_env_or_rc("ATLAS_TELEGRAM_MIN_CONFLUENCE_SCORE", "70"))
        cls.TELEGRAM_REQUIRE_MTF_ALIGNMENT = _env_or_rc("ATLAS_TELEGRAM_REQUIRE_MTF_ALIGNMENT", "1").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_ALLOWED_MARKET_PHASES = tuple(
            item.strip() for item in _env_or_rc("ATLAS_TELEGRAM_ALLOWED_MARKET_PHASES", "Expansion,Trending,Reversal").split(",") if item.strip()
        )
        cls.TELEGRAM_MIN_MANUAL_SCORE = float(_env_or_rc("ATLAS_TELEGRAM_MIN_MANUAL_SCORE", "75"))
        cls.TELEGRAM_HISTORICAL_MIN_TRADES = int(_env_or_rc("ATLAS_TELEGRAM_HISTORICAL_MIN_TRADES", "20"))
        cls.TELEGRAM_HISTORICAL_MIN_EXPECTANCY = float(_env_or_rc("ATLAS_TELEGRAM_HISTORICAL_MIN_EXPECTANCY", "0.30"))
        cls.TELEGRAM_HISTORICAL_MIN_PROFIT_FACTOR = float(_env_or_rc("ATLAS_TELEGRAM_HISTORICAL_MIN_PROFIT_FACTOR", "1.30"))
        cls.TELEGRAM_HISTORICAL_STRICT = _env_or_rc("ATLAS_TELEGRAM_HISTORICAL_STRICT", "0").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_MINIMAL_LAYOUT = _env_or_rc("ATLAS_TELEGRAM_MINIMAL_LAYOUT", "1").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_BOT_TOKEN = _env_or_rc("ATLAS_TELEGRAM_BOT_TOKEN", cls.DEFAULT_TELEGRAM_BOT_TOKEN)
        cls.TELEGRAM_CHAT_ID = _env_or_rc("ATLAS_TELEGRAM_CHAT_ID", cls.DEFAULT_TELEGRAM_CHAT_ID)
        cls.TELEGRAM_HTTP_TIMEOUT_SECONDS = float(_env_or_rc("ATLAS_TELEGRAM_HTTP_TIMEOUT_SECONDS", "3"))
        cls.TELEGRAM_ASYNC_SEND = _env_or_rc("ATLAS_TELEGRAM_ASYNC_SEND", "1").strip().lower() in {"1", "true", "yes"}
        cls.TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS = float(_env_or_rc("ATLAS_TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", "0.5"))
        cls.BOT_PASSWORD = os.getenv("ATLAS_BOT_PASSWORD", "")
        cls.ADMIN_CHAT_ID = int(os.getenv("ATLAS_ADMIN_CHAT_ID", "0"))
        cls.TELEGRAM_ADMIN_IDS = [cls.ADMIN_CHAT_ID]

    @classmethod
    def validate(cls, logger=None, raise_on_error=False):
        """Merkezi yapılandırma doğrulaması.

        Kritik ayarları kontrol eder; sorunları loglar.
        ``raise_on_error=True`` ise ilk kritik hata da ValueError fırlatır.
        Dönüş: (hata sayısı, uyarı sayısı)
        """
        log = logger or CONFIG_LOGGER
        errors = 0
        warnings = 0

        # Kritik risk değerleri
        if cls.MINIMUM_RR < 1.0:
            log.warning("MINIMUM_RR >= 1 olmalı (Risk/Ödül oranı). Mevcut: %s", cls.MINIMUM_RR)
            warnings += 1
        if cls.RISK_PERCENT <= 0 or cls.RISK_PERCENT > 10:
            log.warning("RISK_PERCENT 0-10 aralığında olmalı (riskli per işlem). Mevcut: %s", cls.RISK_PERCENT)
            warnings += 1
        if cls.MIN_STOP_PERCENT <= 0:
            log.error("MIN_STOP_PERCENT > 0 olmalı. Mevcut: %s", cls.MIN_STOP_PERCENT)
            errors += 1
        if cls.MAX_POSITION_SIZE <= 0:
            log.error("MAX_POSITION_SIZE > 0 olmalı. Mevcut: %s", cls.MAX_POSITION_SIZE)
            errors += 1

        # Kaldıraç aralığı
        min_lev = int(getattr(cls, "AUTO_TRADING_MIN_LEVERAGE", 1))
        max_lev = int(getattr(cls, "AUTO_TRADING_MAX_LEVERAGE", 20))
        if min_lev < 1 or max_lev < 1 or min_lev > max_lev:
            log.error("Geçersiz kaldıraç aralığı: %s-%s", min_lev, max_lev)
            errors += 1

        # Otomatik işlem güvenlik kontrolü
        auto = bool(getattr(cls, "AUTO_TRADING_ENABLED", False))
        if auto:
            key = str(getattr(cls, "BYBIT_API_KEY", "") or "").strip()
            secret = str(getattr(cls, "BYBIT_API_SECRET", "") or "").strip()
            testnet = bool(getattr(cls, "BYBIT_TESTNET", True))
            demo = bool(getattr(cls, "BYBIT_DEMO_TRADING", False))
            if not (key and secret):
                log.error("AUTO_TRADING acik ama Bybit API anahtari/secret eksik.")
                errors += 1
            if not testnet and not demo:
                log.warning("AUTO_TRADING CANLI modda calisiyor (LIVE). Para riski var!")
                warnings += 1

        # Telegram
        if cls.TELEGRAM_ENABLED:
            token = str(getattr(cls, "TELEGRAM_BOT_TOKEN", "") or "").strip()
            chat_id = str(getattr(cls, "TELEGRAM_CHAT_ID", "") or "").strip()
            if not token:
                log.warning("TELEGRAM_ENABLED acik ama BOT_TOKEN yok. Bildirim gonderilemez.")
                warnings += 1
            if not chat_id:
                log.warning("TELEGRAM_BOT_TOKEN var ama CHAT_ID yok; hedef belirsiz.")
                warnings += 1

        # Zaman dilimi sabitleri
        if not (0 <= cls.LONDON_START < 24) or not (0 <= cls.LONDON_END < 24):
            log.error("Geçersiz LONDON saat aralığı: %s-%s", cls.LONDON_START, cls.LONDON_END)
            errors += 1
        if not (0 <= cls.NEWYORK_START < 24) or not (0 <= cls.NEWYORK_END < 24):
            log.error("Geçersiz NEWYORK saat aralığı: %s-%s", cls.NEWYORK_START, cls.NEWYORK_END)
            errors += 1

        # Anlamlı skor eşikleri
        if cls.DECISION_SCORE_MAX <= cls.DECISION_SCORE_MIN:
            log.error("DECISION skor aralığı geçersiz: min=%s max=%s", cls.DECISION_SCORE_MIN, cls.DECISION_SCORE_MAX)
            errors += 1

        if errors and raise_on_error:
            raise ValueError(f"Config validation {errors} hata buldu; düzeltilmeden devam edilmemeli.")

        if errors or warnings:
            log.warning("Config doğrulaması | hata=%s uyarı=%s", errors, warnings)
        return errors, warnings

    @classmethod
    def validate_or_raise(cls, logger=None):
        """Doğrulama hatası varsa ValueError fırlatır (startup çağrısı)."""
        errors, _ = cls.validate(logger=logger, raise_on_error=True)
        if errors:
            raise ValueError(f"Config doğrulama hatası: {errors} problem.")
        return True
