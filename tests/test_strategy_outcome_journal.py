import json

from strategy_outcome_journal import StrategyOutcomeJournal


def test_journal_persists_and_aggregates_is_oos_separately(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    journal = StrategyOutcomeJournal(str(path))
    for index, value in enumerate([0.8, -0.4, 0.5, -0.2], start=1):
        result = journal.record_outcome(
            strategy_id="trend_pullback",
            trade_id=f"is-{index}",
            split="is",
            net_r=value,
            closed_at_ms=1_700_000_000_000 + index,
            costs_included=True,
            regime="TREND",
        )
        assert result["accepted"] is True
    for index, value in enumerate([0.6, -0.3, 0.4], start=1):
        journal.record_outcome(
            strategy_id="trend_pullback",
            trade_id=f"oos-{index}",
            split="oos",
            net_r=value,
            closed_at_ms=1_700_100_000_000 + index,
            costs_included=True,
            regime="TREND",
        )

    stats = StrategyOutcomeJournal(str(path)).performance_snapshot()["trend_pullback"]
    assert stats["is_trades"] == 4
    assert stats["oos_trades"] == 3
    assert stats["is_expectancy_r"] == 0.175
    assert stats["oos_expectancy_r"] > 0
    assert stats["is_profit_factor"] > 1


def test_journal_rejects_outcomes_without_costs_and_duplicate_ids(tmp_path):
    journal = StrategyOutcomeJournal(str(tmp_path / "outcomes.jsonl"))
    payload = dict(strategy_id="smc", trade_id="same", split="is", net_r=1.0, closed_at_ms=1000)
    assert journal.record_outcome(**payload, costs_included=False)["accepted"] is False
    assert journal.record_outcome(**payload, costs_included=True)["accepted"] is True
    assert journal.record_outcome(**payload, costs_included=True)["reason"] == "duplicate_trade_id"


def test_journal_rejects_unknown_strategy_and_non_finite_r(tmp_path):
    journal = StrategyOutcomeJournal(str(tmp_path / "outcomes.jsonl"))
    common = dict(trade_id="x", split="is", closed_at_ms=1000, costs_included=True)
    assert journal.record_outcome(strategy_id="made_up", net_r=1, **common)["accepted"] is False
    assert journal.record_outcome(strategy_id="smc", net_r=float("nan"), **common)["accepted"] is False


def test_journal_ignores_corrupt_lines(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    path.write_text("{bad json\n", encoding="utf-8")
    journal = StrategyOutcomeJournal(str(path))
    assert journal.performance_snapshot() == {}
