import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manual_trade_service import ManualTradeService
from trade_journal import TradeJournal


def _prepare_signal(journal, symbol="BTC/USDT:USDT", direction="LONG"):
    return journal.register_signal_outcome(
        symbol=symbol,
        direction=direction,
        entry=100.0,
        stop_loss=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        opened_at=1_700_000_000_000,
    )


def test_manual_trade_service_not_traded_and_duplicate(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "journal.sqlite")
    outcome = _prepare_signal(journal)
    service = ManualTradeService(journal)

    trade, code = service.mark_not_traded(signal_id=outcome["signal_id"])
    assert code == "not_traded"
    assert trade["status"] == "NOT_TRADED"
    assert trade["result"] == "NOT_TRADED"

    duplicate, duplicate_code = service.mark_not_traded(signal_id=outcome["signal_id"])
    assert duplicate_code == "already_open"
    assert duplicate["signal_id"] == outcome["signal_id"]

    assert journal.learning_records(source="manual") == []


def test_manual_trade_service_early_exit_learning_refresh(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "journal.sqlite")
    outcome = _prepare_signal(journal, symbol="ETH/USDT:USDT", direction="SHORT")

    called = {"count": 0}

    def _refresh():
        called["count"] += 1

    service = ManualTradeService(journal, refresh_learning=_refresh)
    opened, open_code = service.open_trade(signal_id=outcome["signal_id"], actual_entry=100.0)
    assert open_code == "opened"
    assert opened["status"] == "OPEN"

    closed, close_code = service.close_trade(
        signal_id=outcome["signal_id"],
        result="EARLY_EXIT",
        actual_exit=99.4,
    )
    assert close_code == "closed"
    assert closed["status"] == "CLOSED"
    assert closed["result"] == "EARLY_EXIT"
    assert called["count"] == 1

    records = journal.learning_records(source="manual")
    assert len(records) == 1
    assert records[0]["result"] == "EARLY_EXIT"
