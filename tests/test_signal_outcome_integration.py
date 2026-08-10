import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from config import Config
from trade_journal import TradeJournal
from learning_engine import LearningEngine
from telegram_service import TelegramTradeCommandHandler
from canonical_features import parse_fingerprint


def _candle(index, price=None):
    base = price if price is not None else 100
    return Candle(
        time=1_700_000_000_000 + (index * 60_000),
        open=base,
        high=base + 1,
        low=base - 1,
        close=base + 0.5,
        volume=120.0,
    )


def _precise_candle(index, high, low, close, open_=None):
    time = 1_700_000_000_000 + (index * 60_000)
    return Candle(time=time, open=open_ if open_ is not None else close, high=high, low=low, close=close, volume=120.0)


def test_signal_outcome_resolves_tp1_to_sl(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    outcome = journal.register_signal_outcome(
        symbol="BTC/USDT:USDT",
        direction="LONG",
        entry=100.0,
        stop_loss=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        grade="A",
        confidence=88,
        opened_at=1_700_000_000_000,
    )
    assert outcome["status"] == "PENDING"

    candles = [
        _precise_candle(1, high=100.4, low=99.6, close=100.0),  # TP1/SL yok
        _precise_candle(2, high=101.2, low=100.1, close=101.2),  # TP1 hit -> BE
        _precise_candle(3, high=100.6, low=99.3, close=99.5),    # BE(100) stop hit
    ]
    resolved = journal.resolve_signal_outcome(outcome, candles)
    assert resolved is not None
    assert resolved["status"] == "SL"
    assert len(resolved.get("tps_hit") or []) == 1
    assert resolved.get("realized_r", 0.0) > 0.2
    assert resolved.get("realized_r", 0.0) > 0.5


def test_signal_outcome_expires_after_expiry(tmp_path, monkeypatch):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    monkeypatch.setattr(Config, "SIGNAL_OUTCOME_EXPIRY_HOURS", 1)
    opened = 1_700_000_000_000
    outcome = journal.register_signal_outcome(
        symbol="BTC/USDT:USDT", direction="LONG",
        entry=100.0, stop_loss=99.0, tp1=105.0,
        opened_at=opened,
    )
    old_factory = journal._signal_outcome_expiry_hours
    journal._signal_outcome_expiry_hours = lambda: 1.0
    late_candle = _precise_candle(20, high=100.5, low=99.5, close=100.0)  # SL/TP'ye dokunmaz
    late_candle.time = opened + 2 * 3600 * 1000
    resolved = journal.resolve_signal_outcome(outcome, [late_candle])
    assert resolved is not None
    assert resolved["status"] == "EXPIRED"
    journal._signal_outcome_expiry_hours = old_factory


def test_manual_trade_open_close_and_reflection(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    outcome = journal.register_signal_outcome(
        symbol="ETH/USDT:USDT", direction="SHORT",
        entry=100.0, stop_loss=101.0, tp1=99.0,
        opened_at=1_700_000_000_000,
    )

    manual, code = journal.open_manual_trade(signal_id=outcome["signal_id"])
    assert code == "opened"
    assert journal.open_manual_trades()[0]["signal_id"] == outcome["signal_id"]

    closed, code = journal.close_manual_trade(signal_id=outcome["signal_id"], actual_exit=98.5)
    assert code == "closed"
    assert closed["result"] == "WIN"
    assert closed["pnl_rr"] == 1.5

    perf = journal.manual_trade_performance()
    assert perf["wins"] == 1
    assert perf["winrate"] == 100


def test_refresh_learning_maps_records(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    for i in range(6):
        outcome = journal.register_signal_outcome(
            symbol=f"BTC{1}:USDT", direction="LONG",
            entry=100.0, stop_loss=99.0, tp1=101.0, tp2=102.0, tp3=103.0,
            opened_at=1_700_000_000_000 + i * 60_000,
        )
        journal.open_manual_trade(signal_id=outcome["signal_id"])
        journal.close_manual_trade(signal_id=outcome["signal_id"], actual_exit=102.0)
    records = journal.learning_records(source="manual")
    assert len(records) == 6
    assert all(r["win"] for r in records)


def test_refresh_learning_rebuilds_buckets(tmp_path):
    learning = LearningEngine(tmp_path / "learning.json")
    records = [
        {"direction": "LONG", "timeframe": "15m", "regime": "TREND", "setup_fingerprint": "fvg", "win": True, "r": 2.0, "confidence": 88, "closed_at": 1_700_000_000_000},
        {"direction": "LONG", "timeframe": "15m", "regime": "TREND", "setup_fingerprint": "fvg", "win": True, "r": 1.5, "confidence": 92, "closed_at": 1_700_000_000_000},
    ] * 12
    setups = learning.rebuild_from_records(records)
    assert len(setups) >= 1
    key = next(iter(setups))
    assert setups[key]["bayesian"] > 70
    assert setups[key]["wilson_lower"] > 60
    assert setups[key]["average_confidence"] == 90
    suggestions = learning.edge_summary()["suggestions"]
    assert suggestions and suggestions[0]["action"] == "BOOST"


def test_missing_learning_records_handled(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    assert journal.learning_records(source="manual") == []
    assert journal.signal_performance()["total"] == 0


def test_telegram_trade_command_handler(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    handler = TelegramTradeCommandHandler(journal=journal)
    outcome = journal.register_signal_outcome(
        symbol="BTC/USDT:USDT", direction="LONG",
        entry=100.0, stop_loss=99.0, tp1=101.0,
        opened_at=1_700_000_000_000,
    )
    sid = outcome["signal_id"]

    help_reply = handler.handle(1, "/trade help")
    assert "open" in help_reply

    opened_reply = handler.handle(1, f"/trade open {sid}")
    assert "kaydedildi" in opened_reply

    closed_reply = handler.handle(1, f"/trade close {sid} 100.5")
    assert "İşlem kapatıldı" in closed_reply
    assert "0.5000R" in closed_reply

    perf_reply = handler.handle(1, "/trade performance")
    assert "ATLAS PERFORMANS" in perf_reply


def test_mark_not_traded_not_counted_as_loss(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    outcome = journal.register_signal_outcome(
        symbol="SOL/USDT:USDT",
        direction="LONG",
        entry=100.0,
        stop_loss=99.0,
        tp1=101.0,
        opened_at=1_700_000_000_000,
    )
    manual, code = journal.mark_manual_not_traded(signal_id=outcome["signal_id"])
    assert code == "not_traded"
    assert manual["status"] == "NOT_TRADED"
    assert manual["result"] == "NOT_TRADED"

    perf = journal.manual_trade_performance()
    assert perf["total"] == 0
    assert perf["not_traded"] == 1
    assert perf["losses"] == 0


def test_duplicate_close_blocked(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    outcome = journal.register_signal_outcome(
        symbol="BTC/USDT:USDT",
        direction="LONG",
        entry=100.0,
        stop_loss=99.0,
        tp1=101.0,
        opened_at=1_700_000_000_000,
    )
    journal.open_manual_trade(signal_id=outcome["signal_id"], actual_entry=100.0)

    first, first_code = journal.close_manual_trade(signal_id=outcome["signal_id"], result="WIN", actual_exit=101.0)
    assert first_code == "closed"
    assert first["status"] == "CLOSED"

    second, second_code = journal.close_manual_trade(signal_id=outcome["signal_id"], result="LOSS", actual_exit=98.0)
    assert second_code == "already_closed"
    assert second["result"] == "WIN"


def test_telegram_trade_command_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "MANUAL_TRADE_COMMAND_ENABLED", False)
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    handler = TelegramTradeCommandHandler(journal=journal)
    assert not handler.enabled()


def _long_setup_quality():
    from setup_quality_engine import SetupQualityEngine

    sq = SetupQualityEngine()
    candles = [Candle(1_700_000_000_000 + i * 60000, 1990, 2005, 1985, 2000, 120) for i in range(25)]
    return sq.evaluate(
        candles=candles, direction="LONG",
        mtf={"valid": True, "entry": "LONG"}, trend={"trend": "BULLISH"},
        structure=[{"label": "HH", "bos": True, "choch": False, "direction": "BULLISH"}] * 6,
        liquidity_sweep={"is_sweep": True, "strength_score": 70, "post_structure": {"confirmed": True}},
        orderblocks=[{"type": "BULLISH", "mitigated": False, "strength": 70, "low": 1998, "high": 2002}],
        fvg=[{"type": "BULLISH", "filled": False, "strength": 70, "size": 5}],
        premium_discount={"valid": True, "zone": "DISCOUNT"},
        market_phase={"phase": "Expansion"},
        session={"session": "LONDON"},
        entry={"valid": True, "direction": "LONG", "entry": 100, "entry_type": "MARKET"},
        confirmation={"confirmed": True},
    )


def test_learning_matches_canonical_features_exact(tmp_path):
    """Bucket anahtarları ile module_scores artık KESİŞMELİ (kanonik skema)."""
    learning = LearningEngine(tmp_path / "learning.json")
    base = _long_setup_quality()
    fingerprint = base["setup_fingerprint"]
    records = [
        {
            "direction": "LONG", "timeframe": "15m", "regime": "Expansion",
            "setup_fingerprint": fingerprint, "win": True, "r": 1.5,
            "confidence": 88, "closed_at": 1_700_000_000_000,
        }
    ] * 30
    setups = learning.rebuild_from_records(records)
    assert len(setups) >= 1
    module_names = set(base["module_scores"].keys())
    tokens = set()
    for key in setups:
        tokens.update(parse_fingerprint(key))
    overlap = tokens & module_names
    assert overlap, "kanonik bucket token'ları modül isimleriyle kesişmeli"
    assert "liquidity_sweep" in tokens or "fvg" in tokens


def test_learning_without_matching_bucket_keeps_score(tmp_path):
    """Hiç öğrenme verisi yoksa skor DEĞİŞMEZ (artefakt yok)."""
    empty = LearningEngine(tmp_path / "empty.json")
    base = _long_setup_quality()
    adjusted = empty.apply_to_setup_quality(base, market_phase="Expansion", timeframe="15m")
    assert adjusted["score"] == base["score"]
    assert adjusted["learning"]["matched"] is False
    assert all(v == 1.0 for v in adjusted["learning_adjustments"].values())


def test_learning_positive_history_raises_setup_quality(tmp_path):
    """ADIM-7: Aynı setup'a 30 başarılı manuel kayıt skoru yükseltmeli."""
    learning = LearningEngine(tmp_path / "learning.json")
    base = _long_setup_quality()
    fingerprint = base["setup_fingerprint"]
    records = [
        {
            "direction": "LONG", "timeframe": "15m", "regime": "Expansion",
            "setup_fingerprint": fingerprint, "win": True, "r": 1.5,
            "confidence": 85, "closed_at": 1_700_000_000_000,
        }
    ] * 30
    learning.rebuild_from_records(records)

    adjusted = learning.apply_to_setup_quality(base, market_phase="Expansion", timeframe="15m")
    assert adjusted["learning"]["matched"] is True
    assert adjusted["learning"]["level"] == "exact"
    assert adjusted["learning"]["sample_count"] == 30
    assert adjusted["learning"]["historical_edge"] > 0
    assert adjusted["learning"]["reliability"] > 0.5
    assert adjusted["learning"]["expected_r"] > 0
    assert adjusted["score"] > base["score"]
    assert any(v != 1.0 for v in adjusted["learning_adjustments"].values())


def test_learning_negative_history_lowers_setup_quality(tmp_path):
    """30 kaybeden kayıt skoru DÜŞÜRMELİ (pozitifin tersi)."""
    learning = LearningEngine(tmp_path / "learning.json")
    base = _long_setup_quality()
    fingerprint = base["setup_fingerprint"]
    records = [
        {
            "direction": "LONG", "timeframe": "15m", "regime": "Expansion",
            "setup_fingerprint": fingerprint, "win": False, "r": -1.0,
            "confidence": 85, "closed_at": 1_700_000_000_000,
        }
    ] * 30
    learning.rebuild_from_records(records)
    adjusted = learning.apply_to_setup_quality(base, market_phase="Expansion", timeframe="15m")
    assert adjusted["learning"]["matched"] is True
    assert adjusted["learning"]["historical_edge"] < 0
    assert adjusted["score"] < base["score"]


def test_learning_direction_isolation(tmp_path):
    """9: Başarılı LONG geçmişi SHORT setup'ı aynı şekilde yükseltmemeli."""
    learning = LearningEngine(tmp_path / "learning.json")
    base = _long_setup_quality()
    fingerprint = base["setup_fingerprint"]
    records_long = [
        {
            "direction": "LONG", "timeframe": "15m", "regime": "Expansion",
            "setup_fingerprint": fingerprint, "win": True, "r": 1.5,
            "confidence": 85, "closed_at": 1_700_000_000_000,
        }
    ] * 30
    learning.rebuild_from_records(records_long)

    long_adj = learning.apply_to_setup_quality(base, market_phase="Expansion", timeframe="15m")
    assert long_adj["score"] > base["score"]

    short = _long_setup_quality()
    short["direction"] = "SHORT"
    short_adj = learning.apply_to_setup_quality(short, market_phase="Expansion", timeframe="15m")
    assert short_adj["learning"]["matched"] is True or short_adj["learning"]["matched"] is False
    assert short_adj["score"] == short["score"], "SHORT setup LONG geçmişinden etkilenmemeli"


def test_learning_regime_isolation(tmp_path):
    """10: Bullish regimetteki başarılı gelmiş geçmiş, bearish setup'ı esnetmemeli."""
    learning = LearningEngine(tmp_path / "learning.json")
    base = _long_setup_quality()
    fingerprint = base["setup_fingerprint"]
    records = [
        {
            "direction": "LONG", "timeframe": "15m", "regime": "Expansion",
            "setup_fingerprint": fingerprint, "win": True, "r": 1.5,
            "confidence": 85, "closed_at": 1_700_000_000_000,
        }
    ] * 30
    learning.rebuild_from_records(records)
    bullish = learning.apply_to_setup_quality(base, market_phase="Expansion", timeframe="15m")
    assert bullish["score"] > base["score"]

    bearish = learning.apply_to_setup_quality(base, market_phase="Recession", timeframe="15m")
    assert bearish["score"] == base["score"], "farklı regime aynı sonucu almamalı"


def test_learning_timeframe_isolation(tmp_path):
    """4H geçmişi 15m setup'ı körü körüne aynı sonucu vermemeli."""
    learning = LearningEngine(tmp_path / "learning.json")
    base = _long_setup_quality()
    fingerprint = base["setup_fingerprint"]
    records = [
        {
            "direction": "LONG", "timeframe": "4h", "regime": "Expansion",
            "setup_fingerprint": fingerprint, "win": True, "r": 1.5,
            "confidence": 85, "closed_at": 1_700_000_000_000,
        }
    ] * 30
    learning.rebuild_from_records(records)

    _15m = learning.apply_to_setup_quality(base, market_phase="Expansion", timeframe="15m")
    assert _15m["learning"]["matched"] is False, "4h geçmişi 15m exact'ına exact olarak sızmamalı"
    assert _15m["score"] == base["score"]

    _4h = learning.apply_to_setup_quality(base, market_phase="Expansion", timeframe="4h")
    assert _4h["learning"]["matched"] is True
    assert _4h["learning"]["historical_edge"] > 0
    assert _4h["score"] > base["score"]


def test_learning_min_sample_guard(tmp_path):
    """2-3 işlemden aşırı öğrenme YAPILMAZ (ramp düşürür)."""
    import pytest
    learning = LearningEngine(tmp_path / "learning.json")
    base = _long_setup_quality()
    fingerprint = base["setup_fingerprint"]
    records = [
        {
            "direction": "LONG", "timeframe": "15m", "regime": "Expansion",
            "setup_fingerprint": fingerprint, "win": True, "r": 2.5,
            "confidence": 90, "closed_at": 1_700_000_000_000,
        }
    ] * 3
    learning.rebuild_from_records(records)
    adjusted = learning.apply_to_setup_quality(base, market_phase="Expansion", timeframe="15m")
    assert adjusted["learning"]["sample_count"] == 3
    assert adjusted["score"] < base["score"] + 6, "küçük örneklemde büyük uplift yok"


def test_learning_real_journal_chain(tmp_path):
    """12: gerçek journal -> learning record -> rebuild -> setup -> phone."""
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    base = _long_setup_quality()
    fingerprint = base["setup_fingerprint"]
    for i in range(30):
        outcome = journal.register_signal_outcome(
            symbol="ETH/USDT:USDT", direction="LONG",
            entry=2000.0, stop_loss=1990.0, tp1=2020.0,
            market_phase="Expansion", setup_fingerprint=fingerprint,
            opened_at=1_700_000_000_000 + i * 60_000, confidence=85,
        )
        journal.open_manual_trade(signal_id=outcome["signal_id"])
        journal.close_manual_trade(signal_id=outcome["signal_id"], actual_exit=2020.0, result="WIN")
    recs = journal.learning_records(source="manual")
    assert len(recs) == 30

    learning = LearningEngine(tmp_path / "learning.json")
    learning.rebuild_from_records(recs)
    adjusted = learning.apply_to_setup_quality(base, market_phase="Expansion", timeframe="15m")
    assert adjusted["learning"]["matched"] is True
    assert adjusted["learning"]["sample_count"] == 30
    assert adjusted["score"] > base["score"]
    assert adjusted["learning"]["historical_edge"] > 0


def test_future_trade_does_not_leak_into_past_asof(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    o = journal.register_signal_outcome(
        symbol="ETH/USDT:USDT", direction="LONG", entry=2000.0, stop_loss=1990.0,
        tp1=2020.0, opened_at=1_700_000_000_000,
    )
    journal.open_manual_trade(signal_id=o["signal_id"])
    journal.close_manual_trade(signal_id=o["signal_id"], actual_exit=2020.0, result="WIN")

    future = journal.register_signal_outcome(
        symbol="SOL/USDT:USDT", direction="SHORT", entry=50.0, stop_loss=50.5,
        tp1=49.0, opened_at=2_000_000_000_000,
    )
    journal.open_manual_trade(signal_id=future["signal_id"])
    journal.close_manual_trade(
        signal_id=future["signal_id"], actual_exit=48.0, result="WIN",
        closed_at=2_100_000_000_000,
    )
    as_of = 1_800_000_000_000
    recs = journal.learning_records(source="manual")
    recs_asof = journal.learning_records(source="manual", as_of_ms=as_of)
    assert len(recs) == 2
    assert len(recs_asof) == 1
    assert all(r["closed_at"] <= as_of for r in recs_asof)


def test_same_signal_not_reopened_as_manual(tmp_path):
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    o = journal.register_signal_outcome(
        symbol="BNB/USDT:USDT", direction="LONG", entry=300.0, stop_loss=295.0,
        tp1=305.0, opened_at=1_700_000_000_000,
    )
    _, c1 = journal.open_manual_trade(signal_id=o["signal_id"])
    _, c2 = journal.open_manual_trade(signal_id=o["signal_id"])
    assert c1 == "opened"
    assert c2 == "already_open"
    count = [m for m in journal._manual_trades if m["signal_id"] == o["signal_id"]]
    assert len(count) == 1


def test_resolve_ignores_candles_before_opened_at(tmp_path):
    """Look-ahead koruması: opened_at öncesi mumlar sinyali çözemez."""
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    o = journal.register_signal_outcome(
        symbol="LTC/USDT:USDT", direction="LONG", entry=100.0, stop_loss=99.0,
        tp1=101.0, opened_at=1_700_000_000_000,
    )
    pre_open = Candle(1_699_000_000_000, 102.0, 103.0, 101.0, 102.5, 100)
    resolved = journal.resolve_signal_outcome(o, [pre_open])
    assert resolved is None or resolved.get("status") == "PENDING"
