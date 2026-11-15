import time
import math
import os
import ccxt
from core.candle import Candle
from sector_universe import configured_sector_peers
from trace_context import ensure_trace, record_stage

# Bybit API olmadan sadece public veri için exchange oluştur
exchange = ccxt.bybit({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})

TIMEFRAMES = {
    "1w": 300,
    "1d": 500,
    "4h": 1000,
    "1h": 1000,
    "15m": 1000,
}

# Üst TF'ler yavaş değişir; her taramada yeniden çekmek yerine TTL önbellek.
# 15m larç hızlı değiştiği için çok kısa TTL'li ya da önbelleksiz tutulur.
TF_CACHE_TTL_SECONDS = {
    "1w": 3600,
    "1d": 3600,
    "4h": 900,
    "1h": 300,
    "15m": 0,
}

_cache = {}


def _fetch(symbol, timeframe, limit):
    """Fetch validated, fully closed candles only.

    Bybit/CCXT commonly includes the currently forming candle as the final
    OHLCV row. Returning it to SMC/MTF engines creates moving structure and
    inconsistent signals. Invalid, duplicate, or out-of-order rows are
    discarded; the last candle is retained only after its timeframe closes.
    """
    raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit) or []
    try:
        timeframe_ms = int(exchange.parse_timeframe(timeframe) * 1000)
        now_ms = int(exchange.milliseconds())
    except (AttributeError, TypeError, ValueError, OverflowError):
        timeframe_ms = 0
        now_ms = 0

    candles = []
    previous_time = None
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            timestamp = int(row[0])
            values = [float(value) for value in row[1:6]]
        except (TypeError, ValueError, OverflowError):
            continue
        open_price, high, low, close, volume = values
        if timestamp <= 0 or any(not math.isfinite(v) for v in values):
            continue
        if min(open_price, high, low, close) <= 0 or volume < 0:
            continue
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            continue
        if previous_time is not None and timestamp <= previous_time:
            continue
        previous_time = timestamp
        if timeframe_ms > 0 and now_ms > 0 and timestamp + timeframe_ms > now_ms:
            continue
        candles.append(Candle(
            time=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        ))
    return candles


def fetch_candles(symbol, timeframe, limit, force_refresh=False):
    now = time.time()
    # limit'i anahtara kat: aynı sembol/ZF farklı limitlerle istenirse
    # birbirinin önbellek kaydını kirletip warmup eksikliği yaratmasın.
    key = (symbol, timeframe, limit)

    if not force_refresh and timeframe != "15m":
        cached = _cache.get(key)
        if cached is not None:
            candles, fetched_at = cached
            ttl = TF_CACHE_TTL_SECONDS.get(timeframe, 0)
            if now - fetched_at <= ttl:
                return candles

    candles = _fetch(symbol, timeframe, limit)
    _cache[key] = (candles, now)
    return candles


def invalidate_all():
    """Zorunlu tazeleme için tüm piyasa veri önbelleklerini boşaltır."""
    _cache.clear()
    if "_smt_cache" in globals():
        _smt_cache.clear()


def get_market_data(symbol, force_refresh=False):
    data = {"symbol": symbol}
    # Trace kimliği analiz başında bir kez üretilir; tüm aşamalar aynı kimliği taşır.
    ensure_trace(data)
    # Start one shared public stream per symbol; REST remains the fallback.
    from config import Config
    stream_snapshot = {}
    try:
        from strategies.orderflow.websocket_collector import BybitPublicStream
        stream = BybitPublicStream.for_symbol(symbol)
        stream.start()
        # İlk geçerli snapshot için sınırlı bekleme: ilk mesajlar gelmeden
        # snapshot almak orderbook/trade verisini boş bırakırdı. Sonsuz
        # bekleme yoktur; süre dolarsa REST fallback kullanılır.
        stream_snapshot = stream.snapshot(
            int(exchange.milliseconds()),
            wait_ms=float(getattr(Config, "WS_FIRST_SNAPSHOT_TIMEOUT_MS", 2500.0)),
        )
    except Exception:
        stream_snapshot = {}
    record_stage(
        data,
        "DATA_COLLECTION",
        source="BYBIT_V5_PUBLIC_WEBSOCKET",
        timestamp_ms=int(exchange.milliseconds()),
        availability="AVAILABLE" if stream_snapshot.get("last_message_timestamp_ms") else "UNAVAILABLE",
        freshness="FRESH" if stream_snapshot.get("last_message_timestamp_ms") else "NO_MESSAGE",
        reason=None if stream_snapshot.get("last_message_timestamp_ms") else "WS_NO_FIRST_MESSAGE_BEFORE_TIMEOUT",
        detail={
            "ws_connected": bool(stream_snapshot.get("connected")),
            "wait_ms": float(getattr(Config, "WS_FIRST_SNAPSHOT_TIMEOUT_MS", 2500.0)),
        },
    )
    # Public Bybit REST order-book snapshot; optional fallback.
    data["snapshot_timestamp_ms"] = int(exchange.milliseconds())
    data["orderbook_timestamp_ms"] = None
    data["orderbook_source"] = "UNAVAILABLE"
    try:
        data["orderbook"] = exchange.fetch_order_book(symbol, limit=50)
        book_timestamp = data["orderbook"].get("timestamp") if isinstance(data["orderbook"], dict) else None
        data["orderbook_timestamp_ms"] = int(book_timestamp) if book_timestamp is not None else int(exchange.milliseconds())
    except Exception:
        data["orderbook"] = None
    book_age_ms = None
    if data["orderbook_timestamp_ms"] is not None:
        book_age_ms = max(0, data["snapshot_timestamp_ms"] - data["orderbook_timestamp_ms"])

    # Recent executed trades provide taker buy/sell delta. This is a short
    # rolling sample, not a historical cumulative-volume-delta series.
    data["recent_trades_timestamp_ms"] = None
    data["recent_trades_source"] = "UNAVAILABLE"
    try:
        data["recent_trades"] = exchange.fetch_trades(symbol, limit=200)
        valid_trade_times = [
            int(item["timestamp"]) for item in (data["recent_trades"] or [])
            if isinstance(item, dict) and item.get("timestamp") is not None
        ]
        data["recent_trades_timestamp_ms"] = max(valid_trade_times) if valid_trade_times else None
    except Exception:
        data["recent_trades"] = None
    trades_age_ms = None
    if data["recent_trades_timestamp_ms"] is not None:
        trades_age_ms = max(0, data["snapshot_timestamp_ms"] - data["recent_trades_timestamp_ms"])

    # Prefer fresh WebSocket L2/trades and actual liquidation events. Kaynak
    # etiketi yalnızca gerçekten kullanılan taze veriden gelir; bağlantı
    # kurulması tek başına WebSocket verisinin kullanıldığı anlamına gelmez.
    if stream_snapshot.get("orderbook") is not None:
        data["orderbook"] = stream_snapshot["orderbook"]
        data["orderbook_timestamp_ms"] = stream_snapshot.get("orderbook_timestamp_ms")
        data["orderbook_source"] = "WEBSOCKET"
    elif data.get("orderbook"):
        data["orderbook_source"] = "REST"
    if stream_snapshot.get("recent_trades"):
        data["recent_trades"] = stream_snapshot["recent_trades"]
        data["recent_trades_timestamp_ms"] = stream_snapshot.get("recent_trades_timestamp_ms")
        data["recent_trades_source"] = "WEBSOCKET"
    elif data.get("recent_trades"):
        data["recent_trades_source"] = "REST"
    data["trade_flow_history"] = stream_snapshot.get("trade_flow_history") or []
    data["trade_flow_history_source"] = stream_snapshot.get("trade_flow_history_source") or "UNAVAILABLE"
    data["liquidation_events"] = stream_snapshot.get("liquidation_events") or []
    data["liquidation_events_source"] = stream_snapshot.get("liquidation_events_source") or "UNAVAILABLE"
    websocket_used = any(
        data.get(key) == "WEBSOCKET"
        for key in ("orderbook_source", "recent_trades_source", "liquidation_events_source")
    )
    rest_used = any(
        data.get(key) == "REST"
        for key in ("orderbook_source", "recent_trades_source")
    )
    if websocket_used and rest_used:
        data["microstructure_source"] = "MIXED_WEBSOCKET_AND_REST"
    elif websocket_used:
        data["microstructure_source"] = "WEBSOCKET"
    elif rest_used:
        data["microstructure_source"] = "REST_FALLBACK"
    else:
        data["microstructure_source"] = "UNAVAILABLE"

    for feed_name, availability, age_ms, reason in (
        ("orderbook", data["orderbook_source"], book_age_ms,
         None if data.get("orderbook") else "NO_ORDERBOOK_SNAPSHOT"),
        ("recent_trades", data["recent_trades_source"], trades_age_ms,
         None if data.get("recent_trades") else "NO_RECENT_TRADES"),
        ("liquidation_events", data["liquidation_events_source"], None,
         None if data["liquidation_events"] else "NO_EXCHANGE_LIQUIDATION_FEED"),
    ):
        record_stage(
            data,
            "DATA_COLLECTION",
            source=availability,
            timestamp_ms=data["snapshot_timestamp_ms"],
            freshness=("FRESH" if (age_ms is not None and age_ms <= 30000) else
                       "STALE" if age_ms is not None else "UNKNOWN"),
            availability=availability,
            reason=reason,
            detail={"feed": feed_name, "age_ms": age_ms},
        )

    # Derivatives context is optional: unsupported endpoints or exchange
    # hiccups must not break OHLCV analysis.
    data["open_interest"] = []
    data["open_interest_timestamps_ms"] = []
    data["open_interest_source"] = "UNAVAILABLE"
    fetch_oi = getattr(exchange, "fetch_open_interest_history", None)
    if callable(fetch_oi):
        try:
            records = fetch_oi(symbol, timeframe="1h", limit=100) or []
            records = sorted(records, key=lambda item: item.get("timestamp") or 0)
            valid_oi = [
                item for item in records
                if isinstance(item, dict)
                and item.get("timestamp") is not None
                and (item.get("openInterestValue") is not None or item.get("openInterestAmount") is not None)
            ]
            data["open_interest"] = [
                float(item.get("openInterestValue") or item.get("openInterestAmount"))
                for item in valid_oi
            ]
            data["open_interest_timestamps_ms"] = [
                int(item["timestamp"]) for item in valid_oi if item.get("timestamp") is not None
            ]
        except Exception:
            data["open_interest"] = []
            data["open_interest_timestamps_ms"] = []
    if data["open_interest"]:
        # Tarihsel OI serisi (zaman damgalı gözlemler) REST'ten geldi.
        data["open_interest_source"] = "REST"
    if not data["open_interest"]:
        fetch_oi_snapshot = getattr(exchange, "fetch_open_interest", None)
        if callable(fetch_oi_snapshot):
            try:
                snapshot = fetch_oi_snapshot(symbol) or {}
                value = snapshot.get("openInterestValue") or snapshot.get("openInterestAmount")
                if value is not None:
                    # Tek anlık snapshot: zaman damgasız. Tarihsel OI serisiyle
                    # ayrı tutulur; OI değişimi bundan hesaplanamaz.
                    data["open_interest"] = [float(value)]
                    data["open_interest_source"] = "REST_SNAPSHOT_ONLY"
            except Exception:
                pass

    data["funding_rate"] = []
    data["funding_rate_source"] = "UNAVAILABLE"
    fetch_funding_history = getattr(exchange, "fetch_funding_rate_history", None)
    if callable(fetch_funding_history):
        try:
            records = fetch_funding_history(symbol, limit=100) or []
            records = sorted(records, key=lambda item: item.get("timestamp") or 0)
            data["funding_rate"] = [
                float(item.get("fundingRate"))
                for item in records
                if isinstance(item, dict) and item.get("fundingRate") is not None
            ]
        except Exception:
            data["funding_rate"] = []
    if data["funding_rate"]:
        data["funding_rate_source"] = "REST"
    if not data["funding_rate"]:
        fetch_funding = getattr(exchange, "fetch_funding_rate", None)
        if callable(fetch_funding):
            try:
                snapshot = fetch_funding(symbol) or {}
                value = snapshot.get("fundingRate")
                if value is not None:
                    data["funding_rate"] = [float(value)]
                    data["funding_rate_source"] = "REST_SNAPSHOT_ONLY"
            except Exception:
                pass
    record_stage(
        data,
        "DATA_COLLECTION",
        source=data["open_interest_source"],
        timestamp_ms=data["snapshot_timestamp_ms"],
        freshness="FRESH" if data["open_interest_timestamps_ms"] else "UNKNOWN",
        availability=("AVAILABLE" if data["open_interest_timestamps_ms"] else
                      "INSUFFICIENT_OI_HISTORY" if data["open_interest"] else "UNAVAILABLE"),
        reason=("NO_TIMESTAMPED_OI_OBSERVATIONS" if data["open_interest"] and not data["open_interest_timestamps_ms"]
                else None if data["open_interest"] else "OI_HISTORY_UNAVAILABLE"),
        detail={"feed": "open_interest", "samples": len(data["open_interest"]),
                "timestamped_samples": min(len(data["open_interest"]), len(data["open_interest_timestamps_ms"]))},
    )
    record_stage(
        data,
        "DATA_COLLECTION",
        source=data["funding_rate_source"],
        timestamp_ms=data["snapshot_timestamp_ms"],
        freshness="FRESH" if data["funding_rate"] else "UNKNOWN",
        availability="AVAILABLE" if data["funding_rate"] else "UNAVAILABLE",
        reason=None if data["funding_rate"] else "FUNDING_RATE_UNAVAILABLE",
        detail={"feed": "funding_rate", "samples": len(data["funding_rate"])},
    )

    for timeframe, c_limit in TIMEFRAMES.items():
        data[timeframe] = fetch_candles(symbol, timeframe, c_limit, force_refresh=force_refresh)

    # DataEngine normalizasyonu: _fetch yalnızca tamamen kapanmış, geçerli ve
    # sıralı mumları tutar; oluşmakta olan mum analiz dışıdır.
    candle_counts = {tf: len(data.get(tf) or []) for tf in TIMEFRAMES}
    last_15m_age_ms = None
    if data.get("15m"):
        try:
            last_15m_age_ms = max(0, int(exchange.milliseconds()) - (int(data["15m"][-1].time) + 15 * 60 * 1000))
        except (AttributeError, TypeError, ValueError, OverflowError):
            last_15m_age_ms = None
    record_stage(
        data,
        "DATA_NORMALIZATION",
        source="BYBIT_PUBLIC_REST",
        timestamp_ms=int(exchange.milliseconds()),
        freshness=("FRESH" if last_15m_age_ms is not None and last_15m_age_ms <= 30 * 60 * 1000
                   else "STALE" if last_15m_age_ms is not None else "UNKNOWN"),
        availability="AVAILABLE" if all(candle_counts.get(tf) for tf in ("1w", "1d", "4h", "15m")) else "UNAVAILABLE",
        reason=None if all(candle_counts.get(tf) for tf in ("1w", "1d", "4h", "15m")) else "INCOMPLETE_OHLCV_TIMEFRAMES",
        detail={"candle_counts": candle_counts, "last_closed_15m_age_ms": last_15m_age_ms},
    )

    data["sector_peer_universe"] = {}
    for peer_symbol in configured_sector_peers(symbol):
        try:
            data["sector_peer_universe"][peer_symbol] = {
                "4h": fetch_candles(peer_symbol, "4h", 200, force_refresh=force_refresh)
            }
        except Exception:
            # Sector peers are optional; BTC/ETH benchmark remains available.
            continue

    # Use a fresh ticker snapshot for MARKET reference entries. If unavailable,
    # the strategy lab explicitly falls back to the last closed 15m close.
    data["current_price"] = None
    data["current_price_timestamp_ms"] = None
    data["current_price_source"] = "LAST_CLOSED_15M_FALLBACK"
    try:
        ticker = exchange.fetch_ticker(symbol) or {}
        ticker_price = float(ticker.get("last"))
        ticker_time = ticker.get("timestamp")
        now_ms = int(exchange.milliseconds())
        fresh = ticker_time is None or 0 <= now_ms - int(ticker_time) <= 60_000
        if math.isfinite(ticker_price) and ticker_price > 0 and fresh:
            data["current_price"] = ticker_price
            data["current_price_timestamp_ms"] = int(ticker_time) if ticker_time is not None else now_ms
            data["current_price_source"] = "BYBIT_TICKER"
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass
    except Exception:
        # Ticker is optional; OHLCV remains the authoritative fallback.
        pass
    if data["current_price"] is None and data.get("15m"):
        data["current_price"] = data["15m"][-1].close
        data["current_price_timestamp_ms"] = int(data["15m"][-1].time) + 15 * 60 * 1000

    # Take the snapshot clock after all optional feeds have been fetched so
    # their exchange timestamps are never incorrectly classified as future.
    data["snapshot_timestamp_ms"] = int(exchange.milliseconds())
    record_stage(
        data,
        "DATA_SOURCE",
        source="BYBIT_PUBLIC_MARKET_DATA",
        timestamp_ms=data["snapshot_timestamp_ms"],
        freshness=("FRESH" if data.get("current_price_source") == "BYBIT_TICKER" else "UNKNOWN"),
        availability=("AVAILABLE" if bool(data.get("15m")) else "UNAVAILABLE"),
        reason=None if bool(data.get("15m")) else "NO_OHLCV_CANDLES",
        detail={
            "current_price_source": data.get("current_price_source"),
            "microstructure_source": data.get("microstructure_source"),
        },
    )
    if os.getenv("ATLAS_MICROSTRUCTURE_ARCHIVE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from microstructure_archive import record_snapshot
            record_snapshot(symbol, data)
        except Exception:
            # Archiving is optional and must never interrupt market analysis.
            pass
    return data


# Cross-market evidence universe: BTC/ETH 4H candles. Dominance indexes are
# not fetched from this Bybit data provider and must not be fabricated.
_CORRELATION_SYMBOLS = {
    "BTC": ("BTC/USDT:USDT", "4h", 200),
    "ETH": ("ETH/USDT:USDT", "4h", 200),
}


def get_correlation_universe(force_refresh=False, candle_factory=None):
    """BTC/ETH 4h mumlarini toplar; scan boyunca cache toplar (bir kez cekilir)."""
    from core.candle import Candle
    universe = {}
    for key, (symbol, timeframe, limit) in _CORRELATION_SYMBOLS.items():
        try:
            candles = fetch_candles(symbol, timeframe, limit, force_refresh=force_refresh)
            universe[key] = candles
        except Exception:
            universe[key] = []
    return universe

# SMT comparison data is shared across a scan and cached per timeframe.
# 15m data gets a short TTL so scanning many symbols does not refetch BTC/ETH
# for every altcoin; higher timeframes use progressively longer TTLs.
_SMT_SYMBOLS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
_SMT_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_SMT_CACHE_TTL_SECONDS = {"15m": 45, "1h": 300, "4h": 900, "1d": 3600}
_smt_cache = {}


def get_smt_universe(force_refresh=False):
    """Return cached BTC/ETH OHLCV comparison data for SMT on all supported TFs."""
    now = time.time()
    universe = {}
    for symbol in _SMT_SYMBOLS:
        frames = {}
        for timeframe in _SMT_TIMEFRAMES:
            key = (symbol, timeframe)
            cached = _smt_cache.get(key)
            ttl = _SMT_CACHE_TTL_SECONDS[timeframe]
            if (
                not force_refresh
                and cached is not None
                and now - cached[1] <= ttl
            ):
                frames[timeframe] = cached[0]
                continue
            try:
                candles = fetch_candles(symbol, timeframe, TIMEFRAMES[timeframe], force_refresh=force_refresh)
                _smt_cache[key] = (candles, now)
                frames[timeframe] = candles
            except Exception:
                # A temporary exchange failure should not erase a previously
                # fetched comparison series; the SMT engine can still use it.
                frames[timeframe] = cached[0] if cached is not None else []
        universe[symbol] = frames
    return universe
