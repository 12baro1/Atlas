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
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")

from data_engine import exchange, TIMEFRAMES
from core.candle import Candle
from backtest_runner import BacktestRunner
from engine import AtlasEngine
from config import Config


def _fetch_history(symbol, timeframe, since_ms, limit=1000):
    candles = []
    cursor = since_ms
    attempts = 0
    while True:
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=limit)
        except Exception:
            attempts += 1
            if attempts > 3:
                break
            time.sleep(0.5 * attempts)
            continue
        attempts = 0
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
    # Tarihe göre sırala ve tekilleştir
    seen = set()
    ordered = []
    for candle in sorted(candles, key=lambda c: c.time):
        if candle.time in seen:
            continue
        seen.add(candle.time)
        ordered.append(candle)
    return ordered


def load_historical(symbol, days=60):
    """days kadar geriye gidip 15m + üst TF mumlarını toplar."""
    now = time.time() * 1000
    since = now - int(days * 86400 * 1000)
    data = {"symbol": symbol}
    for tf, limit in TIMEFRAMES.items():
        candles = _fetch_history(symbol, tf, since_ms=since, limit=limit)
        data[tf] = candles
        logging.info("%s %s -> %s mum", symbol, tf, len(candles))
    return data


def build_analyze_fn(engine):
    def analyze(window):
        try:
            return engine.analyze(window)
        except Exception as exc:  # tek bir sinyal hatası taramayı durdurmasın
            logging.debug("analyze error: %s", exc)
            return None
    return analyze


def _report(stats, name):
    print("=" * 52)
    print(f"SONUÇ | {name}")
    print("=" * 52)
    print(f"  Toplam sinyal  : {stats['total']}")
    print(f"  Kazanç (WIN)   : {stats['wins']}")
    print(f"  Kayıp (LOSS)   : {stats['losses']}")
    print(f"  Winrate        : %{stats['winrate']}")
    print(f"  TP1/2/3        : {stats['tp1']}/{stats['tp2']}/{stats['tp3']}")
    print(f"  Beklenti       : {stats['expectancy']} RR/işlem")
    print(f"  Profit Factor  : {stats['profit_factor']}")
    print(f"  Net RR         : {stats['net_rr']}")

    if stats["total"] >= 20 and stats["expectancy"] > 0 and stats["profit_factor"] >= 1.3:
        print("  YORUM: Edge pozitif görünüyor; daha uzun örnekle doğrulanmalı.")
    elif stats["total"] >= 20:
        print("  YORUM: Edge net değil. Sinyal filtresi maliyetleri karşılamıyor.")
    elif stats["total"] >= 5:
        print(f"  YORUM: {stats['total']} sinyal az ama güvenilir örnek değil; daha uzun süre koş.")
    else:
        print(f"  YORUM: {stats['total']} sinyal çok az, güvenilir sonuç yok.")
    print("=" * 52)


def main():
    parser = argparse.ArgumentParser(description="Atlas sinyal backtest")
    parser.add_argument("--symbol", default="BTC/USDT:USDT", help="Tek sembol (Bybit swap)")
    parser.add_argument("--symbols", help="Virgülle ayrılmış sembol listesi (çoklu tarama; --symbol'dan öncelikli)")
    parser.add_argument("--days", type=int, default=60, help="Kaç gün geriye gidilecek")
    parser.add_argument("--tf", default="15m", help="Giriş zaman dilimi")
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="Decision kapısını atla; ham sinyal (LONG/SHORT) seviyesinde edge ölç",
    )
    args = parser.parse_args()

    # State/telegram/korelasyon gibi canlı mod bağımlılıklarını kapat
    Config.STATE_ENGINE_ENABLED = False
    Config.INCREMENTAL_ANALYSIS_ENABLED = False
    Config.TELEGRAM_ENABLED = False
    Config.CORRELATION_ENGINE_ENABLED = False
    Config.ECONOMIC_NEWS_FILTER_ENABLED = False
    Config.LEARNING_ENGINE_ENABLED = False
    # Sembol bazlı işlem yasağı sinyal üretimini gerçek backtestte bastırmasın
    Config.TRADE_COOLDOWN_MINUTES = 0.0
    Config.refresh_from_env()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else [args.symbol]

    engine = AtlasEngine()

    print(
        f"\nBacktest | {len(symbols)} sembol | {args.days}g | TF={args.tf} | "
        f"mod={'lenient (ham sinyal)' if args.lenient else 'katı (EXECUTE)'}"
    )

    # Semboller arası signal durumunu izole et: runner tek örnekte yok, engine'deki
    # cooldown 0 olduğu için ardışık tarama bir sonraki sembolü etkilemez.
    all_stats = []
    combined = {
        "total": 0, "wins": 0, "losses": 0, "winrate": 0,
        "expectancy": 0, "profit_factor": 0, "net_rr": 0,
        "tp1": 0, "tp2": 0, "tp3": 0,
    }

    for symbol in symbols:
        data = load_historical(symbol, days=args.days)
        runner = BacktestRunner(analyze_fn=build_analyze_fn(engine), fee_rate=float(getattr(Config, "ROUND_TRIP_COST_RATE", 0.002)))
        stats = runner.run(data, step=5, lenient=args.lenient)
        for key in ("total", "wins", "losses", "tp1", "tp2", "tp3"):
            combined[key] += stats[key]
        combined["net_rr"] += stats["net_rr"]
        _report(stats, symbol)
        all_stats.append((symbol, stats))

    print(f"\n{len(symbols)} sembol | Mod: {'lenient' if args.lenient else 'katı'}")
    print(f"{'Sembol':<22} {'Sinyal':>7} {'Winrate':>9} {'PF':>6} {'NetRR':>8}")
    for symbol, stats in all_stats:
        print(f"{symbol:<22} {stats['total']:>7} {stats['winrate']:>8}% {stats['profit_factor']:>6} {stats['net_rr']:>8.2f}")

    if combined["total"] > 0:
        combined["losses"] = combined["total"] - combined["wins"]
        combined["winrate"] = round(combined["wins"] / combined["total"] * 100, 2)
        combined["expectancy"] = round(combined["net_rr"] / combined["total"], 4) if combined["total"] else 0
        gross_loss = abs(sum(s[1]["net_rr"] for s in all_stats if s[1]["net_rr"] < 0))
        gross_win = sum(s[1]["net_rr"] for s in all_stats if s[1]["net_rr"] > 0)
        combined["profit_factor"] = round(gross_win / gross_loss, 2) if gross_loss > 0 else (round(gross_win, 2) if gross_win else 0.0)
        _report(combined, "BİRLEŞİK")


if __name__ == "__main__":
    main()
