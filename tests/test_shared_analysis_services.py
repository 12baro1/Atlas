from shared.analysis_context import AnalysisContext
from shared.market_structure_services import displacement, trend_structure, volatility_regime
from shared.microstructure_services import beta_stability, relative_volume


def test_market_structure_evidence_is_reused_for_same_snapshot():
    from types import SimpleNamespace
    candles = [
        SimpleNamespace(open=100+i, high=103+i, low=98+i, close=102+i, volume=100+i)
        for i in range(100)
    ]
    with AnalysisContext() as context:
        first = trend_structure(candles)
        count = context.computation_count
        second = trend_structure(candles)
        assert first == second
        assert context.computation_count == count


def test_microstructure_evidence_is_reused_for_same_inputs():
    asset = [i / 10000 for i in range(60)]
    market = [i / 12000 for i in range(60)]
    with AnalysisContext() as context:
        first = beta_stability(asset, market, 24)
        count = context.computation_count
        second = beta_stability(asset, market, 24)
        assert first == second
        assert context.computation_count == count


def test_shared_services_still_work_without_active_analysis_scope():
    assert relative_volume(20, [10] * 20)["ratio"] == 2.0
    assert displacement([], 1.0)["state"] == "UNAVAILABLE"
    assert volatility_regime([], period=14)["state"] == "UNAVAILABLE"


def test_orderflow_evidence_bundle_is_reused_for_same_snapshot():
    from strategies.orderflow.analytics import build_orderflow_evidence

    trades = [
        {"timestamp": 1000+i, "price": 100.0+i, "amount": 0.1, "side": "buy" if i % 2 else "sell"}
        for i in range(25)
    ]
    book = {"bids": [[99.0, 2.0]], "asks": [[101.0, 1.5]]}
    candles = []
    with AnalysisContext() as context:
        first = build_orderflow_evidence(trades, book, candles, [])
        count = context.computation_count
        second = build_orderflow_evidence(trades, book, candles, [])
        assert first == second
        assert context.computation_count == count
