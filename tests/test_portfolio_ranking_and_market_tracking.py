"""End-to-end regressions for portfolio selection and simulated MARKET entry states.

All inputs are deterministic and offline. None imply live order fills.
"""
import json
import math
import threading
import time
from unittest.mock import MagicMock

import pytest

import opportunity_pool
from opportunity_pool import OpportunityPool, SetupCandidate, SetupStatus
from telegram_command_service import TelegramCommandService


@pytest.fixture
def portfolio(tmp_path, monkeypatch):
    pool = OpportunityPool(base_path=str(tmp_path / "pool"), auto_persist=False)
    monkeypatch.setattr(opportunity_pool, "_pool_instance", pool)
    yield pool
    pool.stop()


def candidate(name, *, strategy="smc", rr=2.5, distance=None, fit=None,
              direction="LONG", entry_type="LIMIT"):
    now = int(time.time() * 1000)
    symbol = f"{name}/USDT:USDT"
    result = SetupCandidate(
        setup_id=f"{name}:{strategy}", symbol=symbol,
        strategy_id=strategy, strategy_name=strategy,
        direction=direction, entry_type=entry_type,
        entry_price=100.0, stop_loss=99.0 if direction == "LONG" else 101.0,
        tp1=101.0 if direction == "LONG" else 99.0,
        tp2=102.0 if direction == "LONG" else 98.0,
        tp3=103.0 if direction == "LONG" else 97.0,
        rr_tp1=1.0, rr_tp2=2.0, rr_tp3=3.0,
        net_rr=rr, risk_reward=2.0, confidence=80.0, grade="A",
        score=80.0, net_rr_after_costs=rr,
        status=SetupStatus.VALIDATED.value, created_at_ms=now,
        validated_at_ms=now, evidence_at_ms=now,
        entry_distance_pct=distance, regime_fit=fit,
    )
    return result


def publish(pool, *items):
    for item in items:
        assert pool.add_candidate(item)
        assert pool.validate_candidate(item.setup_id)


def service():
    return TelegramCommandService(MagicMock(), "offline-token", "-1004433")


def test_best_five_command_persists_all_displayed_symbols_before_send(portfolio):
    publish(portfolio, candidate("BTC"), candidate("ETH"), candidate("SOL"))
    bot = service()
    bot._api = MagicMock(side_effect=RuntimeError("network down"))
    bot._command_and_reply("/eniyi5")
    assert len(portfolio.tracking.tracked(bot.chat_id)) == 3
    for symbol in ("BTC", "ETH", "SOL"):
        assert symbol in bot.handle_islemler()
    assert not bot.runtime.start_scan.called


def test_best_ten_is_idempotent_and_does_not_duplicate_active_records(portfolio):
    publish(portfolio, candidate("BTC"), candidate("ETH"))
    bot = service()
    bot.execute_command("/eniyi10")
    bot.execute_command("/eniyi10")
    assert len(portfolio.tracking.tracked(bot.chat_id)) == 2


def test_market_is_not_mislabeled_as_waiting_limit_or_filled(portfolio):
    market = candidate("BTC", entry_type="MARKET")
    publish(portfolio, market)
    bot = service()
    assert "BTC" in bot.execute_command("/eniyi5")
    tracked = portfolio.tracking.tracked(bot.chat_id)
    assert len(tracked) == 1 and tracked[0][2] == "WAITING"
    assert not tracked[0][3]["entry_reached"]
    report = bot.handle_islemler()
    assert "MARKET SİNYALİ" in report
    assert "Emir gönderilmedi" in report
    assert "LIMIT GİRİŞ BEKLEYENLER" not in report


def test_unconfirmed_market_history_has_explicit_ambiguity(portfolio):
    publish(portfolio, candidate("BTC", entry_type="MARKET"))
    bot = service()
    bot.execute_command("/eniyi5")
    with portfolio.tracking._transaction() as conn:
        conn.execute(
            "UPDATE chat_plans SET state='AMBIGUOUS',"
            "payload=json_set(payload,'$.ambiguity_reason','Alt mum geçmişi eksik') "
            "WHERE chat=?",
            (bot.chat_id,),
        )
    report = bot.handle_islemler()
    assert "DOĞRULAMA BEKLİYOR" in report
    assert "Alt mum geçmişi eksik" in report
    assert "MARKET SİNYALİ" not in report


def test_unverified_entry_remains_visible_today(portfolio):
    publish(portfolio, candidate("BTC"))
    bot = service()
    bot.execute_command("/eniyi5")
    with portfolio.tracking._transaction() as conn:
        conn.execute(
            "UPDATE chat_plans SET state='UNVERIFIED', "
            "payload=json_set(payload,'$.status','UNVERIFIED','$.resolved_at',?) "
            "WHERE chat=?",
            (int(time.time() * 1000), bot.chat_id),
        )
    report = bot.handle_islemler()
    assert "GİRİŞİ DOĞRULANAMAYANLAR" in report
    assert "BTC" in report


def test_verified_oos_edge_and_negative_oos_change_ranking(portfolio):
    publish(portfolio, candidate("GOOD", strategy="smc"),
            candidate("BAD", strategy="mean_reversion"))
    history = {
        "smc": {
            "is_trades": 40, "is_expectancy_r": 0.8, "is_profit_factor": 2.8,
            "is_expectancy_std_r": 0.3, "oos_trades": 20,
            "oos_expectancy_r": 0.7, "oos_profit_factor": 2.1,
        },
        "mean_reversion": {
            "is_trades": 40, "is_expectancy_r": -0.2, "is_profit_factor": 0.6,
            "is_expectancy_std_r": 0.7, "oos_trades": 20,
            "oos_expectancy_r": -0.4, "oos_profit_factor": 0.7,
        },
    }
    assert portfolio.get_best_setups(limit=2, performance=history)[0].symbol.startswith("GOOD")
    # Missing history is neutral: it never becomes a fictional edge.
    assert len(portfolio.get_best_setups(limit=2, performance={})) == 2


def test_recent_entry_distance_and_regime_affect_ranking(portfolio):
    publish(portfolio, candidate("NEAR", distance=0.001, fit=1.0),
            candidate("FAR", distance=0.04, fit=0.2))
    assert portfolio.get_best_setups(limit=2)[0].symbol.startswith("NEAR")


def test_only_observed_correlations_diversify_same_direction(portfolio):
    btc = candidate("BTC", rr=3.0)
    eth = candidate("ETH", rr=2.8)
    sol = candidate("SOL", rr=2.6)
    publish(portfolio, btc, eth, sol)
    observed = {frozenset((btc.symbol, eth.symbol)): 0.98}
    result, _ = portfolio.prepare_best_reply("chat", 3, correlations=observed)
    assert [item.symbol for item in result] == [btc.symbol, sol.symbol]
    # Opposite exposure may hedge, so it is not excluded merely for high raw correlation.
    eth.direction = "SHORT"
    result, _ = portfolio.prepare_best_reply("chat", 3, correlations=observed)
    assert len(result) == 3


def test_real_four_hour_return_cache_yields_correlation_without_fetching_network():
    from atlas_runtime import AtlasRuntime
    from core.candle import Candle

    runtime = object.__new__(AtlasRuntime)
    runtime._h4_close_cache = {}
    runtime._h4_close_lock = threading.Lock()
    period = 4 * 3600_000
    now = int(time.time() * 1000)
    start = (now // period - 61) * period
    closes = [100.0]
    for i in range(1, 61):
        closes.append(closes[-1] * (1.0 + 0.001 * (1 + i % 5)))
    def candles(multiplier):
        return [Candle(start + i * period, value * multiplier, value * multiplier,
                       value * multiplier, value * multiplier, 5)
                for i, value in enumerate(closes)]
    runtime._remember_h4("BTC/USDT:USDT", candles(1), now)
    runtime._remember_h4("ETH/USDT:USDT", candles(2), now)
    corr = runtime.market_correlations()
    assert corr[frozenset(("BTC/USDT:USDT", "ETH/USDT:USDT"))] > 0.99
    # A stale snapshot is not interpreted as a fresh correlation.
    runtime._h4_close_cache["ETH/USDT:USDT"] = (
        now - 10 * 3_600_000, runtime._h4_close_cache["ETH/USDT:USDT"][1]
    )
    assert not runtime.market_correlations()


def test_scan_limit_is_explicit_about_clamping():
    bot = service()
    bot.runtime.start_scan.return_value = {
        "continuous": True, "started": True, "selected": 50,
        "progress": {"generation": 2, "done": 0, "failed": 0, "pending": 50},
    }
    reply = bot.handle_scan("200tara")
    assert "İstenen: 200" in reply
    assert "En fazla 50" in reply
    bot.runtime.start_scan.assert_called_once_with(200)
