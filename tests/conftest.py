"""Test yardımcıları: üretim dışı ortam izolasyonu.

AtlasEngine() her kurulduğunda Config.TRADE_JOURNAL_DB_FILE varsayılanı olan
production atlas_journal.db (10K+ snapshot JSON) belleğe yükleniyor ve 20-30
saniyelik bir darboğaz yaratıyordu. Bu conftest, her test için journal DB'sini
geçici bir dosyaya yönlendirerek üretim verisine dokunmadan testlerin hızlı
ve kararlı çalışmasını sağlar.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_journal_db(monkeypatch):
    """Config.TRADE_JOURNAL_DB_FILE'i test başına taze bir temp dosyaya yönlendir."""
    import config as config_module

    tmp_db = os.path.join(tempfile.mkdtemp(prefix="atlas_test_"), "journal.sqlite")
    monkeypatch.setattr(config_module.Config, "TRADE_JOURNAL_DB_FILE", tmp_db, raising=False)
    monkeypatch.setattr(config_module.Config, "SIGNAL_TRACKING_ENABLED", True, raising=False)