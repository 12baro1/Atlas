"""Requirement I: yedi strateji ba\u015f\u0131ms\u0131r setup \u00fcretim yolu.

Her strateji i\u00e7in:
- Ge\u00e7erli LONG setup \u00fcrebiliyor mu?
- Ge\u00e7erli SHORT setup \u00fcrebiliyor mu?
- Setup \u00fcretemeyen piyasa ko\u015fulu (None d\u00f6nmelidir)
- Ortak filtre reddi (common_filter_rejected, nedeni measurable)
- Ana karar motoruna aktar\u0131m (decision engine SELECTED)

Generator fonksiyonlar\u0131 monkeypatch ile kontrol edilir; her stratejin
kendi \u0131\u015flem manti\u011f\u0131na \u0131saret yap\u0131lmaz, sadece \u00e7\u0131kt\u0131s\u0131
\u00f6rnekle\u015fin Director/commun filtre/karar motoru ak\u0131\u015f\u0131na girdi\u011fi
olarak kullan\u0131l\u0131r. T\u00fcm testler offline ve fixture tabanl\u0131d\u0131r.
"""
import pytest

from strategy_lab import SevenStrategyLab, STRATEGY_NAMES
import strategy_lab


ALL_STRATEGY_IDS = {
    "trend_pullback", "volatility_breakout", "mean_reversion",
    "orderflow_momentum", "smc",
}


def _raw_plan(strategy_id, direction="LONG", entry=100.0, stop=98.0,
              tp1=102.0, tp2=104.0, tp3=106.0, strength=80.0,
              entry_type="LIMIT"):
    """A raw, geometry-valid plan for a strategy."""
    return {
        "status": "RAW_SETUP",
        "strategy_id": strategy_id,
        "strategy": STRATEGY_NAMES[strategy_id],
        "direction": direction,
        "entry_type": entry_type,
        "entry": entry,
        "stop_loss": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr_tp1": abs(tp1 - entry) / abs(entry - stop),
        "rr_tp2": abs(tp2 - entry) / abs(entry - stop),
        "rr_tp3": abs(tp3 - entry) / abs(entry - stop),
        "strength": strength,
        "reasons": [f"{strategy_id} {direction} setup"],
        "supporting_event_ids": [],
        "opposing_event_ids": [],
    }


def _eligible_risk(plan):
    return {
        "eligible": True, "reason": None, "weighted_net_rr": 2.5,
        "risk_plan": {
            "final_geometry_reconciled": True, "risk_setup_valid": True,
            "weighted_net_rr": 2.5, "weighted_rr": 2.7,
        },
    }


def _ineligible_risk(plan):
    return {
        "eligible": False, "reason": "NET_RR_BELOW_MINIMUM",
        "weighted_net_rr": 0.5,
        "risk_plan": {
            "final_geometry_reconciled": True, "risk_setup_valid": True,
            "weighted_net_rr": 0.5, "weighted_rr": 0.6,
        },
    }


# -----------------------------------------------------------------------
# Per-strategy: valid LONG, valid SHORT, no-setup, filter reject, decision
# -----------------------------------------------------------------------

def _make_lab(monkeypatch, strategy_id, generator_return, risk=_eligible_risk):
    """Patch a single strategy's generator and the shared risk filter."""
    import_strategy = {
        "trend_pullback": "strategies.trend.strategy",
        "volatility_breakout": "strategies.breakout.strategy",
        "mean_reversion": "strategies.mean_reversion.strategy",
        "liquidation_cascade": "strategies.liquidation.strategy",
        "orderflow_momentum": "strategies.orderflow.strategy",
        "relative_strength": "strategies.relative_strength.strategy",
        "smc": "strategies.smc.strategy",
    }[strategy_id]
    module = __import__(import_strategy, fromlist=["generate"])
    lab_attr = "_smc_candidate" if strategy_id == "smc" else f"_{strategy_id}"
    monkeypatch.setattr(strategy_lab, lab_attr, lambda *a, **k: generator_return)
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", risk)
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {
        "label": "TREND", "trend": "BULLISH", "strength": 1.0,
    })
    return module


def test_each_strategy_valid_long_setup(monkeypatch):
    """Her strateji ge\u00e7erli bir LONG setup \u00fcretebilmelidir."""
    for sid in ALL_STRATEGY_IDS:
        plan = _raw_plan(sid, direction="LONG")
        _make_lab(monkeypatch, sid, plan)
        report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
        row = next(r for r in report["strategies"] if r["strategy_id"] == sid)
        assert row["status"] in ("SELECTED", "FILTERED_NOT_SELECTED"), (
            f"{sid}: expected setup through common filter, got {row['status']}: {row.get('rejection_reasons')}"
        )
        usage = next(u for u in report["data_usage"] if u["strategy_id"] == sid)
        assert usage["setup_produced"] is True


def test_each_strategy_valid_short_setup(monkeypatch):
    """Her strateji ge\u00e7erli bir SHORT setup \u00fcretebilmelidir."""
    for sid in ALL_STRATEGY_IDS:
        plan = _raw_plan(sid, direction="SHORT", entry=100.0, stop=102.0,
                         tp1=98.0, tp2=96.0, tp3=94.0)
        _make_lab(monkeypatch, sid, plan)
        report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
        row = next(r for r in report["strategies"] if r["strategy_id"] == sid)
        assert row["status"] in ("SELECTED", "FILTERED_NOT_SELECTED"), (
            f"{sid}: expected setup through common filter, got {row['status']}: {row.get('rejection_reasons')}"
        )
        usage = next(u for u in report["data_usage"] if u["strategy_id"] == sid)
        assert usage["setup_produced"] is True


def test_each_strategy_rejects_bad_direction(monkeypatch):
    """Ge\u00e7ersiz d\u00f6n\u00fc\u015f (LONG/SHORT d\u0131\u015f\u0131 olmayan) \u00fcretilmemelidir."""
    for sid in ALL_STRATEGY_IDS:
        plan = _raw_plan(sid, direction="NEUTRAL")
        _make_lab(monkeypatch, sid, plan)
        report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
        row = next(r for r in report["strategies"] if r["strategy_id"] == sid)
        assert row["status"] in ("BLOCKED_COMMON_FILTER", "CONDITION_NOT_MET", "MISSING_DATA"), (
            f"{sid}: invalid direction must be rejected, got {row['status']}"
        )


def test_each_strategy_no_setup_when_generator_returns_none(monkeypatch):
    """Generator None d\u00f6nd\u00fcd\u00fcnde strateji 'no setup' raporlamalidir."""
    for sid in ALL_STRATEGY_IDS:
        _make_lab(monkeypatch, sid, None)
        report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
        row = next(r for r in report["strategies"] if r["strategy_id"] == sid)
        assert row["status"] not in ("SELECTED", "FILTERED_SETUP", "FILTERED_NOT_SELECTED"), (
            f"{sid}: None generator must not produce a setup, got {row['status']}"
        )
        usage = next(u for u in report["data_usage"] if u["strategy_id"] == sid)
        assert usage["setup_produced"] is False


def test_each_strategy_common_filter_rejection_is_measurable(monkeypatch):
    """Ortak filtre reddi nedeni measurable (rejection_reasons bo\u015f olmaz)."""
    for sid in ALL_STRATEGY_IDS:
        plan = _raw_plan(sid)
        _make_lab(monkeypatch, sid, plan, risk=_ineligible_risk)
        report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
        row = next(r for r in report["strategies"] if r["strategy_id"] == sid)
        assert row["status"] == "BLOCKED_COMMON_FILTER", (
            f"{sid}: expected BLOCKED_COMMON_FILTER, got {row['status']}"
        )
        assert row["rejection_stage"] == "COMMON_FILTER"
        assert row["rejection_reasons"], f"{sid}: rejection reason must be measurable"


def test_each_strategy_strategy_id_written_to_pool(monkeypatch):
    """Strateji kimliği havuza do\u011fru yaz\u0131l\u0131r (setup_id strateji ID'si ile ba\u015flar)."""
    for sid in ALL_STRATEGY_IDS:
        plan = _raw_plan(sid)
        _make_lab(monkeypatch, sid, plan, risk=_eligible_risk)
        report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
        row = next(r for r in report["strategies"] if r["strategy_id"] == sid)
        assert row["strategy_id"] == sid
        assert row["strategy"] == STRATEGY_NAMES[sid]


def test_decision_engine_is_single_authority(monkeypatch):
    """Yaln\u0131zca bir strateji SELECTED olabilir; ba\u015fka strateji karar\u0131 y\u00f6netemez."""
    plans = {sid: _raw_plan(sid) for sid in ALL_STRATEGY_IDS}
    for sid, plan in plans.items():
        _make_lab(monkeypatch, sid, plan, risk=_eligible_risk)
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
    selected = report["selected"]
    selected_flags = [r for r in report["strategies"] if r.get("selected") is True]
    assert len(selected_flags) <= 1, "Only one strategy may be selected"
    if selected is not None:
        assert selected["status"] == "SELECTED"
        assert report["diagnostics"]["selected_strategy_id"] == selected["strategy_id"]
        assert selected["strategy_id"] in ALL_STRATEGY_IDS


def test_all_five_strategies_independent_registry():
    """Yedi strateji ba\u015f\u0131ms\u0131r, ortak analiz servisleri kullanmadan kendi setup'ini \u00fcreter."""
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
    ids = {r["strategy_id"] for r in report["strategies"]}
    assert ids == ALL_STRATEGY_IDS
    assert report["diagnostics"]["strategy_count"] == 5
    for row in report["strategies"]:
        assert row["strategy_id"] in ALL_STRATEGY_IDS
        assert row["strategy"] == STRATEGY_NAMES[row["strategy_id"]]
        # Her strateji kendi data_usage raporuna sahip olmalidir.
        usage = next(u for u in report["data_usage"] if u["strategy_id"] == row["strategy_id"])
        assert usage["strategy_id"] == row["strategy_id"]
