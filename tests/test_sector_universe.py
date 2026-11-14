import json

from sector_universe import configured_sector_peers


def test_sector_peers_are_configurable_and_deduplicated(monkeypatch):
    monkeypatch.setenv("ATLAS_SECTOR_PEERS_JSON", json.dumps({
        "SOL": ["AVAX/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT"]
    }))
    assert configured_sector_peers("SOL/USDT:USDT") == [
        "AVAX/USDT:USDT", "ADA/USDT:USDT"
    ]


def test_unknown_or_invalid_sector_mapping_fails_closed(monkeypatch):
    monkeypatch.setenv("ATLAS_SECTOR_PEERS_JSON", "{invalid")
    assert configured_sector_peers("SOL/USDT:USDT") == []
    monkeypatch.setenv("ATLAS_SECTOR_PEERS_JSON", json.dumps({"BTC": ["BTC/USDT:USDT"]}))
    assert configured_sector_peers("BTC/USDT:USDT") == []
