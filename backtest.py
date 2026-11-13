"""
backtest.py
Atlas için gerçek piyasa verisiyle sinyal backtesti.

Kullanım:
    python3 backtest.py --symbol BTC/USDT:USDT --days 60
    python3 backtest.py --symbol ETH/USDT:USDT --days 30 --timeframe 15m

Gerçek OHLCV geçmişini çeker, engine.analyze()'u ileri sardırarak sinyal üretir,
her sinyali SL/TP vuruşuyla simüle eder ve expectancy/winrate/profit factor raporlar.
"""

import argparse
import json
import logging
import math
import os
import subprocess
import sys
import time

import ccxt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")

from data_engine import exchange, TIMEFRAMES
from core.candle import Candle
from backtest_runner import BacktestRunner
from engine import AtlasEngine
from config import Config


TIMEFRAME_DURATION_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}
BACKTEST_WARMUP_CANDLES = {
    "15m": 300,
    "1h": 1000,
    "4h": 1000,
    "1d": 500,
    "1w": 300,
}

# Yerel OHLCV cache'i: her backtestte aynı tarihi baştan indirmek yerine
# indirilen mumları diske yazar. Cache sadece okunur kaynak; sahte veri üretilmez.
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".backtest_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(symbol, timeframe):
    safe = symbol.replace("/", "_").replace(":", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{timeframe}.json")


def _load_cached_candles(symbol, timeframe, since_ms, now_ms):
    """Cache'den sadece [since_ms, now_ms) penceresi içinde kalan mumları döndür."""
    path = _cache_path(symbol, timeframe)
    if not os.path.exists(path):
        return None
    duration_ms = TIMEFRAME_DURATION_MS.get(timeframe)
    if duration_ms is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        rows = payload.get("rows") or []
        candles = []
        for r in rows:
            try:
                c = Candle(
                    time=int(r[0]),
                    open=float(r[1]),
                    high=float(r[2]),
                    low=float(r[3]),
                    close=float(r[4]),
                    volume=float(r[5]),
                )
            except (TypeError, ValueError, OverflowError):
                continue
            if since_ms <= c.time and c.time + duration_ms <= now_ms:
                candles.append(c)
        candles.sort(key=lambda c: c.time)
        seen = set()
        deduped = []
        for c in candles:
            if c.time in seen:
                continue
            seen.add(c.time)
            deduped.append(c)
        return deduped
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _save_cached_candles(symbol, timeframe, candles):
    """Tüm indirilmiş mumları cache dosyasına yazar (overwrite)."""
    path = _cache_path(symbol, timeframe)
    try:
        rows = [[c.time, c.open, c.high, c.low, c.close, c.volume] for c in candles]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rows": rows}, f)
    except OSError as exc:
        logging.warning("Cache yazımı başarısız | %s %s: %s", symbol, timeframe, exc)


def _market_listing_time_ms(symbol):
    """Return the exchange-reported listing timestamp for a swap market."""
    try:
        markets = exchange.load_markets()
    except Exception as exc:
        raise RuntimeError(
            f"{symbol}: Bybit market metadata yüklenemedi: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    market = markets.get(symbol) if isinstance(markets, dict) else None
    if not market:
        return None

    info = market.get("info") or {}
    raw_timestamp = (
        info.get("launchTime")
        or info.get("launch_time")
        or market.get("listing")
    )
    if raw_timestamp in (None, ""):
        return None
    try:
        timestamp = int(float(raw_timestamp))
    except (TypeError, ValueError, OverflowError):
        logging.warning("%s için geçersiz listing timestamp: %r", symbol, raw_timestamp)
        return None

    # Normalize second-based timestamps while preserving Bybit's millisecond values.
    if timestamp < 10_000_000_000:
        timestamp *= 1000
    return timestamp


def _history_days_for_timeframe(days, timeframe):
    """Fetch enough prehistory for each timeframe's structure warmup."""
    days = float(days)
    if not days > 0:
        raise ValueError("Backtest days must be greater than zero")
    if timeframe not in TIMEFRAME_DURATION_MS:
        raise ValueError(f"Unsupported backtest timeframe: {timeframe}")
    # Request two extra closed-candle slots so the currently-forming weekly
    # candle can be discarded without leaving the 300-candle warmup short.
    warmup_candles = BACKTEST_WARMUP_CANDLES[timeframe]
    if timeframe == "1w":
        warmup_candles += 2
    warmup_days = (
        warmup_candles
        * TIMEFRAME_DURATION_MS[timeframe]
        / 86_400_000
    )
    # Every timeframe needs its warmup BEFORE the requested evaluation
    # window. The 15m warmup controls the runner start; HTF warmups must also
    # precede that same historical start so MTF context matches live analysis.
    return days + warmup_days


def _disable_backtest_live_features():
    """Disable all live-only side effects through the environment config source."""
    disabled = (
        "ATLAS_STATE_ENGINE_ENABLED",
        "ATLAS_INCREMENTAL_ANALYSIS_ENABLED",
        "ATLAS_TELEGRAM_ENABLED",
        "ATLAS_CORRELATION_ENGINE_ENABLED",
        "ATLAS_ECONOMIC_NEWS_FILTER_ENABLED",
        "ATLAS_LEARNING_ENGINE_ENABLED",
        "ATLAS_SIGNAL_TRACKING_ENABLED",
    )
    for name in disabled:
        os.environ[name] = "0"
    os.environ["ATLAS_TRADE_COOLDOWN_MINUTES"] = "0"
    os.environ["ATLAS_AUTO_TRADING_ENABLED"] = "0"
    Config.refresh_from_env()

    # Several legacy flags are read at Config import time and are not refreshed
    # by refresh_from_env(); pin them after refresh as well.
    Config.STATE_ENGINE_ENABLED = False
    Config.INCREMENTAL_ANALYSIS_ENABLED = False
    Config.TELEGRAM_ENABLED = False
    Config.CORRELATION_ENGINE_ENABLED = False
    Config.ECONOMIC_NEWS_FILTER_ENABLED = False
    Config.LEARNING_ENGINE_ENABLED = False
    Config.SIGNAL_TRACKING_ENABLED = False
    Config.TRADE_COOLDOWN_MINUTES = 0.0


_history_fallback_exchange = None
_history_provider_name = "Bybit"


def _create_history_fallback_exchange():
    """Binance USD-M public futures OHLCV fallback for regions blocking Bybit."""
    return ccxt.binanceusdm({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })


def _is_geoblock_error(exc):
    message = str(exc).lower()
    return "403" in message or "cloudfront" in message or "configured to block" in message


def _fetch_history_batch(symbol, timeframe, cursor, limit):
    global _history_fallback_exchange, _history_provider_name
    if _history_fallback_exchange is not None:
        batch = _history_fallback_exchange.fetch_ohlcv(
            symbol, timeframe, since=cursor, limit=limit
        )
        _history_provider_name = "Binance USD-M Futures (Bybit 403 fallback)"
        return batch
    try:
        return exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=limit)
    except Exception as exc:
        if not _is_geoblock_error(exc):
            raise
        logging.warning(
            "Bybit 403 engeli; tarihsel OHLCV için Binance USD-M Futures deneniyor."
        )
        _history_fallback_exchange = _create_history_fallback_exchange()
        try:
            batch = _history_fallback_exchange.fetch_ohlcv(
                symbol, timeframe, since=cursor, limit=limit
            )
        except Exception as fallback_exc:
            _history_fallback_exchange = None
            raise RuntimeError(
                f"Bybit 403 verdi; Binance USD-M yedeği de başarısız: "
                f"{type(fallback_exc).__name__}: {fallback_exc}"
            ) from fallback_exc
        _history_provider_name = "Binance USD-M Futures (Bybit 403 fallback)"
        return batch


def _fetch_history(symbol, timeframe, since_ms, limit=1000):
    candles = []
    cursor = since_ms
    attempts = 0
    last_error = None
    while True:
        try:
            batch = _fetch_history_batch(symbol, timeframe, cursor, limit)
        except Exception as exc:
            last_error = exc
            attempts += 1
            if attempts > 3:
                raise RuntimeError(
                    f"Tarihsel OHLCV alınamadı: {symbol} {timeframe}; "
                    f"4 deneme başarısız. Sağlayıcı={_history_provider_name}. "
                    f"Son hata: {type(last_error).__name__}: {last_error}"
                ) from last_error
            time.sleep(0.5 * attempts)
            continue
        attempts = 0
        last_error = None
        if not batch:
            break
        candles.extend(
            Candle(time=c[0], open=c[1], high=c[2], low=c[3], close=c[4], volume=c[5]) for c in batch
        )
        last_time = batch[-1][0]
        if last_time <= cursor or len(batch) < limit:
            break
        cursor = last_time + 1
        time.sleep(0.05)
    seen = set()
    ordered = []
    for candle in sorted(candles, key=lambda c: c.time):
        if candle.time in seen:
            continue
        seen.add(candle.time)
        ordered.append(candle)
    return ordered

def load_historical(symbol, days=60, now_ms=None, listing_time_ms=None,
                    use_cache=True):
    """Load evaluation history, clamped to the market's actual listing date.

    Gerçek Bybit OHLCV verisi CCXT üzerinden indirilir ve yerel cache'e
    kaydedilir. Aynı tarih aralığındaki sonraki backtest
    cache'den okunur; baştan indirilmez. Sahte veya rastgele veri üretilmez.
    ``use_cache=False`` testi ve izole ortamlar için cache'i atlar.
    """
    if float(days) <= 0:
        raise ValueError("Backtest days must be greater than zero")
    now = time.time() * 1000 if now_ms is None else float(now_ms)
    data = {"symbol": symbol}
    for tf, limit in TIMEFRAMES.items():
        history_days = _history_days_for_timeframe(days, tf)
        requested_since = now - int(history_days * 86_400_000)
        since = max(requested_since, listing_time_ms) if listing_time_ms else requested_since
        duration_ms = TIMEFRAME_DURATION_MS[tf]

        if use_cache:
            cached = _load_cached_candles(symbol, tf, since, now)
            if cached is not None:
                data[tf] = cached
                logging.info(
                    "%s %s -> %s candles (cache) (history %.1f days)",
                    symbol,
                    tf,
                    len(cached),
                    history_days,
                )
                continue

        fetch_limit = limit + 2 if tf == "1w" else limit
        candles = _fetch_history(
            symbol, tf, since_ms=since, limit=fetch_limit
        )
        # Bybit includes the currently-forming candle in OHLCV responses.
        # A historical decision may only use candles that were fully closed
        # at the backtest's fixed as-of timestamp.
        candles = [candle for candle in candles if candle.time + duration_ms <= now]
        if use_cache:
            _save_cached_candles(symbol, tf, candles)
        data[tf] = candles
        logging.info(
            "%s %s -> %s candles (fetched) (history %.1f days)",
            symbol,
            tf,
            len(candles),
            history_days,
        )
    return data


_SMT_HISTORY_CACHE = {}


def _load_smt_comparison_history(symbol, timeframe, days, now_ms):
    """Load cached historical comparison candles for a single SMT timeframe."""
    history_days = _history_days_for_timeframe(days, timeframe)
    since_ms = int(float(now_ms) - history_days * 86_400_000)
    cache_key = (symbol, timeframe, since_ms, int(float(now_ms) // 60_000))
    if cache_key in _SMT_HISTORY_CACHE:
        return _SMT_HISTORY_CACHE[cache_key]
    try:
        candles = _fetch_history(
            symbol, timeframe, since_ms=since_ms, limit=TIMEFRAMES[timeframe]
        )
        duration = TIMEFRAME_DURATION_MS[timeframe]
        candles = [item for item in candles if item.time + duration <= now_ms]
    except Exception as exc:
        logging.warning("SMT historical comparison unavailable | %s %s: %s", symbol, timeframe, exc)
        candles = []
    _SMT_HISTORY_CACHE[cache_key] = candles
    return candles


def attach_historical_smt_universe(data, days, now_ms):
    """Attach BTC/ETH comparison series aligned by timestamp for replay."""
    primary_symbol = data.get("symbol")
    universe = {}
    for comparison_symbol in ("BTC/USDT:USDT", "ETH/USDT:USDT"):
        frames = {}
        for timeframe in ("15m", "1h", "4h", "1d"):
            if comparison_symbol == primary_symbol:
                frames[timeframe] = data.get(timeframe) or []
            else:
                frames[timeframe] = _load_smt_comparison_history(
                    comparison_symbol, timeframe, days, now_ms
                )
        universe[comparison_symbol] = frames
    data["smt_universe"] = universe
    return data

def _validate_backtest_history(data, symbol):
    """Fail loudly instead of reporting a successful zero-call backtest."""
    counts = {
        tf: len(data.get(tf) or [])
        for tf in ("15m", "1h", "4h", "1d", "1w")
    }
    print(
        "VERİ DURUMU | "
        + " | ".join(f"{tf}: {count} mum" for tf, count in counts.items())
    )
    minimum = BACKTEST_WARMUP_CANDLES["15m"] + 1
    if counts["15m"] < minimum:
        raise RuntimeError(
            f"{symbol}: 15m geçmişi yetersiz ({counts['15m']} mum; "
            f"en az {minimum} gerekli). Backtest başlatılmadı. "
            "Bybit OHLCV erişimini ve tarihsel veri sınırını kontrol edin."
        )
    return counts


def _validate_backtest_coverage(data, symbol, days, now_ms, listing_time_ms=None):
    """Validate coverage, allowing only listing-date-limited warmup reductions."""
    now = float(now_ms)
    coverage = {}
    for tf in ("15m", "1h", "4h", "1d", "1w"):
        candles = data.get(tf) or []
        duration = TIMEFRAME_DURATION_MS[tf]
        history_days = _history_days_for_timeframe(days, tf)
        requested_start = now - history_days * 86_400_000
        effective_start = max(requested_start, listing_time_ms) if listing_time_ms else requested_start
        if not candles:
            raise RuntimeError(f"{symbol} {tf}: tarihsel veri yok; backtest durduruldu.")

        first_open = min(c.time for c in candles)
        last_close = max(c.time + duration for c in candles)
        # Candle boundaries are timeframe-aligned. Exchange provider may not
        # cover the full requested history (e.g. Bybit 15m is limited to the
        # most recent ~1000 candles). Use whatever real data is available
        # instead of fabricating history; the warmup floor is enforced
        # separately in _validate_backtest_history.
        if first_open > effective_start + 2 * duration:
            logging.warning(
                "%s %s: istenen baslangic (%s) ile mevcut ilk mum (%s) arasinda "
                "aralik var; mevcut gerçek veriyle devam ediliyor.",
                symbol, tf, time.strftime("%Y-%m-%d %H:%M", time.gmtime(effective_start / 1000)),
                time.strftime("%Y-%m-%d %H:%M", time.gmtime(first_open / 1000)),
            )
        if last_close < now - 2 * duration:
            stale_days = (now - last_close) / 86_400_000
            raise RuntimeError(
                f"{symbol} {tf}: son mum eski ({stale_days:.1f} gün geride); "
                "backtest durduruldu."
            )
        ordered_times = sorted(c.time for c in candles)
        if any(
            current - previous > 2 * duration
            for previous, current in zip(ordered_times, ordered_times[1:])
        ):
            raise RuntimeError(
                f"{symbol} {tf}: mumlar arasında 2 zaman diliminden büyük veri boşluğu var; "
                "backtest durduruldu."
            )
        minimum = BACKTEST_WARMUP_CANDLES[tf]
        if listing_time_ms is not None and listing_time_ms > requested_start:
            # Keep the normal warmup requirement (300 weekly candles, etc.)
            # whenever the market has existed long enough. Reduce it only by
            # the amount that is mathematically unavailable before listing.
            available_since_listing = max(0, int((now - effective_start) // duration))
            minimum = min(minimum, max(1, available_since_listing - 2))
        if len(candles) < minimum:
            raise RuntimeError(
                f"{symbol} {tf}: warmup verisi yetersiz ({len(candles)} mum; "
                f"en az {minimum} gerekli)."
            )
        coverage[tf] = {
            "first": first_open,
            "last_close": last_close,
            "count": len(candles),
            "requested_days": round(history_days, 1),
            "warmup_required": minimum,
            "warmup_reduced": minimum < BACKTEST_WARMUP_CANDLES[tf],
        }
    print("TARİH KAPSAMI | " + " | ".join(
        f"{tf}: {item['requested_days']}g / {item['count']} mum"
        for tf, item in coverage.items()
    ))
    reduced = [
        f"{tf}: {item['count']} mum (normal warmup {BACKTEST_WARMUP_CANDLES[tf]})"
        for tf, item in coverage.items()
        if item["warmup_reduced"]
    ]
    if reduced:
        print("WARMUP UYARISI | Piyasa listelenme tarihi nedeniyle azaltıldı | " + " | ".join(reduced))
    return coverage


def build_analyze_fn(engine):
    def analyze(window):
        try:
            return engine.analyze(window)
        except Exception as exc:  # tek bir sinyal hatası taramayı durdurmasın
            logging.debug("analyze error: %s", exc)
            return None
    return analyze


def _metrics_for_trades(trades):
    gross = [float(item.get("gross_rr", item.get("net_rr", 0.0)) or 0.0) for item in trades]
    net = [float(item.get("net_rr", 0.0) or 0.0) for item in trades]
    def pf(values):
        profit = sum(value for value in values if value > 0)
        loss = abs(sum(value for value in values if value < 0))
        return round(profit / loss, 4) if loss else round(profit, 4)
    count = len(trades)
    wins = sum(1 for value in net if value > 0)
    losses = sum(1 for value in net if value < 0)
    return {
        "total": count,
        "wins": wins,
        "losses": losses,
        "winrate": round(wins / count * 100.0, 2) if count else 0.0,
        "gross_rr": round(sum(gross), 4),
        "gross_expectancy": round(sum(gross) / count, 4) if count else 0.0,
        "gross_profit_factor": pf(gross),
        "net_rr": round(sum(net), 4),
        "expectancy": round(sum(net) / count, 4) if count else 0.0,
        "profit_factor": pf(net),
        "execution_cost_rr": round(sum(float(item.get("execution_cost_rr", 0.0) or 0.0) for item in trades), 4),
    }


def _combine_stats(all_stats):
    """Aggregate realized trade metrics from gross R, not net symbol totals."""
    combined = {
        "total": 0,
        "wins": 0,
        "losses": 0,
        "winrate": 0,
        "expectancy": 0,
        "profit_factor": 0,
        "net_rr": 0,
        "gross_profit_rr": 0,
        "gross_loss_rr": 0,
        "gross_rr": 0,
        "gross_expectancy": 0,
        "gross_profit_factor": 0,
        "total_execution_cost_rr": 0,
        "candidate_signals": 0,
        "analysis_calls": 0,
        "empty_results": 0,
        "raw_long_signals": 0,
        "raw_short_signals": 0,
        "non_directional_results": 0,
        "action_counts": {},
        "wait_reason_counts": {},
        "signal_reason_counts": {},
        "mtf_alignment_counts": {},
        "entry_reason_counts": {},
        "entry_type_counts": {},
        "risk_reason_counts": {},
        "target_reason_counts": {},
        "target_missing_rr_counts": {},
        "stop_atr_buckets": {},
        "confirmation_outcome_counts": {},
        "confirmation_reason_counts": {},
        "confirmation_requirement_counts": {},
        "entry_type_reason_counts": {},
        "unfilled_limits": 0,
        "expired_limits": 0,
        "stale_limits_cancelled": 0,
        "stale_limit_signal_candle_target": 0,
        "stale_limit_target_before_fill": 0,
        "stale_limit_targets_rebased": 0,
        "stale_limit_target_rebase_rejected": 0,
        "duplicate_setups_skipped": 0,
        "market_fallback_fills": 0,
        "market_fallback_rejected_rr": 0,
        "market_fallback_rejected_distance": 0,
        "candidate_direction_counts": {},
        "filled_direction_counts": {},
        "unfilled_limit_direction_counts": {},
        "expired_limit_direction_counts": {},
        "stale_limit_direction_counts": {},
        "overlapping_signals_skipped": 0,
        "open_trades": 0,
        "invalid_candidates": 0,
        "no_followup_data": 0,
        "tp1": 0,
        "tp2": 0,
        "tp3": 0,
        "trade_history": [],
    }
    for _, stats in all_stats:
        for key in (
            "total", "wins", "tp1", "tp2", "tp3",
            "candidate_signals", "analysis_calls", "empty_results",
            "raw_long_signals", "raw_short_signals", "non_directional_results",
            "unfilled_limits", "expired_limits", "stale_limits_cancelled",
            "stale_limit_signal_candle_target", "stale_limit_target_before_fill",
            "stale_limit_targets_rebased", "stale_limit_target_rebase_rejected",
            "duplicate_setups_skipped",
            "market_fallback_fills", "market_fallback_rejected_rr",
            "market_fallback_rejected_distance",
            "overlapping_signals_skipped", "open_trades",
            "invalid_candidates", "no_followup_data",
        ):
            combined[key] += int(stats.get(key, 0) or 0)
        for key in (
            "action_counts", "wait_reason_counts", "signal_reason_counts", "mtf_alignment_counts",
            "entry_reason_counts", "entry_type_counts", "risk_reason_counts", "target_reason_counts",
            "target_missing_rr_counts", "stop_atr_buckets", "confirmation_outcome_counts",
            "confirmation_reason_counts", "confirmation_requirement_counts", "entry_type_reason_counts",
            "candidate_direction_counts", "filled_direction_counts", "unfilled_limit_direction_counts",
            "expired_limit_direction_counts", "stale_limit_direction_counts",
        ):
            for label, count in (stats.get(key) or {}).items():
                combined[key][label] = combined[key].get(label, 0) + int(count or 0)
        combined["net_rr"] += float(stats.get("net_rr", 0) or 0)
        combined["gross_profit_rr"] += float(stats.get("gross_profit_rr", 0) or 0)
        combined["gross_loss_rr"] += float(stats.get("gross_loss_rr", 0) or 0)
        combined["gross_rr"] += float(stats.get("gross_rr", 0) or 0)
        combined["total_execution_cost_rr"] += float(stats.get("total_execution_cost_rr", 0) or 0)
        combined["trade_history"].extend(stats.get("trade_history") or [])

    # Rebuild combined direction and MTF outcome groups from the actual closed
    # trades; summing per-symbol percentages would distort the pooled sample.
    combined["direction_breakdown"] = {}
    combined["mtf_trade_breakdown"] = {}
    grouped = {}
    for trade in combined["trade_history"]:
        context = trade.get("mtf_context") or {}
        direction = str(trade.get("direction") or "UNKNOWN").upper()
        side_key = direction
        mtf_key = (
            f"{direction}|weekly={str(context.get('weekly') or 'UNKNOWN').upper()}"
            f"|daily={str(context.get('daily') or 'UNKNOWN').upper()}"
            f"|h4={str(context.get('h4') or 'UNKNOWN').upper()}"
        )
        grouped.setdefault(side_key, []).append(trade)
        combined["mtf_trade_breakdown"].setdefault(mtf_key, []).append(trade)

    for key, trades in grouped.items():
        combined["direction_breakdown"][key] = _metrics_for_trades(trades)
    for key, trades in list(combined["mtf_trade_breakdown"].items()):
        combined["mtf_trade_breakdown"][key] = _metrics_for_trades(trades)

    segment_dimensions = {
        "entry_type": lambda trade: trade.get("entry_type"),
        "market_phase": lambda trade: trade.get("market_phase"),
        "market_regime": lambda trade: trade.get("market_regime"),
        "volatility": lambda trade: trade.get("volatility"),
        "poi_type": lambda trade: trade.get("poi_type"),
        "tp_behavior": lambda trade: (
            "TP3" if 3 in (trade.get("_levels") or [])
            else "TP2" if 2 in (trade.get("_levels") or [])
            else "TP1_THEN_STOP" if 1 in (trade.get("_levels") or []) and "STOP" in str(trade.get("exit_reason", "")).upper()
            else "TP1_THEN_EXIT" if 1 in (trade.get("_levels") or [])
            else "STOP_BEFORE_TP1" if "STOP" in str(trade.get("exit_reason", "")).upper()
            else str(trade.get("exit_reason") or "UNKNOWN").upper()
        ),
    }
    combined["segment_breakdown"] = {}
    for dimension, getter in segment_dimensions.items():
        groups = {}
        for trade in combined["trade_history"]:
            label = str(getter(trade) or "UNKNOWN").upper()
            groups.setdefault(label, []).append(trade)
        combined["segment_breakdown"][dimension] = {
            label: _metrics_for_trades(trades)
            for label, trades in sorted(groups.items())
        }

    combined["losses"] = combined["total"] - combined["wins"]
    if combined["total"]:
        combined["winrate"] = round(combined["wins"] / combined["total"] * 100, 2)
        combined["expectancy"] = round(combined["net_rr"] / combined["total"], 4)
        combined["gross_expectancy"] = round(combined["gross_rr"] / combined["total"], 4)
    if combined["trade_history"]:
        combined["gross_profit_rr"] = round(sum(
            max(0.0, float(x.get("gross_rr", x.get("net_rr", 0.0)) or 0.0))
            for x in combined["trade_history"]
        ), 4)
        combined["gross_loss_rr"] = round(abs(sum(
            min(0.0, float(x.get("gross_rr", x.get("net_rr", 0.0)) or 0.0))
            for x in combined["trade_history"]
        )), 4)
        trade_metrics = _metrics_for_trades(combined["trade_history"])
        combined["gross_profit_factor"] = trade_metrics["gross_profit_factor"]
        combined["profit_factor"] = trade_metrics["profit_factor"]
    else:
        # Compatibility for callers/tests that provide aggregated per-symbol
        # statistics without the underlying trade ledger.
        combined["gross_rr"] = round(
            combined["gross_profit_rr"] - combined["gross_loss_rr"], 4
        )
        if combined["total"]:
            combined["gross_expectancy"] = round(
                combined["gross_rr"] / combined["total"], 4
            )
        combined["gross_profit_factor"] = (
            round(combined["gross_profit_rr"] / combined["gross_loss_rr"], 4)
            if combined["gross_loss_rr"] > 0 else 0.0
        )
        combined["profit_factor"] = combined["gross_profit_factor"]
    return combined


def _report(stats, name):
    print("=" * 52)
    print(f"SONUÇ | {name}")
    print(f"  Maliyet varsayımları: maker={getattr(Config, 'MAKER_FEE_RATE', 0.0002):.4%}/leg | "
          f"taker={getattr(Config, 'TAKER_FEE_RATE', 0.00055):.4%}/leg | "
          f"spread={getattr(Config, 'STOP_SPREAD_BUFFER_RATE', 0.0002):.4%}/market leg | "
          f"slippage={getattr(Config, 'STOP_SLIPPAGE_BUFFER_RATE', 0.0003):.4%}/market leg")
    print("=" * 52)
    print(f"  Analiz çağrısı : {stats.get('analysis_calls', 0)}")
    print(f"  Boş sonuç      : {stats.get('empty_results', 0)}")
    print(f"  Ham LONG/SHORT : {stats.get('raw_long_signals', 0)}/{stats.get('raw_short_signals', 0)}")
    print(f"  Yönsüz sonuç   : {stats.get('non_directional_results', 0)}")
    print(f"  Karar aksiyonları: {stats.get('action_counts', {})}")
    if stats.get("wait_reason_counts"):
        print(f"  WAIT nedenleri : {stats['wait_reason_counts']}")
    if stats.get("signal_reason_counts"):
        print(f"  Sinyal nedenleri: {stats['signal_reason_counts']}")
    if stats.get("mtf_alignment_counts"):
        print(f"  MTF yönleri    : {stats['mtf_alignment_counts']}")
    if stats.get("entry_reason_counts"):
        print(f"  Entry nedenleri: {stats['entry_reason_counts']}")
    if stats.get("entry_type_counts"):
        print(f"  Emir türleri   : {stats['entry_type_counts']}")
    if stats.get("risk_reason_counts"):
        print(f"  Stop nedenleri : {stats['risk_reason_counts']}")
    if stats.get("target_reason_counts"):
        print(f"  TP nedenleri   : {stats['target_reason_counts']}")
    if stats.get("target_missing_rr_counts"):
        print(f"  Eksik TP RR    : {stats['target_missing_rr_counts']}")
    if stats.get("stop_atr_buckets"):
        print(f"  Stop / ATR     : {stats['stop_atr_buckets']}")
    if stats.get("mtf_entry_source_counts"):
        print(f"  MTF kaynakları : {stats['mtf_entry_source_counts']}")
    if stats.get("liquidity_sweep_state_counts"):
        print(f"  Sweep durumu   : {stats['liquidity_sweep_state_counts']}")
    print(f"  Onay sonucu    : {stats.get('confirmation_outcome_counts', {})}")
    print(f"  Onay nedenleri : {stats.get('confirmation_reason_counts', {})}")
    print(f"  Onay şart profili: {stats.get('confirmation_requirement_counts', {})}")
    print(f"  Entry tür nedeni: {stats.get('entry_type_reason_counts', {})}")
    if stats.get("entry_validity_counts"):
        print(f"  Entry geçerliliği: {stats['entry_validity_counts']}")
    if stats.get("decision_blocker_counts"):
        print(f"  Karar engelleri: {stats['decision_blocker_counts']}")
    print(f"  Aday sinyal    : {stats.get('candidate_signals', 0)}")
    print(f"  Kapanan işlem  : {stats['total']}")
    print(f"  Açık işlem     : {stats.get('open_trades', 0)}")
    print(f"  Dolmayan LIMIT : {stats.get('unfilled_limits', 0)}")
    print(f"  Süresi dolan LIMIT: {stats.get('expired_limits', 0)}")
    print(f"  Hedefe geç kalan LIMIT iptali: {stats.get('stale_limits_cancelled', 0)}")
    print(f"  Hedef sonrası kalan TP'ye göre güncellenen LIMIT: {stats.get('stale_limit_targets_rebased', 0)}")
    print(f"  Maliyet/RR nedeniyle güncellenemeyen LIMIT: {stats.get('stale_limit_target_rebase_rejected', 0)}")
    print(f"  Aynı setup tekrarları atlandı: {stats.get('duplicate_setups_skipped', 0)}")
    print(f"  Aday yönleri   : {stats.get('candidate_direction_counts', {})}")
    print(f"  Dolan yönler   : {stats.get('filled_direction_counts', {})}")
    direction_fill_rates = stats.get("direction_fill_rates")
    if not isinstance(direction_fill_rates, dict):
        candidates_by_side = stats.get("candidate_direction_counts", {})
        fills_by_side = stats.get("filled_direction_counts", {})
        direction_fill_rates = {
            side: round(
                fills_by_side.get(side, 0) / max(1, candidates_by_side.get(side, 0)) * 100.0, 2
            ) for side in ("LONG", "SHORT")
        }
    print(f"  Yön bazlı dolum oranı: {direction_fill_rates}")
    print(f"  Dolmayan yönler: {stats.get('unfilled_limit_direction_counts', {})}")
    print(f"  Süresi dolan yönler: {stats.get('expired_limit_direction_counts', {})}")
    print(f"  Hedef öncesi iptal yönleri: {stats.get('stale_limit_direction_counts', {})}")
    print(f"  Market fallback reddi (RR/mesafe): {stats.get('market_fallback_rejected_rr', 0)}/{stats.get('market_fallback_rejected_distance', 0)}")
    print(f"    - Sinyal mumu hedefi önceden gördü: {stats.get('stale_limit_signal_candle_target', 0)}")
    print(f"    - Dolumdan önce sonraki mum hedefi gördü: {stats.get('stale_limit_target_before_fill', 0)}")
    print(f"  Geçersiz aday  : {stats.get('invalid_candidates', 0)}")
    print(f"  Takipsiz son mum: {stats.get('no_followup_data', 0)}")
    if not stats["total"]:
        print("  SONUÇ: Kapanmış işlem yok; kârlılık ölçülemez.")
        print("=" * 52)
        return
    print(f"  Kazanç (WIN)   : {stats['wins']}")
    print(f"  Kayıp (LOSS)   : {stats['losses']}")
    print(f"  Winrate        : %{stats['winrate']}")
    print(f"  TP1/2/3        : {stats['tp1']}/{stats['tp2']}/{stats['tp3']}")
    print(f"  BRÜT sonuç     : {stats.get('gross_rr', 0)}R | beklenti {stats.get('gross_expectancy', 0)}R/işlem | PF {stats.get('gross_profit_factor', 0)}")
    print(f"  MALİYET        : -{stats.get('total_execution_cost_rr', 0)}R")
    print(f"  NET sonuç      : {stats['net_rr']}R | beklenti {stats['expectancy']}R/işlem | PF {stats['profit_factor']}")
    if "max_drawdown" in stats:
        print(f"  Max Drawdown   : {stats['max_drawdown']} R")
    mtf_breakdown = stats.get("mtf_trade_breakdown") or {}
    if mtf_breakdown:
        print(f"  Kapanan işlem MTF dağılımı: {mtf_breakdown}")
    segment_breakdown = stats.get("segment_breakdown") or {}
    for dimension in ("entry_type", "market_phase", "market_regime", "volatility", "poi_type", "tp_behavior"):
        values = segment_breakdown.get(dimension) or {}
        if values:
            print(f"  Segment {dimension}: {values}")
    breakdown = stats.get("direction_breakdown") or {}
    for direction in ("LONG", "SHORT"):
        side = breakdown.get(direction)
        if side and side.get("total", 0):
            print(
                f"  {direction:<5}          : {side.get('total', 0)} işlem | "
                f"Win %{side.get('winrate', 0)} | "
                f"Beklenti {side.get('expectancy', 0)} R | "
                f"PF {side.get('profit_factor', 0)}"
            )

    print("  İŞLEM DEFTERİ | yön, emir, sinyal zamanı, dolum gecikmesi, planlanan/gerçekleşen giriş, SL, TP'ler, sonuç, net R")
    for trade_no, trade in enumerate(stats.get("trade_history", []), 1):
        tps = "/".join("-" if value is None else f"{value:g}" for value in trade.get("tps", []))
        print(
            f"    #{trade_no} {trade.get('direction')} {trade.get('entry_type')} | "
            f"signal={trade.get('signal_time')} fill={trade.get('entry_time')} "
            f"delay={trade.get('fill_delay_bars')} bar | "
            f"plan={trade.get('planned_entry')} fill={trade.get('entry')} "
            f"SL={trade.get('stop_loss')} TP={tps} | "
            f"exit={trade.get('exit_price')} "
            f"{'STOP_GAP=' + str(trade.get('stop_gap_r')) + 'R ' if trade.get('stop_gap') else ''}"
            f"{trade.get('exit_reason')} gross={trade.get('gross_rr', 'n/a')}R "
            f"cost=-{trade.get('execution_cost_rr', 0)}R "
            f"net={trade.get('net_rr')}R | "
            f"MTF={trade.get('mtf_context')}"
        )

    if stats["total"] >= 20 and stats["expectancy"] > 0 and stats["profit_factor"] >= 1.3:
        print("  YORUM: Edge pozitif görünüyor; daha uzun örnekle doğrulanmalı.")
    elif stats["total"] >= 20:
        print("  YORUM: Edge net değil. Sinyal filtresi maliyetleri karşılamıyor.")
    elif stats["total"] >= 5:
        print(f"  YORUM: {stats['total']} sinyal az ama güvenilir örnek değil; daha uzun süre koş.")
    else:
        print(f"  YORUM: {stats['total']} sinyal çok az, güvenilir sonuç yok.")
    print("=" * 52)


def _configured_partial_tp_weights():
    """Use the same partial-close proportions as risk and signal tracking."""
    raw = getattr(Config, "SIGNAL_OUTCOME_PARTIAL_WEIGHTS", "0.5,0.3,0.2")
    if isinstance(raw, dict):
        values = [raw.get(f"tp{i}", 1.0) for i in range(1, 4)]
    elif isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = []

    weights = {}
    for index in range(3):
        value = values[index] if index < len(values) else 1.0
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = 0.0
        weights[f"tp{index + 1}"] = number if math.isfinite(number) and number > 0 else 0.0

    if sum(weights.values()) <= 0:
        return {"tp1": 1.0, "tp2": 1.0, "tp3": 1.0}
    return weights


def _effective_now_ms(data):
    """Backtest referans zamanı: veri bize verdiği son kapanmış mumun kapanışı.

    Backtest "gerçek şu an" yerine exchange'in sunduğu son kapanış anı üzerinden
    replay yapar. Böylece Bybit'in henüz kapanmamış mumundan kaynaklanan
    freshness hatası alınmaz ve tarihsel veri tutarlı kalır.
    """
    last_closes = []
    for tf in ("15m", "1h", "4h", "1d", "1w"):
        candles = data.get(tf) or []
        if candles:
            duration = TIMEFRAME_DURATION_MS.get(tf, 0)
            last_closes.append(max(c.time + duration for c in candles))
    if not last_closes:
        return time.time() * 1000
    return float(min(last_closes))


def _checkpoint_path(checkpoint_dir, symbol, days):
    safe = symbol.replace("/", "_").replace(":", "_")
    return os.path.join(checkpoint_dir, f"backtest_chunk_{safe}_{int(days)}d.json")


def _load_checkpoint(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _save_checkpoint(path, payload):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        logging.warning("Checkpoint yazımı başarısız | %s: %s", path, exc)


def _backtest_run_fingerprint(*, symbol, days, chunk_days, step, limit_expiry_bars, lenient, walk_forward):
    """Inputs that make a resumed historical chunk result reusable."""
    config_keys = (
        "MAKER_FEE_RATE", "TAKER_FEE_RATE", "STOP_SPREAD_BUFFER_RATE",
        "STOP_SLIPPAGE_BUFFER_RATE", "MINIMUM_RR", "MINIMUM_NET_RR",
        "MIN_STOP_ATR_MULTIPLIER", "AUTO_EXPAND_TIGHT_STOPS",
        "REJECT_TIGHT_STOPS", "INITIAL_BALANCE",
    )
    return {
        "symbol": str(symbol),
        "days": int(days),
        "chunk_days": int(chunk_days),
        "step": int(step),
        "limit_expiry_bars": int(limit_expiry_bars),
        "lenient": bool(lenient),
        "walk_forward": bool(walk_forward),
        "source_revision": _git_revision(),
        "partial_tp_weights": _configured_partial_tp_weights(),
        "config": {key: getattr(Config, key, None) for key in config_keys},
    }


def run_segmented_backtest(engine, symbols, days, chunk_days, checkpoint_dir,
                           resume, step, limit_expiry_bars, lenient, walk_forward=False):
    """Büyük backtesti tarih aralıklarına göre parçalara böler ve kalıcı checkpoint'ler yazar.

    Her parça bağımsız veri indirir ve çalışır; bellekte tek parça kadar veri
    tutulur. Parça sonuçları JSON checkpoint dosyasına yazılır. Program
    durursa --resume ile tamamlanmış parçalar atlanarak kaldığı yerden devam
    edilir. Tüm parçalar tamamlanmazsa sonuç INCOMPLETE olarak işaretlenir.
    """
    total_chunks = max(1, math.ceil(float(days) / float(chunk_days)))
    overall_status = "SUCCESS"
    combined_all = []
    is_results = []
    oos_results = []
    oos_chunk_count = max(1, math.ceil(total_chunks * 0.30))

    for symbol in symbols:
        listing_time_ms = _market_listing_time_ms(symbol)
        checkpoint_path = _checkpoint_path(checkpoint_dir, symbol, days)
        checkpoint = _load_checkpoint(checkpoint_path) if resume else None
        run_fingerprint = _backtest_run_fingerprint(
            symbol=symbol, days=days, chunk_days=chunk_days, step=step,
            limit_expiry_bars=limit_expiry_bars, lenient=lenient,
            walk_forward=walk_forward,
        )

        completed_chunks = set()
        chunk_results = {}
        anchor_now_ms = time.time() * 1000
        if checkpoint:
            compatible = (
                checkpoint.get("symbol") == symbol
                and checkpoint.get("run_fingerprint") == run_fingerprint
                and checkpoint.get("anchor_now_ms") is not None
            )
            if compatible:
                completed_chunks = {
                    int(index) for index in checkpoint.get("completed_chunks", [])
                    if 0 <= int(index) < total_chunks
                }
                chunk_results = {
                    str(k): v for k, v in (checkpoint.get("results") or {}).items()
                    if str(k).isdigit() and 0 <= int(k) < total_chunks
                }
                anchor_now_ms = float(checkpoint["anchor_now_ms"])
            else:
                print("  [checkpoint] Ayarlar/kod/zaman çıpası uyuşmuyor; eski parçalar kullanılmayacak.")

        print(
            f"\n=== {symbol} | {days}g | parçalı backtest "
            f"(parça={chunk_days}g, toplam={total_chunks}) ==="
        )

        for chunk_index in range(total_chunks):
            # Parça 0 = en yeni (şuandan geriye chunk_days), parça N = daha eski.
            chunk_now_ms = anchor_now_ms - chunk_index * chunk_days * 86_400_000
            chunk_label = f"{chunk_index + 1}/{total_chunks}"

            if chunk_index in completed_chunks:
                print(f"  [atlandi] {chunk_label} (checkpoint'te tamamlanmis)")
                restored_stats = chunk_results[str(chunk_index)]
                combined_all.append((symbol, restored_stats))
                if walk_forward:
                    (oos_results if chunk_index < oos_chunk_count else is_results).append((symbol, restored_stats))
                continue

            print(f"  [isleniyor] {chunk_label} ...", flush=True)
            try:
                data = load_historical(
                    symbol, days=chunk_days, now_ms=chunk_now_ms,
                    listing_time_ms=listing_time_ms,
                )
                attach_historical_smt_universe(data, chunk_days, chunk_now_ms)
                _validate_backtest_history(data, symbol)
                effective_now_ms = _effective_now_ms(data)
                _validate_backtest_coverage(
                    data, symbol, chunk_days, effective_now_ms,
                    listing_time_ms=listing_time_ms,
                )
                runner = BacktestRunner(
                    analyze_fn=build_analyze_fn(engine),
                    maker_fee_rate=float(getattr(Config, "MAKER_FEE_RATE", 0.0002)),
                    taker_fee_rate=float(getattr(Config, "TAKER_FEE_RATE", 0.00055)),
                    spread_rate=float(getattr(Config, "STOP_SPREAD_BUFFER_RATE", 0.0002)),
                    slippage_rate=float(getattr(Config, "STOP_SLIPPAGE_BUFFER_RATE", 0.0003)),
                    tp_weights=_configured_partial_tp_weights(),
                    limit_expiry_bars=limit_expiry_bars,
                )
                stats = runner.run(data, step=step, lenient=lenient)
                _report(stats, f"{symbol} parca {chunk_label}")
                chunk_results[str(chunk_index)] = stats
                completed_chunks.add(chunk_index)
                combined_all.append((symbol, stats))
                if walk_forward:
                    (oos_results if chunk_index < oos_chunk_count else is_results).append((symbol, stats))

                _save_checkpoint(checkpoint_path, {
                    "symbol": symbol,
                    "days": days,
                    "chunk_days": chunk_days,
                    "total_chunks": total_chunks,
                    "run_fingerprint": run_fingerprint,
                    "anchor_now_ms": anchor_now_ms,
                    "completed_chunks": sorted(completed_chunks),
                    "results": chunk_results,
                    "status": "IN_PROGRESS",
                    "updated_at": time.time(),
                })
                pct = len(completed_chunks) / total_chunks * 100
                print(f"  [tamamlandi] {chunk_label} | ilerleme %{pct:.0f}")
            except Exception as exc:
                logging.exception("Parça başarısız | %s %s: %s", symbol, chunk_label, exc)
                overall_status = "FAILED"
                _save_checkpoint(checkpoint_path, {
                    "symbol": symbol,
                    "days": days,
                    "chunk_days": chunk_days,
                    "total_chunks": total_chunks,
                    "run_fingerprint": run_fingerprint,
                    "anchor_now_ms": anchor_now_ms,
                    "completed_chunks": sorted(completed_chunks),
                    "results": chunk_results,
                    "status": "FAILED",
                    "error": f"{chunk_label}: {type(exc).__name__}: {exc}",
                    "updated_at": time.time(),
                })
                break

        if len(completed_chunks) == total_chunks:
            _save_checkpoint(checkpoint_path, {
                "symbol": symbol,
                "days": days,
                "chunk_days": chunk_days,
                "total_chunks": total_chunks,
                "run_fingerprint": run_fingerprint,
                "anchor_now_ms": anchor_now_ms,
                "completed_chunks": sorted(completed_chunks),
                "results": chunk_results,
                "status": "SUCCESS",
                "updated_at": time.time(),
            })
        elif completed_chunks:
            overall_status = "INCOMPLETE"

    if walk_forward:
        print("\n=== WALK-FORWARD | PARAMETRELER SABİT ===")
        print(f"IS: eski dönem {len(is_results)} sembol/parça | OOS: en yeni dönem {len(oos_results)} sembol/parça")
        if is_results:
            _report(_combine_stats(is_results), "IS (ESKİ DÖNEM)")
        else:
            print("IS verisi yok; OOS karşılaştırması geçersiz.")
        if oos_results:
            _report(_combine_stats(oos_results), "OOS (EN YENİ DÖNEM)")
        else:
            print("OOS verisi yok.")

    if combined_all:
        combined = _combine_stats(combined_all)
        print("\n=== BIRLEŞTİRİLİK SONUÇ ===")
        _report(combined, "TÜM PARÇALAR (BİRLEŞTİRİLİK)")
        print(f"\n{len(symbols)} sembol | Parçalı mod")
        print(f"{'Sembol':<22} {'Sinyal':>7} {'Winrate':>9} {'PF':>6} {'NetRR':>8}")
        for symbol, stats in combined_all:
            print(
                f"{symbol:<22} {stats['total']:>7} {stats['winrate']:>8}% "
                f"{stats['profit_factor']:>6} {stats['net_rr']:>8.2f}"
            )
    else:
        print("\nHIÇ PARÇA TAMAMLANAMADI.")

    return overall_status


def _git_revision():
    """Return the exact source revision used for this historical run."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Atlas sinyal backtest")
    parser.add_argument("--symbol", default="BTC/USDT:USDT", help="Tek sembol (Bybit swap)")
    parser.add_argument("--symbols", help="Virgülle ayrılmış sembol listesi (çoklu tarama; --symbol'dan öncelikli)")
    parser.add_argument("--days", type=int, default=60, help="Kaç gün geriye gidilecek")
    parser.add_argument("--step", type=int, default=1, help="Kaç adet 15m mumda bir analiz yapılacağı (varsayılan: 1 = her 15 dakika)")
    parser.add_argument(
        "--limit-expiry-bars", type=int, default=8,
        help="LIMIT emrinin en fazla kaç adet 15m mum bekleyeceği (varsayılan: 8 = 2 saat)",
    )
    parser.add_argument("--tf", choices=("15m",), default="15m", help="Giriş zaman dilimi (şimdilik yalnızca 15m)")
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="Decision kapısını atla; ham sinyal (LONG/SHORT) seviyesinde edge ölç",
    )
    parser.add_argument(
        "--chunk-days", type=int, default=0,
        help="Tarih aralığını bu günlük parçalara bölerek çalıştır (0 = tek parça; önerilen: 15)"
    )
    parser.add_argument(
        "--checkpoint-dir", default=".backtest_checkpoints",
        help="Checkpoint ve parça sonuçlarının kaydedileceği dizin"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Kaldığı yerden devam et (tamamlanmış parçaları atla)"
    )
    parser.add_argument("--walk-forward", action="store_true", help="Parçalı backtestte eski IS / en yeni OOS performansını ayrı raporla; parametreleri sabit tut")
    args = parser.parse_args()

    if args.days <= 0:
        parser.error("--days must be greater than zero")
    if args.step <= 0:
        parser.error("--step must be greater than zero")
    if args.limit_expiry_bars <= 0:
        parser.error("--limit-expiry-bars must be greater than zero")
    if args.walk_forward and (args.chunk_days <= 0 or math.ceil(args.days / args.chunk_days) < 2):
        parser.error("--walk-forward için en az iki parça oluşturacak --chunk-days gerekli")

    # Config.refresh_from_env() runs again inside AtlasEngine.__init__, so
    # disable live-only features in the environment before constructing it.
    _disable_backtest_live_features()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else [args.symbol]

    engine = AtlasEngine()

    print(
        f"\nBacktest | {len(symbols)} sembol | {args.days}g | TF={args.tf} | "
        f"mod={'lenient (ham sinyal)' if args.lenient else 'katı (EXECUTE)'}"
    )

    # Semboller arası signal durumunu izole et: runner tek örnekte yok, engine'deki
    # cooldown 0 olduğu için ardışık tarama bir sonraki sembolü etkilemez.
    print(f"VERİ SAĞLAYICISI | {_history_provider_name}")
    print(f"KOD SÜRÜMÜ | {_git_revision()}")
    print(
        "BACKTEST AYARLARI | "
        f"maker_fee={getattr(Config, 'MAKER_FEE_RATE', 0.0002)} | "
        f"taker_fee={getattr(Config, 'TAKER_FEE_RATE', 0.00055)} | "
        f"spread_per_market_leg={getattr(Config, 'STOP_SPREAD_BUFFER_RATE', 0.0002)} | "
        f"slippage_per_market_leg={getattr(Config, 'STOP_SLIPPAGE_BUFFER_RATE', 0.0003)} | "
        f"partial_tp_weights={_configured_partial_tp_weights()} | "
        f"limit_expiry_bars={args.limit_expiry_bars} | "
        f"minimum_rr={getattr(Config, 'MINIMUM_RR', 'unknown')} | "
        f"min_stop_atr={getattr(Config, 'MIN_STOP_ATR_MULTIPLIER', 'unknown')} | "
        f"auto_expand_stop={getattr(Config, 'AUTO_EXPAND_TIGHT_STOPS', 'unknown')} | "
        f"reject_tight_stops={getattr(Config, 'REJECT_TIGHT_STOPS', 'unknown')} | "
        f"step={args.step} ({args.step * 15}m) | lenient={args.lenient}"
    )
    all_stats = []
    backtest_now_ms = time.time() * 1000

    # Eğer parçalı backtest istenmişse ayrı akışı kullan (bellek/CPU kontrolü,
    # kalıcı checkpoint, kaldığı yerden devam et, ilerleme yüzdesi).
    if args.chunk_days and args.chunk_days > 0:
        overall_status = run_segmented_backtest(
            engine=engine,
            symbols=symbols,
            days=args.days,
            chunk_days=args.chunk_days,
            checkpoint_dir=args.checkpoint_dir,
            resume=args.resume,
            step=args.step,
            limit_expiry_bars=args.limit_expiry_bars,
            lenient=args.lenient,
            walk_forward=args.walk_forward,
        )
        print(f"\nGENEL DURUM: {overall_status}")
        return

    for symbol in symbols:
        listing_time_ms = _market_listing_time_ms(symbol)
        if listing_time_ms is not None:
            listing_date = time.strftime("%Y-%m-%d", time.gmtime(listing_time_ms / 1000))
            print(f"MARKET LİSTELENME | {symbol}: {listing_date}")
        data = load_historical(
            symbol, days=args.days, now_ms=backtest_now_ms, listing_time_ms=listing_time_ms
        )
        attach_historical_smt_universe(data, args.days, backtest_now_ms)
        _validate_backtest_history(data, symbol)
        effective_now_ms = _effective_now_ms(data)
        _validate_backtest_coverage(
            data, symbol, args.days, effective_now_ms,
            listing_time_ms=listing_time_ms,
        )
        runner = BacktestRunner(
            analyze_fn=build_analyze_fn(engine),
            maker_fee_rate=float(getattr(Config, "MAKER_FEE_RATE", 0.0002)),
            taker_fee_rate=float(getattr(Config, "TAKER_FEE_RATE", 0.00055)),
            spread_rate=float(getattr(Config, "STOP_SPREAD_BUFFER_RATE", 0.0002)),
            slippage_rate=float(getattr(Config, "STOP_SLIPPAGE_BUFFER_RATE", 0.0003)),
            tp_weights=_configured_partial_tp_weights(),
            limit_expiry_bars=args.limit_expiry_bars,
        )
        stats = runner.run(data, step=args.step, lenient=args.lenient)
        _report(stats, symbol)
        all_stats.append((symbol, stats))

    print(f"\n{len(symbols)} sembol | Mod: {'lenient' if args.lenient else 'katı'}")
    print(f"{'Sembol':<22} {'Sinyal':>7} {'Winrate':>9} {'PF':>6} {'NetRR':>8}")
    for symbol, stats in all_stats:
        print(f"{symbol:<22} {stats['total']:>7} {stats['winrate']:>8}% {stats['profit_factor']:>6} {stats['net_rr']:>8.2f}")

    combined = _combine_stats(all_stats)
    if combined["candidate_signals"] > 0 or combined["total"] > 0 or any(combined.get(key) for key in ("wait_reason_counts", "entry_reason_counts", "risk_reason_counts", "target_reason_counts", "target_missing_rr_counts", "stop_atr_buckets")):
        _report(combined, "BİRLEŞİK")


if __name__ == "__main__":
    main()
