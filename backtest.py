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
import logging
import math
import time
import os
import ccxt
import sys
import subprocess

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

def load_historical(symbol, days=60, now_ms=None, listing_time_ms=None):
    """Load evaluation history, clamped to the market's actual listing date."""
    if float(days) <= 0:
        raise ValueError("Backtest days must be greater than zero")
    now = time.time() * 1000 if now_ms is None else float(now_ms)
    data = {"symbol": symbol}
    for tf, limit in TIMEFRAMES.items():
        history_days = _history_days_for_timeframe(days, tf)
        requested_since = now - int(history_days * 86_400_000)
        since = max(requested_since, listing_time_ms) if listing_time_ms else requested_since
        fetch_limit = limit + 2 if tf == "1w" else limit
        candles = _fetch_history(
            symbol, tf, since_ms=since, limit=fetch_limit
        )
        # Bybit includes the currently-forming candle in OHLCV responses.
        # A historical decision may only use candles that were fully closed
        # at the backtest's fixed as-of timestamp.
        duration_ms = TIMEFRAME_DURATION_MS[tf]
        candles = [candle for candle in candles if candle.time + duration_ms <= now]
        data[tf] = candles
        logging.info(
            "%s %s -> %s candles (history %.1f days)",
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
        # Candle boundaries are timeframe-aligned; allow two full intervals
        # for exchange boundary/availability differences, but not partial history.
        if first_open > effective_start + 2 * duration:
            missing_days = (first_open - effective_start) / 86_400_000
            raise RuntimeError(
                f"{symbol} {tf}: başlangıç verisi eksik. İstenen başlangıç "
                f"{history_days:.1f} günlük geçmiş; kullanılabilir başlangıca göre "
                f"ilk mum {missing_days:.1f} gün geç geliyor."
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
        "market_fallback_fills": 0,
        "market_fallback_rejected_rr": 0,
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
            "market_fallback_fills", "market_fallback_rejected_rr",
            "overlapping_signals_skipped", "open_trades",
            "invalid_candidates", "no_followup_data",
        ):
            combined[key] += int(stats.get(key, 0) or 0)
        for key in ("action_counts", "wait_reason_counts", "signal_reason_counts", "mtf_alignment_counts", "entry_reason_counts", "entry_type_counts", "risk_reason_counts", "target_reason_counts", "target_missing_rr_counts", "stop_atr_buckets", "confirmation_outcome_counts", "confirmation_reason_counts", "confirmation_requirement_counts", "entry_type_reason_counts"):
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

    combined["losses"] = combined["total"] - combined["wins"]
    if combined["total"]:
        combined["winrate"] = round(combined["wins"] / combined["total"] * 100, 2)
        combined["expectancy"] = round(combined["net_rr"] / combined["total"], 4)
        combined["gross_expectancy"] = round(combined["gross_rr"] / combined["total"], 4)
    combined["gross_profit_rr"] = round(sum(max(0.0, float(x.get("gross_rr", x.get("net_rr", 0.0)) or 0.0)) for x in combined["trade_history"]), 4)
    combined["gross_loss_rr"] = round(abs(sum(min(0.0, float(x.get("gross_rr", x.get("net_rr", 0.0)) or 0.0)) for x in combined["trade_history"])), 4)
    combined["gross_profit_factor"] = _metrics_for_trades(combined["trade_history"])["gross_profit_factor"]
    combined["profit_factor"] = _metrics_for_trades(combined["trade_history"])["profit_factor"]
    return combined


def _report(stats, name):
    print("=" * 52)
    print(f"SONUÇ | {name}")
    print(f"  Maliyet varsayımları: fee={getattr(Config, 'ROUND_TRIP_COST_RATE', 0.002):.4%} | "
          f"spread={getattr(Config, 'STOP_SPREAD_BUFFER_RATE', 0.0002):.4%} | "
          f"slippage={getattr(Config, 'STOP_SLIPPAGE_BUFFER_RATE', 0.0003):.4%} (notional proxy)")
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
    args = parser.parse_args()

    if args.days <= 0:
        parser.error("--days must be greater than zero")
    if args.step <= 0:
        parser.error("--step must be greater than zero")
    if args.limit_expiry_bars <= 0:
        parser.error("--limit-expiry-bars must be greater than zero")

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
        f"fee={getattr(Config, 'ROUND_TRIP_COST_RATE', 0.002)} | "
        f"spread_proxy={getattr(Config, 'STOP_SPREAD_BUFFER_RATE', 0.0002)} | "
        f"slippage_proxy={getattr(Config, 'STOP_SLIPPAGE_BUFFER_RATE', 0.0003)} | "
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
        _validate_backtest_coverage(
            data, symbol, args.days, backtest_now_ms,
            listing_time_ms=listing_time_ms,
        )
        runner = BacktestRunner(
            analyze_fn=build_analyze_fn(engine),
            fee_rate=float(getattr(Config, "ROUND_TRIP_COST_RATE", 0.002)),
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
