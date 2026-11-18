from strategies.smc.strategy import _mandatory_confluence_reason


def _analysis():
    return {
        "smc_h4_structure": [{"choch": True, "direction": "BULLISH"}],
        "smc_orderblocks": [{"type": "BULLISH", "low": 98.0, "high": 102.0, "mitigated": False}],
        "smc_fvg": [{"type": "BULLISH", "from": 99.0, "to": 101.0, "filled": False}],
        "smc_ote": {"fib62": 101.0, "fib79": 99.5},
    }


def test_smc_requires_all_four_conditions_and_entry_in_shared_zone():
    assert _mandatory_confluence_reason(_analysis(), "LONG", 100.0) is None


def test_smc_rejects_missing_choch():
    analysis = _analysis()
    analysis["smc_h4_structure"] = []
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_CHoCH_MISSING"


def test_smc_rejects_wrong_direction_choch():
    analysis = _analysis()
    analysis["smc_h4_structure"] = [{"choch": True, "direction": "BEARISH"}]
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_CHoCH_DIRECTION_MISMATCH"


def test_smc_rejects_missing_ob_even_when_fvg_exists():
    analysis = _analysis()
    analysis["smc_orderblocks"] = []
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_VALID_OB_MISSING"


def test_smc_rejects_missing_fvg_even_when_ob_exists():
    analysis = _analysis()
    analysis["smc_fvg"] = []
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_VALID_FVG_MISSING"


def test_smc_rejects_mitigated_ob_and_filled_fvg():
    analysis = _analysis()
    analysis["smc_orderblocks"][0]["mitigated"] = True
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_VALID_OB_MISSING"
    analysis = _analysis()
    analysis["smc_fvg"][0]["filled"] = True
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_REQUIRED_VALID_FVG_MISSING"


def test_smc_rejects_non_overlapping_ob_fvg_ote_or_entry_outside_overlap():
    analysis = _analysis()
    analysis["smc_fvg"][0]["from"] = 102.0
    analysis["smc_fvg"][0]["to"] = 103.0
    assert _mandatory_confluence_reason(analysis, "LONG", 100.0) == "SMC_OB_FVG_OTE_CONFLUENCE_OR_ENTRY_MISSING"
    assert _mandatory_confluence_reason(_analysis(), "LONG", 101.5) == "SMC_OB_FVG_OTE_CONFLUENCE_OR_ENTRY_MISSING"
