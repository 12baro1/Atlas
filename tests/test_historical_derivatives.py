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
        "BTC/USDT:USDT", 1_700_000_000_000, 1_700_100_000_000
    )
    assert result["open_interest_records"] == [
        {"timestamp": 1_700_000_000_000, "value": 100.0},
        {"timestamp": 1_700_003_600_000, "value": 90.0},
    ]
    assert result["funding_records"] == [
        {"timestamp": 1_700_000_000_000, "value": 0.0001}
    ]
    assert result["derivatives_data_quality"]["funding"] == "PARTIAL"
    assert result["derivatives_data_quality"]["funding_coverage_pct"] < 90
    assert result["derivatives_data_quality"]["open_interest"] == "PARTIAL"


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
        "open_interest_coverage_pct": 0.0,
        "funding_coverage_pct": 0.0,
    }


class CompleteExchange:
    def fetch_open_interest_history(self, symbol, **kwargs):
        start = 1_700_000_000_000
        return [
            {"timestamp": start + hour * 3_600_000, "openInterestValue": str(100 + hour)}
            for hour in range(9)
        ]

    def fetch_funding_rate_history(self, symbol, **kwargs):
        start = 1_700_000_000_000
        return [
            {"timestamp": start, "fundingRate": "0.0001"},
            {"timestamp": start + 8 * 3_600_000, "fundingRate": "0.0002"},
        ]


def test_historical_status_requires_sufficient_timestamp_coverage(monkeypatch):
    monkeypatch.setattr(historical_derivatives, "exchange", CompleteExchange())
    start = 1_700_000_000_000
    result = historical_derivatives.load_historical_derivatives(
        "BTC/USDT:USDT", start, start + 8 * 3_600_000
    )
    assert result["derivatives_data_quality"]["open_interest"] == "HISTORICAL"
    assert result["derivatives_data_quality"]["funding"] == "HISTORICAL"
    assert result["derivatives_data_quality"]["open_interest_coverage_pct"] == 100.0
    assert result["derivatives_data_quality"]["funding_coverage_pct"] == 100.0
