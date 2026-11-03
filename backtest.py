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


def _history_days_for_timeframe(days, timeframe):
    """Fetch enough prehistory for each timeframe's structure warmup."""
    days = float(days)
    if not days > 0:
        raise ValueError("Backtest days must be greater than zero")
    if timeframe not in TIMEFRAME_DURATION_MS:
        raise ValueError(f"Unsupported backtest timeframe: {timeframe}")
    warmup_days = (
        BACKTEST_WARMUP_CANDLES[timeframe]
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

def load_historical(symbol, days=60, now_ms=None):
    """Load the evaluation window plus sufficient timeframe-specific warmup."""
    if float(days) <= 0:
        raise ValueError("Backtest days must be greater than zero")
    now = time.time() * 1000 if now_ms is None else float(now_ms)
    data = {"symbol": symbol}
    for tf, limit in TIMEFRAMES.items():
        history_days = _history_days_for_timeframe(days, tf)
        since = now - int(history_days * 86_400_000)
        candles = _fetch_history(symbol, tf, since_ms=since, limit=limit)
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


def _validate_backtest_coverage(data, symbol, days, now_ms):
    """Ensure every timeframe covers the requested evaluation and warmup window."""
    now = float(now_ms)
    coverage = {}
    for tf in ("15m", "1h", "4h", "1d", "1w"):
        candles = data.get(tf) or []
        duration = TIMEFRAME_DURATION_MS[tf]
        history_days = _history_days_for_timeframe(days, tf)
        requested_start = now - history_days * 86_400_000
        if not candles:
            raise RuntimeError(f"{symbol} {tf}: tarihsel veri yok; backtest durduruldu.")

        first_open = min(c.time for c in candles)
        last_close = max(c.time + duration for c in candles)
        # Candle boundaries are timeframe-aligned; allow two full intervals
        # for exchange boundary/availability differences, but not partial history.
        if first_open > requested_start + 2 * duration:
            missing_days = (first_open - requested_start) / 86_400_000
            raise RuntimeError(
                f"{symbol} {tf}: başlangıç verisi eksik. İstenen geçmiş "
                f"{history_days:.1f} gün; ilk mum {missing_days:.1f} gün geç geliyor."
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
        }
    print("TARİH KAPSAMI | " + " | ".join(
        f"{tf}: {item['requested_days']}g / {item['count']} mum"
        for tf, item in coverage.items()
    ))
    return coverage


def build_analyze_fn(engine):
    def analyze(window):
        try:
            return engine.analyze(window)
        except Exception as exc:  # tek bir sinyal hatası taramayı durdurmasın
            logging.debug("analyze error: %s", exc)
            return None
    return analyze


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
        "candidate_signals": 0,
        "analysis_calls": 0,
        "empty_results": 0,
        "raw_long_signals": 0,
        "raw_short_signals": 0,
        "non_directional_results": 0,
        "action_counts": {},
        "unfilled_limits": 0,
        "open_trades": 0,
        "invalid_candidates": 0,
        "no_followup_data": 0,
        "tp1": 0,
        "tp2": 0,
        "tp3": 0,
    }
    for _, stats in all_stats:
        for key in (
            "total", "wins", "tp1", "tp2", "tp3",
            "candidate_signals", "analysis_calls", "empty_results",
            "raw_long_signals", "raw_short_signals", "non_directional_results",
            "unfilled_limits", "open_trades",
            "invalid_candidates", "no_followup_data",
        ):
            combined[key] += int(stats.get(key, 0) or 0)
        for action, count in (stats.get("action_counts") or {}).items():
            combined["action_counts"][action] = combined["action_counts"].get(action, 0) + int(count or 0)
        combined["net_rr"] += float(stats.get("net_rr", 0) or 0)
        combined["gross_profit_rr"] += float(stats.get("gross_profit_rr", 0) or 0)
        combined["gross_loss_rr"] += float(stats.get("gross_loss_rr", 0) or 0)

    combined["losses"] = combined["total"] - combined["wins"]
    if combined["total"]:
        combined["winrate"] = round(combined["wins"] / combined["total"] * 100, 2)
        combined["expectancy"] = round(combined["net_rr"] / combined["total"], 4)
    if combined["gross_loss_rr"] > 0:
        combined["profit_factor"] = round(
            combined["gross_profit_rr"] / combined["gross_loss_rr"], 2
        )
    elif combined["gross_profit_rr"] > 0:
        combined["profit_factor"] = round(combined["gross_profit_rr"], 2)
    return combined


def _report(stats, name):
    print("=" * 52)
    print(f"SONUÇ | {name}")
    print("=" * 52)
    print(f"  Analiz çağrısı : {stats.get('analysis_calls', 0)}")
    print(f"  Boş sonuç      : {stats.get('empty_results', 0)}")
    print(f"  Ham LONG/SHORT : {stats.get('raw_long_signals', 0)}/{stats.get('raw_short_signals', 0)}")
    print(f"  Yönsüz sonuç   : {stats.get('non_directional_results', 0)}")
    print(f"  Karar aksiyonları: {stats.get('action_counts', {})}")
    print(f"  Aday sinyal    : {stats.get('candidate_signals', 0)}")
    print(f"  Kapanan işlem  : {stats['total']}")
    print(f"  Açık işlem     : {stats.get('open_trades', 0)}")
    print(f"  Dolmayan LIMIT : {stats.get('unfilled_limits', 0)}")
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
    print(f"  Beklenti       : {stats['expectancy']} RR/işlem")
    print(f"  Profit Factor  : {stats['profit_factor']}")
    print(f"  Net RR         : {stats['net_rr']}")
    if "max_drawdown" in stats:
        print(f"  Max Drawdown   : {stats['max_drawdown']} R")
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
    raw = getattr(Config, "SIGNAL_OUTCOME_PARTIAL_WEIGHTS", "1.0,1.0,1.0")
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


def main():
    parser = argparse.ArgumentParser(description="Atlas sinyal backtest")
    parser.add_argument("--symbol", default="BTC/USDT:USDT", help="Tek sembol (Bybit swap)")
    parser.add_argument("--symbols", help="Virgülle ayrılmış sembol listesi (çoklu tarama; --symbol'dan öncelikli)")
    parser.add_argument("--days", type=int, default=60, help="Kaç gün geriye gidilecek")
    parser.add_argument("--tf", choices=("15m",), default="15m", help="Giriş zaman dilimi (şimdilik yalnızca 15m)")
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="Decision kapısını atla; ham sinyal (LONG/SHORT) seviyesinde edge ölç",
    )
    args = parser.parse_args()

    if args.days <= 0:
        parser.error("--days must be greater than zero")

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
    all_stats = []
    for symbol in symbols:
        data = load_historical(symbol, days=args.days)
        _validate_backtest_history(data, symbol)
        _validate_backtest_coverage(data, symbol, args.days, time.time() * 1000)
        runner = BacktestRunner(
            analyze_fn=build_analyze_fn(engine),
            fee_rate=float(getattr(Config, "ROUND_TRIP_COST_RATE", 0.002)),
            tp_weights=_configured_partial_tp_weights(),
        )
        stats = runner.run(data, step=5, lenient=args.lenient)
        _report(stats, symbol)
        all_stats.append((symbol, stats))

    print(f"\n{len(symbols)} sembol | Mod: {'lenient' if args.lenient else 'katı'}")
    print(f"{'Sembol':<22} {'Sinyal':>7} {'Winrate':>9} {'PF':>6} {'NetRR':>8}")
    for symbol, stats in all_stats:
        print(f"{symbol:<22} {stats['total']:>7} {stats['winrate']:>8}% {stats['profit_factor']:>6} {stats['net_rr']:>8.2f}")

    combined = _combine_stats(all_stats)
    if combined["candidate_signals"] > 0 or combined["total"] > 0:
        _report(combined, "BİRLEŞİK")


if __name__ == "__main__":
    main()
