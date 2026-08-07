"""
report.py
Canlı sinyal sonuç takibi verilerini (atlas_journal.db) gösteren CLI raporu.

Kullanım:
    python3 report.py                 # kısa özet
    python3 report.py --detail        # detaylı trade listesi
    python3 report.py --db <path>     # özel journal dosyası
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trade_journal import TradeJournal


def main():
    parser = argparse.ArgumentParser(description="Atlas canlı sinyal performans raporu")
    parser.add_argument("--db", default=os.getenv("ATLAS_TRADE_JOURNAL_DB_FILE", "atlas_journal.db"))
    parser.add_argument("--detail", action="store_true", help="Kapanan sinyallerin tek tek dökümünü göster")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"Journal bulunamadi: {args.db}")
        print("Once 'python3 main.py' ile scanner calistirin (ATLAS_SIGNAL_TRACKING_ENABLED=1).")
        sys.exit(1)

    journal = TradeJournal(db_path=args.db)
    summary = journal.summary()
    open_trades = journal.open_trades() if hasattr(journal, "open_trades") else []

    total = summary.get("total_trades", 0)
    open_count = len(open_trades)
    wins = summary.get("wins", 0)
    losses = summary.get("losses", 0)

    print("=" * 46)
    print("CANLI SINYAL SONUC RAPORU")
    print("=" * 46)
    print(f"  Kapali islem : {total}")
    print(f"  Acik sinyal  : {open_count}")
    if total:
        print(f"  Win / Loss   : {wins} / {losses}")
        print(f"  Winrate      : %{summary.get('winrate', 0)}")
        print(f"  Beklenti (R) : {summary.get('expectancy', 0)}")
        print(f"  Profit Fakt. : {summary.get('profit_factor', 0)}")
        print(f"  Max DD       : {summary.get('max_drawdown', 0)}")
        print(f"  Ort. kpc süre: {summary.get('average_hold_seconds', 0)} sn")
    else:
        print("  Henuz kapanmis sinyal yok. Scanner sinyal urettikce rapor dolar.")

    tpsl = summary.get("tp_sl_analysis", {})
    if total and isinstance(tpsl, dict) and tpsl.get("stop_rate") is not None:
        print("=" * 46)
        print("  TP1 vurma    : %{0}".format(tpsl.get("tp1_hit_rate", 0)))
        print("  TP2 vurma    : %{0}".format(tpsl.get("tp2_hit_rate", 0)))
        print("  TP3 vurma    : %{0}".format(tpsl.get("tp3_hit_rate", 0)))
        print("  SL vurma     : %{0}".format(tpsl.get("stop_rate", 0)))

    coins = summary.get("coin_statistics", {})
    if total and isinstance(coins, dict) and coins:
        print("=" * 46)
        print("  Sembol performansi")
        for symbol, stats in coins.items():
            print("    {0:<22} {1:>3} islem, winrate %{2}".format(symbol, stats.get("total", 0), stats.get("winrate", 0)))

    if open_count:
        print("=" * 46)
        print(f"  ACIK SINYALLER ({open_count})")
        for trade in open_trades:
            print(
                "    {0} {1:<5} entry={2} SL={3} TP1={4} | edildi={5}".format(
                    trade.get("symbol"), trade.get("side"), trade.get("entry"),
                    trade.get("stop_loss"), trade.get("tp1"), trade.get("opened_at"),
                )
            )

    if args.detail:
        closed = [t for t in (journal._trades or []) if t.get("status") == "CLOSED"]
        if closed:
            print("=" * 46)
            print("  KAPANAN SINYALLER")
            for trade in closed:
                print(
                    "    {0} {1:<5} {2} -> result={3} rr={4} ({5})".format(
                        trade.get("symbol"), trade.get("side"),
                        trade.get("opened_at"), trade.get("result"),
                        trade.get("pnl_rr"), trade.get("close_reason"),
                    )
                )


if __name__ == "__main__":
    main()