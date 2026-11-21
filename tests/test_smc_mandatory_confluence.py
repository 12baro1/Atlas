from strategies.smc.strategy import _mandatory_confluence_reason


def _analysis():
    return {
        "smc_h4_structure": [{"choch": True, "direction": "BULLISH"}],
        "smc_orderblocks": [{"type": "BULLISH", "low": 98.0, "high": 102.0, "mitigated": False}],
        "smc_fvg": [{"type": "BULLISH", "from": 99.0, "to": 101.0, "filled": False}],
        "smc_ote": {"fib62": 101.0, "fib79": 99.5},
    }


def test_smc_accepts_ob_and_fvg():
    assert _mandatory_confluence_reason(_analysis(), "LONG", 100.0) is None


def test_smc_accepts_ob_without_fvg():
    analysis = _analysis()
    analysis["smc_fvg"] = []
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) is None


def test_smc_accepts_fvg_without_ob():
    analysis = _analysis()
    analysis["smc_orderblocks"] = []
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) is None


def test_smc_rejects_when_both_ob_and_fvg_are_missing():
    analysis = _analysis()
    analysis["smc_orderblocks"] = []
    analysis["smc_fvg"] = []
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_VALID_OB_OR_FVG_MISSING"


def test_smc_rejects_missing_choch():
    analysis = _analysis()
    analysis["smc_h4_structure"] = []
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_CHoCH_MISSING"


def test_smc_rejects_wrong_direction_choch():
    analysis = _analysis()
    analysis["smc_h4_structure"] = [{"choch": True, "direction": "BEARISH"}]
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_CHoCH_DIRECTION_MISMATCH"


def test_smc_rejects_mitigated_ob_and_filled_fvg():
    analysis = _analysis()
    analysis["smc_orderblocks"][0]["mitigated"] = True
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) is None
    analysis = _analysis()
    analysis["smc_fvg"][0]["filled"] = True
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) is None


def test_smc_rejects_if_only_available_zone_is_invalid():
    analysis = _analysis()
    analysis["smc_orderblocks"][0]["mitigated"] = True
    analysis["smc_fvg"][0]["filled"] = True
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_VALID_OB_OR_FVG_MISSING"


def test_smc_rejects_wrong_direction_zones():
    analysis = _analysis()
    analysis["smc_orderblocks"][0]["type"] = "BEARISH"
    analysis["smc_fvg"][0]["type"] = "BEARISH"
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_VALID_OB_OR_FVG_MISSING"


def test_smc_rejects_entry_outside_all_valid_zones():
    assert _mandatory_confluence_reason(_analysis(), "LONG", 103.0) == "SMC_ENTRY_OUTSIDE_VALID_OB_FVG"


def test_smc_does_not_require_ote():
    analysis = _analysis()
    analysis.pop("smc_ote")
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) is None


def test_smc_does_not_reject_invalid_ote():
    analysis = _analysis()
    analysis["smc_ote"] = {"fib62": "bad", "fib79": None}
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) is None


def test_smc_rejects_opposite_break_after_choch():
    analysis = _analysis()
    analysis["smc_h4_structure"].append({"bos": True, "direction": "BEARISH"})
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_CHoCH_INVALIDATED_BY_OPPOSITE_BREAK"


def test_smc_keeps_same_direction_break_after_choch():
    analysis = _analysis()
    analysis["smc_h4_structure"].append({"bos": True, "direction": "BULLISH"})
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) is None


def test_smc_rejects_explicitly_stale_choch():
    analysis = _analysis()
    analysis["smc_h4_structure"][0]["age_bars"] = 31
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_CHoCH_STALE"


def test_smc_accepts_recent_choch():
    analysis = _analysis()
    analysis["smc_h4_structure"][0]["age_bars"] = 4
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) is None
