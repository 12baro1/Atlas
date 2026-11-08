from setup_reasoning_engine import SetupReasoningEngine


def _run(**overrides):
    payload = {
        "base_entry": {"valid": False, "score": 0, "checks": []},
        "mtf": {"entry": "SHORT", "weekly": "BEARISH", "daily": "BEARISH", "h4": "BEARISH"},
        "structure": [{"choch": True, "direction": "BULLISH", "label": "HH"}],
        "fvg": [{"type": "BULLISH", "from": 100, "to": 105, "filled": False}],
        "orderblocks": [],
        "current_price": 110,
        "candles": [],
        "liquidity_sweep": {
            "is_sweep": True, "sell_side": True, "buy_side": False,
            "sweep_side": "SELL_SIDE",
            "post_structure": {"confirmed": True, "direction": "BULLISH"},
        },
        "ote": {"fib62": 101, "fib79": 104},
        "market_regime": {"regime": "RANGING"},
        "htf_orderblock": {}, "htf_fvg": {},
        "smt": {"active": True, "direction": "BEARISH", "confidence": 80},
        "unicorn": {}, "cisd": {}, "volume_profile": {}, "institutional": {},
        "orderbook": {}, "correlation": {}, "market_phase": {"phase": "Reversal"},
        "liquidity": [{"type": "BUY_SIDE", "price": 120}],
        "external_structure": [],
    }
    payload.update(overrides)
    return SetupReasoningEngine().generate(**payload)


def test_confirmed_sell_side_sweep_can_create_countertrend_long_candidate():
    result = _run()
    selected = result["selected"]
    assert selected["valid"] is True
    assert selected["direction"] == "LONG"
    assert selected["direction_source"] == "CONFIRMED_SWEEP_REVERSAL"
    assert selected["entry_type"] == "LIMIT"
    assert selected["stop_loss"] < selected["entry"]


def test_opposing_smt_is_recorded_as_counter_evidence_not_a_veto():
    result = _run()
    selected = result["selected"]
    assert selected["direction"] == "LONG"
    assert any("SMT SHORT" in item for item in selected["opposing_evidence"])


def test_no_candidate_is_created_without_a_real_directional_poi():
    result = _run(fvg=[], orderblocks=[])
    assert result["candidates"] == []
    assert result["selected"]["valid"] is False


def test_candidate_selection_prefers_better_projected_rr_not_motor_vote_count():
    result = _run(
        fvg=[
            {"type": "BULLISH", "from": 100, "to": 105, "filled": False},
            {"type": "BULLISH", "from": 106, "to": 108, "filled": False},
        ],
        current_price=112,
        liquidity=[{"type": "BUY_SIDE", "price": 120}, {"type": "BUY_SIDE", "price": 150}],
    )
    assert len(result["candidates"]) == 2
    assert result["selected"]["projected_rr"] == max(
        candidate["projected_rr"] for candidate in result["candidates"]
    )


def test_invalid_or_non_finite_poi_levels_are_ignored():
    result = _run(
        fvg=[
            {"type": "BULLISH", "from": float("nan"), "to": 105, "filled": False},
            {"type": "BULLISH", "from": 100, "to": 105, "filled": False},
        ],
    )
    assert len(result["candidates"]) == 1



def test_countertrend_candidate_can_use_raw_four_hour_order_block():
    result = _run(
        fvg=[],
        higher_timeframe_orderblocks=[
            {"type": "BULLISH", "low": 100, "high": 105, "mitigated": False}
        ],
    )
    assert result["selected"]["direction"] == "LONG"
    assert result["selected"]["poi_source"] == "HTF_ORDER_BLOCK"



def test_orderbook_bias_is_reinterpreted_for_countertrend_candidate():
    result = _run(orderbook={"active": True, "supportive": True, "opposing": False})
    selected = result["selected"]
    assert selected["direction"] == "LONG"
    assert any("Order flow counterpressure" in item for item in selected["opposing_evidence"])
    assert selected["counterpressure_adjusted"] is True



def test_wrong_side_liquidity_is_not_used_as_projected_target():
    result = _run(liquidity=[{"type": "SELL_SIDE", "price": 200}])
    assert result["selected"]["projected_target"] is None
    assert result["selected"]["projected_rr"] is None



def test_optimizer_price_is_used_only_for_the_matching_poi():
    base = {
        "valid": False, "direction": "LONG", "poi_source": "FVG",
        "poi_zone": {"low": 100, "high": 105}, "score": 50, "checks": [],
    }
    result = _run(
        base_entry=base,
        mtf={"entry": "SHORT", "weekly": "NEUTRAL", "daily": "NEUTRAL", "h4": "NEUTRAL"},
        smt={}, optimization={"applied": True, "optimized_entry": 102},
    )
    assert result["selected"]["entry"] == 102



def test_breaker_ifvg_and_unicorn_motors_can_supply_directional_poi_candidates():
    breaker = _run(
        fvg=[], breaker=[
            {"type": "BULLISH", "direction": "BULLISH", "low": 100, "high": 105, "breaker": True}
        ],
    )
    assert breaker["selected"]["poi_source"] == "BREAKER"

    ifvg = _run(
        fvg=[], ifvg=[
            {"type": "BEARISH", "from": 100, "to": 105, "inverted": True}
        ],
    )
    assert ifvg["selected"]["poi_source"] == "IFVG"

    unicorn = _run(
        fvg=[], unicorn={
            "active": True, "direction": "BULLISH",
            "setups": [{"valid": True, "direction": "BULLISH", "zone": {"low": 100, "high": 105}}],
        },
    )
    assert unicorn["selected"]["poi_source"] == "UNICORN"


def test_context_motors_are_recorded_in_setup_reasoning():
    result = _run(
        fvg=[], breaker=[
            {"type": "BULLISH", "direction": "BULLISH", "low": 100, "high": 105, "breaker": True}
        ],
        trendline_sweep={"active": True, "direction": "SELL_SIDE"},
        eqh_eql={"active": True},
        inducement={"active": True, "direction": "LONG"},
        premium_discount={"valid": True, "discount": True, "premium": False},
        internal_structure=[{"choch": True, "direction": "BULLISH"}],
        market_phase={"phase": "Accumulation"},
        trendline_liquidity=[{"type": "BUY_SIDE", "price": 125}],
    )
    selected = result["selected"]
    assert any("Breaker block LONG" in item for item in selected["supporting_evidence"])
    assert any("Trendline sweep LONG" in item for item in selected["supporting_evidence"])
    assert any("Internal structure LONG" in item for item in selected["supporting_evidence"])
    assert any("Premium/Discount zone favorable" in item for item in selected["supporting_evidence"])
    assert any("Market phase: Accumulation" in item for item in selected["market_context"])



def test_trendline_liquidity_can_be_a_structural_candidate_target():
    result = _run(
        liquidity=[],
        trendline_liquidity=[{"type": "BUY_SIDE", "price": 125}],
    )
    assert result["selected"]["projected_target"] == 125
