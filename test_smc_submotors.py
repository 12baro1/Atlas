from types import SimpleNamespace

from smc_submotors import (
    breaker_validation,
    dealing_range,
    inducement_proxy,
    liquidity_draw,
    narrative,
    poi_freshness,
    reclaim_acceptance,
)


def candles(rows):
    return [SimpleNamespace(open=o, high=h, low=l, close=c)
            for o, h, l, c in rows]


def test_dealing_range_classifies_discount_and_premium():
    sample = candles([(50, 100, 0, 50)] * 20)
    assert dealing_range(sample, 20)["zone"] == "DISCOUNT"
    assert dealing_range(sample, 80)["zone"] == "PREMIUM"


def test_liquidity_draw_uses_next_external_high_for_long():
    sample = candles([(10, 12, 8, 10)] * 10 + [(10, 15, 9, 11)])
    result = liquidity_draw(sample, "LONG")
    assert result["side"] == "BUY_SIDE"
    assert result["target"] == 12


def test_poi_freshness_does_not_treat_mitigated_zone_as_fresh():
    result = poi_freshness([
        {"top": 12, "bottom": 10, "mitigated": True, "tested_count": 1},
        {"top": 9, "bottom": 8, "mitigated": False, "tested_count": 0},
    ], 11)
    assert result["fresh_count"] == 1
    assert result["zones"][0]["fresh"] is False


def test_bullish_orderblock_breaks_into_bearish_breaker_only_on_close():
    sample = candles([(10, 11, 9, 10), (9, 10, 8, 8.5)])
    result = breaker_validation([{"kind": "BULLISH", "top": 10, "bottom": 9}], sample)
    assert result["state"] == "FOUND"
    assert result["validated"][0]["kind"] == "BEARISH_BREAKER"


def test_reclaim_requires_prior_side_then_close_through_level():
    accepted = candles([(9, 10, 8, 9), (10, 11, 9, 10.5)])
    assert reclaim_acceptance(accepted, 10, "LONG")["state"] == "ACCEPTED"
    rejected = candles([(10.2, 11, 10, 10.5), (10.1, 11, 10, 10.4)])
    assert reclaim_acceptance(rejected, 10, "LONG")["state"] == "NOT_ACCEPTED"


def test_inducement_proxy_is_explicitly_a_proxy():
    sample = candles([(10, 11, 9, 10)] * 12)
    assert inducement_proxy(sample, "LONG")["proxy"] is True


def test_narrative_is_diagnostic_not_execution_authority():
    result = narrative("LONG", {"state": "BULLISH"}, {"zone": "DISCOUNT"},
                       {"state": "FOUND"}, {"direction": "BULLISH"}, {"fresh_count": 1})
    assert result["evidence_count"] == 5
    assert result["authority"] == "DIAGNOSTIC_ONLY"
