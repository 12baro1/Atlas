from strategy_performance import evaluate_strategy_edge, rank_validated_candidate


def good_stats():
    return {
        "is_trades": 120,
        "is_expectancy_r": 0.24,
        "is_profit_factor": 1.42,
        "is_expectancy_std_r": 0.8,
        "oos_trades": 40,
        "oos_expectancy_r": 0.16,
        "oos_profit_factor": 1.23,
    }


def test_missing_performance_fails_closed():
    result = evaluate_strategy_edge(None)
    assert result["eligible"] is False
    assert result["status"] == "NO_PERFORMANCE_RECORD"


def test_incomplete_performance_fails_closed():
    result = evaluate_strategy_edge({"is_trades": 100})
    assert result["eligible"] is False
    assert result["status"] == "INCOMPLETE_PERFORMANCE_RECORD"


def test_positive_is_not_enough_without_oos_confirmation():
    stats = good_stats()
    stats["oos_expectancy_r"] = -0.01
    result = evaluate_strategy_edge(stats)
    assert result["eligible"] is False
    assert any("out-of-sample net expectancy" in reason for reason in result["reasons"])


def test_small_sample_is_rejected():
    stats = good_stats()
    stats["is_trades"] = 12
    result = evaluate_strategy_edge(stats)
    assert result["eligible"] is False


def test_edge_gate_requires_positive_confidence_lower_bound():
    stats = good_stats()
    stats["is_expectancy_r"] = 0.02
    stats["is_expectancy_std_r"] = 2.0
    result = evaluate_strategy_edge(stats)
    assert result["eligible"] is False


def test_validated_edge_can_be_ranked_without_using_signal_strength():
    candidate = {"strategy_id": "trend_pullback", "strength": 99.0}
    ranked = rank_validated_candidate(candidate, good_stats(), regime_fit=0.9)
    assert ranked is not None
    assert ranked["strategy_id"] == "trend_pullback"
    assert ranked["score"] > 0


def test_invalid_numeric_data_is_rejected():
    stats = good_stats()
    stats["is_expectancy_std_r"] = float("nan")
    assert evaluate_strategy_edge(stats)["status"] == "INVALID_PERFORMANCE_RECORD"
