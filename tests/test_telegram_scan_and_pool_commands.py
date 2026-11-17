"""Telegram command integration tests for PR #173 additions.

Covers requirement G (best-5/10 strictly read-only) and requirement F
(scan commands through the real queue). All offline.
"""
import os
import sys
import time as time_mod

import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import opportunity_pool
from opportunity_pool import OpportunityPool, SetupCandidate, SetupStatus, SetupType
from telegram_command_service import TelegramCommandService, is_recognized_command


@pytest.fixture()
def pool(tmp_path, monkeypatch):
    """Fresh OpportunityPool singleton per test."""
    monkeypatch.setattr(opportunity_pool, "_pool_instance", None)
    instance = OpportunityPool(
        base_path=str(tmp_path / "pool"), auto_persist=False,
        max_candidates=50, max_validated=20, max_history=100,
    )
    monkeypatch.setattr(opportunity_pool, "_pool_instance", instance)
    yield instance
    instance.stop()
    monkeypatch.setattr(opportunity_pool, "_pool_instance", None)


def make_validated(pool, sid, symbol="BTC/USDT:USDT", strategy="smc", net_rr=2.5):
    now_ms = int(time_mod.time() * 1000)
    candidate = SetupCandidate(
        setup_id=sid, symbol=symbol, strategy_id=strategy, strategy_name=strategy,
        direction="LONG", entry_type="LIMIT", entry_price=50000.0, stop_loss=49500.0,
        tp1=51000.0, tp2=52000.0, tp3=53000.0, rr_tp1=2.0, rr_tp2=4.0, rr_tp3=6.0,
        net_rr=3.5, risk_reward=3.5, confidence=85.0, grade="A+", score=85.0,
        net_rr_after_costs=net_rr, status=SetupStatus.VALIDATED.value,
        setup_type=SetupType.LIMIT.value, regime="TREND", market_phase="Expansion",
        created_at_ms=now_ms, validated_at_ms=now_ms,
    )
    pool.add_candidate(candidate)
    pool.validate_candidate(sid)
    return candidate


def make_service(runtime=None):
    runtime = runtime or MagicMock()
    runtime.scan_status.return_value = {
        "total": 10, "pending": 2, "running": 0, "done": 8, "failed": 0,
        "percent": 80.0, "complete": False, "workers_running": True,
        "inventory": {"symbol_count": 300},
    }
    runtime.stop_scan.return_value = {
        "stopped": True, "workers_still_alive": [],
        "progress": {"pending": 2, "done": 8},
    }
    runtime.resume_scan.return_value = {
        "started": True, "progress": {"done": 8, "pending": 2, "percent": 80.0},
    }
    runtime.refresh_market_inventory.return_value = {"symbol_count": 312}
    return TelegramCommandService(runtime, "token", "-100123")


# ---------------------------------------------------------------------------
# Scan commands use the real queue
# ---------------------------------------------------------------------------

def test_scan_commands_call_real_queue(pool):
    runtime = MagicMock()
    runtime.start_scan.return_value = {
        "started": True, "universe_size": 300, "selected": 200, "added": 200,
        "progress": {"done": 0, "pending": 200, "percent": 0.0, "workers_running": True},
    }
    service = make_service(runtime)
    result = service.handle_scan("200tara")
    runtime.start_scan.assert_called_once_with(200)
    assert "TARAMA BAŞLADI" in result
    assert "200" in result


def test_scan_all_calls_queue_without_limit(pool):
    runtime = MagicMock()
    runtime.start_scan.return_value = {
        "started": True, "universe_size": 312, "selected": 312, "added": 12,
        "progress": {"done": 300, "pending": 12, "percent": 96.1},
    }
    service = make_service(runtime)
    service.handle_scan_all()
    runtime.start_scan.assert_called_once_with(None)


def test_scan_status_report(pool):
    service = make_service()
    result = service.handle_scan_status()
    assert "TARAMA DURUMU" in result
    assert "İlerleme: %80.0" in result
    assert "Worker'lar: çalışıyor" in result


def test_scan_stop_and_resume(pool):
    service = make_service()
    assert "TARAMA DURDURULDU" in service.handle_scan_stop()
    runtime = MagicMock()
    runtime.resume_scan.return_value = {
        "started": True,
        "progress": {"done": 5, "pending": 3, "percent": 62.5, "workers_running": True},
    }
    service = make_service(runtime)
    assert "sürdürülüyor" in service.handle_scan_resume()


def test_refresh_reports_inventory(pool):
    service = make_service()
    result = service.handle_refresh()
    assert "312" in result
    assert "Gate.io" in result


# ---------------------------------------------------------------------------
# Best 5/10: strictly read-only
# ---------------------------------------------------------------------------

def test_best_five_read_only_from_pool(pool):
    make_validated(pool, "s1")
    make_validated(pool, "s2", "ETH/USDT:USDT", net_rr=3.0)
    runtime = MagicMock()
    service = make_service(runtime)
    result = service.handle_best_five()
    # No scan, no analysis, no pool mutation was ever requested
    runtime.start_scan.assert_not_called()
    runtime.analyze_symbol.assert_not_called()
    assert "EN İYİ 2" in result
    assert "BTC/USDT:USDT" in result
    assert "LIMIT" in result
    assert "Giriş: 50000.0" in result
    assert "SL: 49500.0" in result
    assert "Net RR (maliyet sonrası): 3.0" in result
    assert "kazanma olasılığı değildir" in result
    # Strictly read-only: pool state unchanged
    stats = pool.get_stats()
    assert stats["validated"] == 2 and stats["candidates"] == 0


def test_best_ten_read_only(pool):
    for index in range(3):
        make_validated(pool, f"s{index}", f"S{index}/USDT:USDT")
    service = make_service()
    result = service.handle_best_ten()
    assert "EN İYİ 3" in result


def test_best_report_empty_pool_explicit(pool):
    service = make_service()
    result = service.handle_best_five()
    assert "havuzu boş" in result
    result = service.handle_best_ten()
    assert "havuzu boş" in result


def test_best_commands_recognized_and_read_only(pool):
    assert is_recognized_command("/eniyi10")
    assert is_recognized_command("en iyi 10")
    assert is_recognized_command("/taramadurum")
    assert is_recognized_command("havuz durumu")


def test_composite_ranking_prefers_net_rr_and_freshness(pool):
    now_ms = int(time_mod.time() * 1000)
    old = make_validated(pool, "old", "OLD/USDT:USDT", net_rr=4.0)
    old.created_at_ms = now_ms - 10 * 24 * 3600 * 1000  # 10 days old
    fresh = make_validated(pool, "fresh", "FRESH/USDT:USDT", net_rr=2.0)
    fresh.created_at_ms = now_ms
    service = make_service()
    result = service.handle_best_five()
    # Composite balances net RR against staleness: the fresh 2.0-RR setup
    # outranks the 10-day-old 4.0-RR setup.
    ranked = [line for line in result.splitlines() if line.startswith(("1. ", "2. "))]
    assert "FRESH/USDT:USDT" in ranked[0]

def test_scan_stop_reports_worker_still_running(pool):
    runtime = MagicMock()
    service = make_service(runtime)
    runtime.stop_scan.return_value = {
        "stopped": False,
        "workers_still_alive": ["AtlasScanWorker-0"],
        "progress": {"pending": 4, "running": 1, "done": 5},
    }
    result = service.handle_scan_stop()
    assert "TARAMA DURDURMA İSTEĞİ" in result
    assert "yeni worker başlatılmayacak" in result
    assert "AtlasScanWorker-0" in result


def test_scan_status_includes_strategy_funnel(pool):
    runtime = MagicMock()
    service = make_service(runtime)
    runtime.scan_status.return_value = {
        "total": 10, "pending": 2, "running": 0, "done": 8, "failed": 0,
        "percent": 80.0, "complete": False, "workers_running": True,
        "inventory": {"symbol_count": 300, "ranking_source": "gateio_24h_quote_volume"},
        "strategy_telemetry": {
            "analyses": 10, "raw_setups_generated": 4,
            "common_filter_passed": 2, "common_filter_rejected": 2,
            "per_strategy": {
                "smc": {"setups": 1, "passed": 1, "rejected": 0, "selected": 1}
            },
        },
        "pool": {"validated": 2},
    }
    result = service.handle_scan_status()
    assert "gateio_24h_quote_volume" in result
    assert "YEDİ STRATEJİ / ORTAK FİLTRE" in result
    assert "smc: 1 setup | 1 geçti | 0 elendi | 1 seçildi" in result

@pytest.mark.parametrize(("message", "limit"), [
    ("20 tara", 20),
    ("30 tara", 30),
    ("100 tara", 100),
])
def test_plain_text_scan_aliases_queue_requested_limit(pool, message, limit):
    runtime = MagicMock()
    runtime.start_scan.return_value = {
        "started": True, "universe_size": 300, "selected": limit,
        "added": limit, "ranking_source": "gateio_24h_quote_volume",
        "progress": {"done": 0, "pending": limit, "percent": 0.0},
    }
    service = make_service(runtime)
    assert is_recognized_command(message)
    service.execute_command(message)
    runtime.start_scan.assert_called_once_with(limit)


def test_plain_text_best_five_does_not_start_scan(pool):
    make_validated(pool, "plain-best-five")
    runtime = MagicMock()
    service = make_service(runtime)
    result = service.execute_command("en iyi 5")
    runtime.start_scan.assert_not_called()
    runtime.analyze_symbol.assert_not_called()
    assert "EN İYİ 1" in result

