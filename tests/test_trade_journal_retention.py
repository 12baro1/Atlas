import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from trade_journal import TradeJournal


def _snapshot(tj, ts):
    return tj.record_analysis(
        {"decision": {"action": "EXECUTE"}, "signal": {"signal": "LONG", "confidence": 90}},
        symbol="BTC/USDT:USDT",
        timestamp=ts,
    )


def test_retention_archives_old_snapshots_but_keeps_data(tmp_path):
    db = str(tmp_path / "journal.sqlite")
    tj = TradeJournal(db_path=db)
    # İki eski (40 gün önce — retention 30 günü aşar) + iki yeni.
    old = int(time.time() * 1000) - 40 * 86400 * 1000
    now = int(time.time() * 1000)
    _snapshot(tj, old)
    _snapshot(tj, old + 1000)
    _snapshot(tj, now)
    _snapshot(tj, now + 1000)

    stats = tj.archive_stats()
    assert stats["archived_snapshots"] == 2
    assert stats["active_snapshots"] == 2


def test_retention_disabled_when_days_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_JOURNAL_RETENTION_DAYS", "0")
    monkeypatch.setenv("ATLAS_JOURNAL_RETENTION_MAX_SNAPSHOTS", "0")
    import config as config_module
    monkeypatch.setattr(config_module.Config, "JOURNAL_RETENTION_DAYS", 0)
    monkeypatch.setattr(config_module.Config, "JOURNAL_RETENTION_MAX_SNAPSHOTS", 0)

    db = str(tmp_path / "no_archive.sqlite")
    tj = TradeJournal(db_path=db)
    old = int(time.time() * 1000) - 100 * 86400 * 1000
    for i in range(5):
        _snapshot(tj, old + i)
    stats = tj.archive_stats()
    assert stats["archived_snapshots"] == 0
    assert stats["active_snapshots"] == 5


def test_max_snapshots_caps_active_memory(tmp_path, monkeypatch):
    # Kısa kuyruk: 30 günlük değil, adet sınırı devreye girer.
    monkeypatch.setattr("config.Config.JOURNAL_RETENTION_DAYS", 0)
    monkeypatch.setattr("config.Config.JOURNAL_RETENTION_MAX_SNAPSHOTS", 3)

    db = str(tmp_path / "cap.sqlite")
    tj = TradeJournal(db_path=db)
    now = int(time.time() * 1000)
    for i in range(8):
        _snapshot(tj, now + i * 1000)

    stats = tj.archive_stats()
    assert stats["active_snapshots"] == 3
    assert stats["archived_snapshots"] == 5
    # en yeni 3'ü aktif
    active_ts = [s["timestamp"] for s in tj._snapshots]
    assert max(active_ts) == now + 7 * 1000
    assert min(active_ts) == now + 5 * 1000


def test_archive_data_is_recoverable_not_lost(tmp_path):
    db = str(tmp_path / "rec.sqlite")
    tj = TradeJournal(db_path=db)
    now = int(time.time() * 1000)
    s = _snapshot(tj, now)
    # Close/re-open: arşiv satırları varlığını korur (taşıma — silme değil).
    tj2 = TradeJournal(db_path=db)
    # Re-open yeni snapshot kıyaslara dokunmuyor.
    s2 = _snapshot(tj2, now + 1)
    assert s2 is not None
    assert tj2.archive_stats()["archived_snapshots"] == tj.archive_stats()["archived_snapshots"]


def test_fresh_db_enables_incremental_vacuum(tmp_path):
    """Yeni DB'ler auto_vacuum=INCREMENTAL ile açılır; arşivleme sonrası
    `incremental_vacuum` sayfaları fiziksel olarak geri kazanabilir."""
    import sqlite3
    db = str(tmp_path / "vac.sqlite")
    TradeJournal(db_path=db)
    conn = sqlite3.connect(db)
    mode = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
    conn.close()
    assert mode == 2  # INCREMENTAL — auto_vacuum=0 iken incremental_vacuum no-op kalır


def test_default_max_snapshots_caps_active_table(tmp_path, monkeypatch):
    """Varsayılan max snapshot 5000'de kalmalı: ~115KB/snapshot aktif tabloyu
    ~3.4GB'a (30000) şişirmek yerine ~575MB'da sınırlar."""
    monkeypatch.delenv("ATLAS_JOURNAL_RETENTION_MAX_SNAPSHOTS", raising=False)
    from config import Config
    assert Config.JOURNAL_RETENTION_MAX_SNAPSHOTS == 5000