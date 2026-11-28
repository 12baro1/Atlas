"""Empty-opportunity-pool diagnostics do not turn stale MARKETs into entries."""
import time

import opportunity_pool
from opportunity_pool import OpportunityPool
from strategy_lab import _ensure_observed_atr, _risk_validate_candidate
from tests.test_portfolio_ranking_and_market_tracking import candidate, publish, service


class Candle:
    def __init__(self, close, high, low):
        self.open = close
        self.close = close
        self.high = high
        self.low = low
        self.volume = 100.0


def test_structural_smc_missing_atr_uses_only_observed_closed_candles():
    data = {"15m": [Candle(100 + i * 0.05, 101 + i * 0.05,
                            99 + i * 0.05) for i in range(30)]}
    item = {"entry": 100.0, "stop_loss": 98.5, "direction": "LONG",
            "entry_type": "LIMIT", "tp1": 103, "tp2": 105, "tp3": 107}
    observed = _ensure_observed_atr(item, data)
    assert observed is not None and observed > 0
    assert item["atr"] == observed
    assert item["atr_source"] == "OBSERVED_CLOSED_15M"
    # A missing ATR must not bypass the strict stop floor.
    result = _risk_validate_candidate(item)
    assert result["eligible"] in {True, False}
    assert "STOP_ATR_UNAVAILABLE" != result.get("reason")


def test_missing_atr_and_market_history_cannot_be_fabricated():
    item = {"entry": 100, "stop_loss": 99.5, "direction": "LONG",
            "entry_type": "MARKET", "tp1": 102, "tp2": 104, "tp3": 106}
    assert _ensure_observed_atr(item, {"15m": []}) is None
    assert "atr" not in item
    outcome = _risk_validate_candidate(item)
    assert outcome["eligible"] is False
    assert outcome["reason"] == "STOP_ATR_UNAVAILABLE"


def test_expired_market_is_stored_but_not_actionable(tmp_path, monkeypatch):
    pool = OpportunityPool(base_path=str(tmp_path / "pool"), auto_persist=False)
    monkeypatch.setattr(opportunity_pool, "_pool_instance", pool)
    try:
        setup = candidate("BTC", entry_type="MARKET")
        publish(pool, setup)
        setup.created_at_ms = int(time.time() * 1000) - 5 * 60_000
        assert pool.get_best_setups(limit=5) == []
        stats = pool.get_stats()
        assert stats["validated"] == 0
        assert stats["validated_stored"] == 1
        assert stats["market_expired"] == 1
        report = service().handle_pool_status()
        assert "MARKET süresi dolan: 1" in report
        assert "Doğrulanmış kayıt (toplam): 1" in report
        assert "Güncel giriş adayı: 0" in report
        assert "Şu an girilebilir doğrulanmış setup yok" in report
    finally:
        pool.stop()


def test_limit_remains_actionable_when_market_expires(tmp_path):
    pool = OpportunityPool(base_path=str(tmp_path / "pool"), auto_persist=False)
    try:
        market = candidate("BTC", entry_type="MARKET")
        limit = candidate("ETH", entry_type="LIMIT")
        publish(pool, market, limit)
        market.created_at_ms = int(time.time() * 1000) - 5 * 60_000
        assert [c.symbol for c in pool.get_best_setups(limit=5)] == [limit.symbol]
        assert pool.get_stats()["validated"] == 1
        assert pool.get_stats()["market_expired"] == 1
    finally:
        pool.stop()
