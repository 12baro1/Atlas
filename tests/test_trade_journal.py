import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_journal import TradeJournal


def _analysis(confidence, confluence, phase="Expansion"):
    return {
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "LONG", "confidence": confidence, "grade": "A", "strength": "STRONG"},
        "confluence": {"score": confluence, "confidence": confluence, "checks": ["✔ Entry"]},
        "risk": {"rr": 2.5, "position_size": 1.2, "capital_at_risk": 10},
        "entry": {"direction": "LONG", "valid": True, "entry": 100.0, "stop_loss": 99.0},
        "market_phase": {"phase": phase, "phase_score": 90, "phase_confidence": 85, "mtf_alignment": 100},
        "session": {"session": "LONDON"},
        "killzone": {"name": "LONDON"},
        "decision": {"action": "LONG"},
        "modules": {},
    }


def test_trade_journal_records_lifecycle_and_reports(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "journal.sqlite")

    first_snapshot = journal.record_analysis(_analysis(82, 88), symbol="BTC/USDT:USDT", timeframe="15m", timestamp=1_700_000_000_000)
    first_trade = journal.register_trade(
        trade={"side": "LONG", "entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "tp2": 102.0, "tp3": 103.0, "rr": 2.0, "confidence": 82, "confluence_score": 88},
        analysis=_analysis(82, 88),
        symbol="BTC/USDT:USDT",
        timestamp=1_700_000_000_000,
    )
    journal.close_trade(first_trade["id"], exit_price=102.0, result="WIN", timestamp=1_700_000_060_000)

    second_snapshot = journal.record_analysis(_analysis(61, 55, phase="Ranging"), symbol="ETH/USDT:USDT", timeframe="1h", timestamp=1_700_000_120_000)
    second_trade = journal.register_trade(
        trade={"side": "SHORT", "entry": 100.0, "stop_loss": 101.0, "tp1": 99.0, "tp2": 98.0, "tp3": 97.0, "rr": 1.5, "confidence": 61, "confluence_score": 55},
        analysis=_analysis(61, 55, phase="Ranging"),
        symbol="ETH/USDT:USDT",
        timestamp=1_700_000_120_000,
    )
    journal.close_trade(second_trade["id"], exit_price=101.5, result="LOSS", timestamp=1_700_000_180_000)

    summary = journal.summary()
    analysis_summary = journal.analysis_summary()
    report = journal.report_bundle()

    assert first_snapshot["symbol"] == "BTC/USDT:USDT"
    assert second_snapshot["symbol"] == "ETH/USDT:USDT"
    assert analysis_summary["total_snapshots"] == 2
    assert summary["total_trades"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["winrate"] == 50
    assert summary["profit_factor"] >= 0
    assert summary["max_drawdown"] >= 0
    assert report["recommendations"]["confidence_floor"] >= 0
    assert report["recommendations"]["confluence_floor"] >= 0
    assert report["analysis"]["total_snapshots"] == 2
    assert "strengths" in report
    assert "weaknesses" in report
