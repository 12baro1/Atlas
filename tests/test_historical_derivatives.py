import historical_derivatives


class FakeExchange:
    def fetch_open_interest_history(self, symbol, **kwargs):
        return [
            {"timestamp": 1_700_000_000_000, "openInterestValue": "100"},
            {"timestamp": 1_700_003_600_000, "openInterestValue": "90"},
        ]

    def fetch_funding_rate_history(self, symbol, **kwargs):
        return [
            {"timestamp": 1_700_000_000_000, "fundingRate": "0.0001"},
            {"timestamp": 1_700_028_800_000, "fundingRate": "-0.0002"},
        ]


def test_historical_derivatives_are_timestamped_and_sorted(monkeypatch):
    monkeypatch.setattr(historical_derivatives, "exchange", FakeExchange())
    result = historical_derivatives.load_historical_derivatives(
        "BTC/USDT:USDT", 1_700_000_000_000, 1_700_010_000_000
    )
    assert result["open_interest_records"] == [
        {"timestamp": 1_700_000_000_000, "value": 100.0},
        {"timestamp": 1_700_003_600_000, "value": 90.0},
    ]
    assert result["funding_records"] == [
        {"timestamp": 1_700_000_000_000, "value": 0.0001}
    ]
    assert result["derivatives_data_quality"]["funding"] == "HISTORICAL"


def test_unsupported_derivatives_endpoints_are_explicit(monkeypatch):
    monkeypatch.setattr(historical_derivatives, "exchange", object())
    result = historical_derivatives.load_historical_derivatives(
        "BTC/USDT:USDT", 1_700_000_000_000, 1_700_010_000_000
    )
    assert result["open_interest_records"] == []
    assert result["funding_records"] == []
    assert result["derivatives_data_quality"] == {
        "open_interest": "UNSUPPORTED",
        "funding": "UNSUPPORTED",
    }
