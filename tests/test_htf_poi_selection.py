from htf_fvg_engine import HTFFVGEngine
from htf_orderblock_engine import HTFOrderBlockEngine


def test_htf_fvg_skips_filled_and_wrong_direction_zones():
    result = HTFFVGEngine().detect(
        h4_fvg=[
            {"type": "BULLISH", "from": 90, "to": 92, "filled": True, "index": 20},
            {"type": "BEARISH", "from": 108, "to": 110, "filled": False, "index": 30},
        ],
        daily_fvg=[
            {"type": "BULLISH", "from": 100, "to": 102, "filled": False, "index": 10},
        ],
        current_price=105,
        direction="LONG",
    )
    assert result["valid"] is True
    assert result["timeframe"] == "1D"
    assert result["best"]["zone"] == {"low": 100.0, "high": 102.0}


def test_htf_fvg_returns_no_candidate_when_only_stale_or_opposing_zones_exist():
    result = HTFFVGEngine().detect(
        h4_fvg=[{"type": "BEARISH", "from": 108, "to": 110, "filled": False}],
        daily_fvg=[{"type": "BULLISH", "from": 90, "to": 92, "filled": True}],
        current_price=105,
        direction="LONG",
    )
    assert result["valid"] is False
    assert result["best"] is None


def test_htf_orderblock_selects_nearest_unmitigated_directional_block():
    result = HTFOrderBlockEngine().detect(
        current_price=105,
        daily_orderblocks=[
            {"type": "BULLISH", "low": 100, "high": 102, "strength": 60, "mitigated": False},
        ],
        h4_orderblocks=[
            {"type": "BULLISH", "low": 90, "high": 92, "strength": 90, "mitigated": False},
            {"type": "BULLISH", "low": 103, "high": 104, "strength": 100, "mitigated": True},
            {"type": "BEARISH", "low": 103, "high": 104, "strength": 100, "mitigated": False},
        ],
        direction="LONG",
    )
    assert result["valid"] is True
    assert result["timeframe"] == "DAILY"
    assert result["best"]["zone"] == {"low": 100.0, "high": 102.0}
