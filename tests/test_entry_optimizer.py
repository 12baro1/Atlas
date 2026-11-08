from entry_optimizer import EntryOptimizer


def _entry(direction="LONG"):
    return {
        "valid": True,
        "direction": direction,
        "entry": 105.0 if direction == "LONG" else 115.0,
        "stop_loss": 95.0 if direction == "LONG" else 125.0,
        "entry_type": "LIMIT",
        "poi_zone": {"low": 100.0, "high": 110.0},
        "checks": [],
    }


def test_aligned_secondary_engines_adjust_entry_inside_poi():
    entry = _entry()
    result = EntryOptimizer().optimize(
        entry,
        current_price=120.0,
        trend={"trend": "BULLISH"},
        smt={"active": True, "direction": "BULLISH", "confidence": 80},
        cisd={"active": True, "direction": "BULLISH", "confidence": 75},
        volume_profile={"active": True, "poc": 104.0, "hvn": [103.0]},
    )

    assert result["applied"] is True
    assert 100.0 <= entry["entry"] <= 110.0
    assert entry["entry"] > 100.0
    assert entry["entry"] != 105.0
    assert entry["stop_loss"] < entry["entry"]


def test_opposing_evidence_demands_deeper_long_limit():
    entry = _entry()
    result = EntryOptimizer().optimize(
        entry,
        current_price=120.0,
        trend={"trend": "BEARISH"},
        smt={"active": True, "direction": "BEARISH", "confidence": 90},
        orderbook={"active": True, "opposing": True, "direction": "LONG", "best_bid": 101.0},
    )

    assert result["applied"] is True
    assert 100.0 <= entry["entry"] <= 110.0
    assert entry["entry"] < 105.0


def test_short_optimizer_keeps_entry_inside_zone_and_stop_above():
    entry = _entry("SHORT")
    result = EntryOptimizer().optimize(
        entry,
        current_price=90.0,
        trend={"trend": "BEARISH"},
        liquidity_sweep={
            "is_sweep": True,
            "buy_side": True,
            "sell_side": False,
            "sweep_level": 108.0,
            "post_structure": {"confirmed": True, "direction": "BEARISH"},
        },
    )

    assert result["applied"] is True
    assert 100.0 <= entry["entry"] <= 110.0
    assert entry["stop_loss"] > entry["entry"]


def test_optimizer_does_not_manufacture_entry_without_valid_setup():
    entry = _entry()
    entry["valid"] = False
    result = EntryOptimizer().optimize(entry, current_price=120.0, trend={"trend": "BULLISH"})

    assert result["applied"] is False
    assert entry["entry"] == 105.0



def test_proxy_evidence_has_less_entry_weight_than_live_evidence():
    live_entry = _entry()
    proxy_entry = _entry()
    live = EntryOptimizer().optimize(
        live_entry, current_price=120.0,
        institutional={"active": True, "direction": "BULLISH", "confidence": 90,
                       "cvd": {"source": "bybit_recent_trades", "is_proxy": False}},
    )
    proxy = EntryOptimizer().optimize(
        proxy_entry, current_price=120.0,
        institutional={"active": True, "direction": "BULLISH", "confidence": 90,
                       "cvd": {"source": "candle_direction_proxy", "is_proxy": True}},
    )
    live_weight = next(x["weight"] for x in live["evidence"] if x["source"] == "institutional_flow")
    proxy_weight = next(x["weight"] for x in proxy["evidence"] if x["source"] == "institutional_flow")
    assert live_weight > proxy_weight
    live_evidence = next(x for x in live["evidence"] if x["source"] == "institutional_flow")
    proxy_evidence = next(x for x in proxy["evidence"] if x["source"] == "institutional_flow")
    assert live_evidence["quality_factor"] == 0.50
    assert live_evidence["data_quality"] == "UNVERIFIED_OR_OHLCV"
    assert proxy_evidence["data_quality"] == "PROXY"



def test_optimizer_does_not_double_count_derived_trend_as_entry_evidence():
    with_trend = _entry()
    without_trend = _entry()
    a = EntryOptimizer().optimize(with_trend, current_price=120.0, trend={"trend": "BULLISH"})
    b = EntryOptimizer().optimize(without_trend, current_price=120.0)
    assert a["applied"] is True and b["applied"] is True
    assert with_trend["entry"] == without_trend["entry"]
    assert not any(item["source"] == "trend" for item in a["evidence"])



def test_timestamp_validated_trade_flow_is_mixed_not_fully_native():
    entry = _entry()
    result = EntryOptimizer().optimize(
        entry, current_price=120.0,
        institutional={"active": True, "direction": "BULLISH", "confidence": 90,
                       "cvd": {"source": "bybit_recent_trades", "is_proxy": False,
                               "timestamp_validated": True}},
    )
    evidence = next(x for x in result["evidence"] if x["source"] == "institutional_flow")
    assert evidence["quality_factor"] == 0.75
    assert evidence["data_quality"] == "MIXED_LIVE_AND_OHLCV"
