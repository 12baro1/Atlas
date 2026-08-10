"""Canlı öğrenme zinciri regression testleri.

Kapsam:
- TradeJournal.learning_records(source="tracked"): gerçek kapanan (scanner)
  işlem kayıtlarından kanonik feature/fingerprint çıkarımı.
- AtlasEngine.refresh_learning(): kaynak önceliği manual -> tracked -> signal.
- Learning index'in eşleşmesi (match) ve look-ahead guard'ı.
- ManualTradeQualityGate'in learning bileşeni (skorun 100'e yapışmaması).
- SignalEngine payload'ının learning meta taşıması.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canonical_features import build_fingerprint
from config import Config
from engine import AtlasEngine
from learning_engine import LearningEngine
from manual_trade_quality import ManualTradeQualityGate
from signal_engine import SignalEngine
from trade_journal import TradeJournal

FEATURES = ["fvg", "order_block", "market_structure"]


def _setup_quality(features, score=80, direction="LONG"):
    module_scores = {
        feature: {"score": 95, "reason": "x"}
        for feature in features
    }
    return {
        "active": True,
        "direction": direction,
        "score": score,
        "confidence": score,
        "module_scores": module_scores,
        "features": list(features),
        "setup_fingerprint": build_fingerprint(features),
        "blockers": [],
        "reasons": [],
        "trade_allowed": True,
    }


def _result_payload(side, features=FEATURES, confidence=92, phase="Expansion"):
    setup = _setup_quality(features)
    return {
        "symbol": "BTC/USDT:USDT",
        "analysis": {
            "signal": {"signal": side, "confidence": confidence, "grade": "A+"},
            "market_phase": {"phase": phase},
            "setup_quality": setup,
            "setup": {"fingerprint": setup["setup_fingerprint"], "type": "canonical"},
        },
        "signal": {"signal": side, "confidence": confidence, "grade": "A+"},
        "risk": {"entry": 100, "stop_loss": 99, "tp1": 103, "tp3": 109},
        "rr": {"rr": 3.0},
        "decision": {"action": "EXECUTE"},
    }


def _journal_with_closed_trades():
    journal = TradeJournal()
    for index, (pnl_rr, result) in enumerate([(2.0, "WIN"), (1.5, "WIN"), (-1.0, "LOSS")], start=1):
        trade = journal.register_trade(
            {"symbol": "BTC/USDT:USDT", "side": "LONG", "entry": 100, "stop_loss": 99, "rr": 3},
            analysis=_result_payload("LONG"),
            symbol="BTC/USDT:USDT",
            timestamp=index * 1000,
        )
        journal.close_trade(
            trade["id"],
            exit_price=103.0 if pnl_rr > 0 else 99.0,
            result=result,
            timestamp=index * 1000 + 500,
        )
        trade["pnl_rr"] = pnl_rr
    return journal


def _learning_engine(tmp_path):
    return LearningEngine(str(tmp_path / "learning.json"))


def test_tracked_learning_records_extract_canonical_features():
    journal = _journal_with_closed_trades()
    records = journal.learning_records(source="tracked")

    assert len(records) == 3
    record = records[0]
    assert record["source"] == "tracked"
    assert set(record["features"]) == set(FEATURES)
    assert record["setup_fingerprint"] == build_fingerprint(FEATURES)
    assert record["direction"] == "LONG"
    assert record["win"] is True
    assert record["r"] == 2.0
    assert record["regime"] == "Expansion"
    assert record["closed_at"] > record["opened_at"]


def test_tracked_learning_records_fallback_module_scores():
    payload = _result_payload("LONG")
    payload["analysis"]["setup_quality"].pop("setup_fingerprint")
    payload["analysis"]["setup_quality"].pop("features")
    journal = TradeJournal()
    trade = journal.register_trade(
        {"symbol": "BTC/USDT:USDT", "side": "LONG", "entry": 100, "stop_loss": 99},
        analysis=payload,
        symbol="BTC/USDT:USDT",
        timestamp=1000,
    )
    journal.close_trade(trade["id"], exit_price=110.0, result="WIN", timestamp=2000)
    trade["pnl_rr"] = 3.0

    records = journal.learning_records(source="tracked")
    assert len(records) == 1
    assert set(records[0]["features"]) == set(FEATURES)


def test_tracked_learning_records_lookahead_guard():
    journal = _journal_with_closed_trades()
    closed_at = journal._trades[0]["closed_at"]
    records_after = journal.learning_records(source="tracked", as_of_ms=closed_at + 1)
    assert records_after
    records_before = journal.learning_records(source="tracked", as_of_ms=closed_at - 1)
    assert records_before == []


def test_refresh_learning_prefers_tracked_over_signal(tmp_path):
    journal = _journal_with_closed_trades()
    engine = AtlasEngine()
    engine.trade_journal = journal
    engine.learning = _learning_engine(tmp_path)

    result = engine.refresh_learning()
    assert result is not None
    assert engine.learning.stats["feed_meta"]["selected"] == "tracked"
    assert engine.learning.stats["feed_meta"]["manual"] == 0
    index = engine.learning.stats["index"]
    assert index.get("exact") or index.get("family")


def test_refresh_learning_falls_back_to_signal(tmp_path):
    journal = TradeJournal()
    journal.register_signal_outcome(
        symbol="BTC/USDT:USDT", direction="LONG", entry=100, stop_loss=99,
        opened_at=1000, setup_fingerprint=build_fingerprint(FEATURES),
        market_phase="Expansion",
    )
    outcome = journal._signal_outcomes[0]
    outcome["status"] = "CLOSED"
    outcome["resolved_at"] = 2000
    outcome["final_result"] = "WIN"
    outcome["realized_r"] = 2.0
    outcome["payload"] = {"setup_features": list(FEATURES)}
    engine = AtlasEngine()
    engine.trade_journal = journal
    engine.learning = _learning_engine(tmp_path)

    engine.refresh_learning()
    assert engine.learning.stats["feed_meta"]["selected"] == "signal"


def test_refresh_learning_prefers_manual(tmp_path):
    journal = TradeJournal()
    journal._manual_trades.append(
        {
            "status": "CLOSED", "side": "LONG", "symbol": "BTC/USDT:USDT",
            "opened_at": 1000, "closed_at": 2000, "result": "WIN",
            "pnl_rr": 2.0, "regime": "Expansion", "grade": "A+",
            "confidence": 90, "setup_fingerprint": "fvg|order_block", "payload": {},
        }
    )
    engine = AtlasEngine()
    engine.trade_journal = journal
    engine.learning = _learning_engine(tmp_path)

    engine.refresh_learning()
    assert engine.learning.stats["feed_meta"]["selected"] == "manual"


def test_live_match_with_learned_fingerprint(tmp_path):
    journal = _journal_with_closed_trades()
    engine = AtlasEngine()
    engine.trade_journal = journal
    engine.learning = _learning_engine(tmp_path)
    engine.refresh_learning()

    setup = _setup_quality(features=FEATURES)
    adjusted = engine.learning.apply_to_setup_quality(setup, market_phase="Expansion", timeframe="15m")

    assert adjusted["learning"]["matched"] is True
    assert adjusted["learning"]["sample_count"] == 3
    assert adjusted["learning"]["score_delta"] >= 0
    assert adjusted["score"] >= setup["score"]


def test_match_isolated_across_contexts(tmp_path):
    journal = _journal_with_closed_trades()
    engine = AtlasEngine()
    engine.trade_journal = journal
    engine.learning = _learning_engine(tmp_path)
    engine.refresh_learning()

    setup = _setup_quality(features=FEATURES)
    applied = engine.learning.apply_to_setup_quality(setup, market_phase="Manipulation", timeframe="15m")
    assert applied["learning"]["matched"] is False


def test_signal_payload_carries_learning_meta():
    analysis = {
        "confluence": {"score": 85, "checks": []},
        "entry": {"direction": "LONG", "valid": True},
        "confirmation": {"confirmed": True},
        "market_phase": {"phase": "Expansion", "phase_confidence": 80, "phase_score": 75, "mtf_alignment": 80},
        "setup_quality": {
            "active": True,
            "score": 80,
            "trade_allowed": True,
            "reasons": [],
            "learning": {"matched": True, "score_delta": 4, "sample_count": 21},
        },
    }
    payload = SignalEngine().generate(analysis)
    assert payload["learning"]["matched"] is True
    assert payload["learning"]["score_delta"] == 4


def test_manual_score_not_always_100():
    gate = ManualTradeQualityGate(Config)
    base = dict(
        symbol="BTC/USDT:USDT",
        signal={"signal": "LONG", "confidence": 95, "grade": "A+"},
        entry={"valid": True, "direction": "LONG", "entry": 100, "stop_loss": 99},
        risk={"selected_rr": 4.0, "risk": 1},
        decision={"action": "EXECUTE", "score": 90, "risk_valid": True},
        confluence={"score": 90},
        market_phase={"phase": "Expansion"},
        trade_journal=None,
    )
    no_learning = gate.evaluate(**base)
    assert 75 <= no_learning["score"] < 100

    with_learning = gate.evaluate(
        **{**base, "signal": {**base["signal"], "learning": {"matched": True, "score_delta": 6}}}
    )
    assert with_learning["components"]["learning"] == 3
    assert with_learning["score"] == no_learning["score"] + 3
    assert with_learning["learning"]["matched"] is True


def test_manual_learning_penalty_capped():
    gate = ManualTradeQualityGate(Config)
    base = dict(
        symbol="BTC/USDT:USDT",
        signal={
            "signal": "LONG", "confidence": 95, "grade": "A+",
            "learning": {"matched": True, "score_delta": -10},
        },
        entry={"valid": True, "direction": "LONG", "entry": 100, "stop_loss": 99},
        risk={"selected_rr": 4.0, "risk": 1},
        decision={"action": "EXECUTE", "score": 90, "risk_valid": True},
        confluence={"score": 90},
        market_phase={"phase": "Expansion"},
        trade_journal=None,
    )
    result = gate.evaluate(**base)
    assert result["components"]["learning"] == -5
    assert result["score"] >= 0


# ----------------------------------------------------------------------
# Regression: legacy index rebuild, cache-hit, real-DB CASE A/B
# ----------------------------------------------------------------------


def test_load_legacy_file_rebuilds_index(tmp_path):
    """'index' anahtarı olmayan eski format setups dosyasından index kurulmalı."""
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({
        "setups": {
            "Expansion|15m|LONG|fvg|ob": {
                "total": 5, "wins": 4, "winrate": 80.0, "bayesian": 60.0,
                "wilson_lower": 35.0, "average_r": 2.0, "edge": 2.0, "weight": 1.0,
            },
            "SHORT|Trending|15M|liquidity_sweep|order_block|fvg": {
                "total": 3, "wins": 1, "winrate": 33.33, "bayesian": 37.5,
                "wilson_lower": 8.0, "average_r": -0.5, "edge": -0.5, "weight": 1.0,
            },
        },
        "meta": {"records_fed": 8, "buckets": 2},
    }), encoding="utf-8")

    engine = LearningEngine(str(path))
    assert engine.stats["index"], "legacy setups'tan index olusturulmali"
    levels = engine.stats["index"]
    exact_keys = list(levels.get("exact", {}).keys())
    assert any(key.startswith("LONG|EXPANSION|15M|") for key in exact_keys)
    assert any(key.startswith("SHORT|TRENDING|15M|") for key in exact_keys)

    ctx = engine._match_context(
        _setup_quality(features=["fvg", "order_block"]),
        market_phase="Expansion",
        timeframe="15m",
    )
    candidate_keys = engine._candidate_keys(ctx)
    assert candidate_keys[0] == ("exact", "LONG|EXPANSION|15M|fvg|order_block")


def test_no_match_reason_exposed(tmp_path):
    """Index boşken matched=False'in nedeni açıkça raporlanmalı."""
    engine = _learning_engine(tmp_path)
    adjusted = engine.apply_to_setup_quality(
        _setup_quality(features=FEATURES),
        market_phase="Expansion",
        timeframe="15m",
    )
    assert adjusted["learning"]["matched"] is False
    assert "learning index yok" in adjusted["learning"]["no_match_reason"]


def test_manual_learning_record_timeframe():
    """Manuel trade kaydının timeframe alanı öğrenme kaydına geçmeli."""
    journal = TradeJournal()
    journal._manual_trades.append(
        {
            "id": "manual-1", "status": "CLOSED", "side": "LONG",
            "symbol": "BTC/USDT:USDT", "opened_at": 1000, "closed_at": 2000,
            "result": "WIN", "pnl_rr": 2.0, "regime": "Expansion",
            "timeframe": "1h", "payload": {},
            "setup_fingerprint": build_fingerprint(FEATURES),
        }
    )
    records = journal.learning_records(source="manual")
    assert len(records) == 1
    assert records[0]["timeframe"] == "1h"
    assert set(records[0]["features"]) == set(FEATURES)


def test_cache_hit_reapplies_learning(tmp_path):
    """Incremental cache'ten dönen analize güncel learning yeniden uygulanmalı."""
    journal = _journal_with_closed_trades()
    engine = AtlasEngine()
    engine.trade_journal = journal
    engine.learning = _learning_engine(tmp_path)
    engine.refresh_learning()

    cached_analysis = {
        "setup_quality": _setup_quality(features=FEATURES),
        "signal": {"signal": "LONG", "confidence": 88},
        "market_phase": {"phase": "Expansion"},
    }
    engine._reapply_learning_to_cached(cached_analysis)

    sq = cached_analysis["setup_quality"]
    assert sq["learning"]["matched"] is True
    assert cached_analysis["signal"]["learning"]["matched"] is True


def test_manual_score_perfect_inputs_never_100():
    """Mükemmel bileşen değerleriyle bile skor 100'e yapışmamalı."""
    gate = ManualTradeQualityGate(Config)
    result = gate.evaluate(**{
        "symbol": "BTC/USDT:USDT",
        "signal": {
            "signal": "LONG", "confidence": 100, "grade": "S+",
            "learning": {"matched": True, "score_delta": 6, "sample_count": 30},
        },
        "entry": {"valid": True, "direction": "LONG", "entry": 100, "stop_loss": 99},
        "risk": {"selected_rr": 6.0, "risk": 1},
        "decision": {"action": "EXECUTE", "score": 100, "risk_valid": True},
        "confluence": {"score": 100},
        "market_phase": {"phase": "Expansion"},
        "trade_journal": None,
    })
    assert result["score"] < 100
    assert result["grade"] in ("A", "A+", "B")


def test_real_db_case_a_vs_case_b():
    """Gerçek atlas_journal.db kapalı kayıtlarıyla CASE A/B karşılaştırması.

    CASE A: learning uygulanmamış (saf setup_quality).
    CASE B: aynı setup'a gerçek geçmiş kapanmış işlemler üzerinden learning
    uygulanmış. Gerçek geçmişte eşleşen bucket varsa A != B olmalı.
    """
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas_journal.db")
    if not os.path.exists(db_path):
        import pytest
        pytest.skip("atlas_journal.db yok; gerçek veri entegrasyon testi atlandi")

    journal = TradeJournal(db_path=db_path)
    records = journal.learning_records(source="tracked")
    if not records:
        import pytest
        pytest.skip("gercek DB'de kapanmis trade kaydi yok")

    engine = AtlasEngine()
    engine.trade_journal = journal
    engine.refresh_learning()
    index = engine.learning.stats.get("index", {}).get("exact") or {}
    if not index:
        import pytest
        pytest.skip("gercek DB'den learning index kurulamadi")

    from collections import Counter
    feature_counter = Counter()
    for record in records:
        if record.get("features"):
            feature_counter[tuple(sorted(record["features"]))] += 1
    if not feature_counter:
        import pytest
        pytest.skip("gercek kayitlarda feature yok")

    features, count = feature_counter.most_common(1)[0]
    selected = [
        record for record in records
        if tuple(sorted(record.get("features") or [])) == features
    ]
    direction = Counter(record.get("direction", "UNKNOWN") for record in selected).most_common(1)[0][0]
    case_a = _setup_quality(features=list(features), score=80, direction=direction)
    case_b = engine.learning.apply_to_setup_quality(
        case_a,
        market_phase="Expansion",
        timeframe="15m",
    )
    assert case_b["learning"]["matched"] is True, (
        f"gercek DB'de {count} ornekli benzer setup bulundu ama matched=False: "
        f"{case_b['learning'].get('no_match_reason')}"
    )
    assert case_b["learning"]["score_delta"] != 0
    assert case_b["score"] != case_a["score"]
    assert any(value != 1.0 for value in (case_b.get("learning_adjustments") or {}).values())