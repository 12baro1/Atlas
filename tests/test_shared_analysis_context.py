from shared.analysis_context import AnalysisContext, analysis_scope, cached_analysis


def test_cached_analysis_computes_once_for_same_inputs_within_scope():
    calls = []

    @cached_analysis
    def calculate(values, period=2):
        calls.append((tuple(values), period))
        return sum(values[-period:])

    @analysis_scope
    def run():
        first = calculate([1, 2, 3], period=2)
        second = calculate([1, 2, 3], period=2)
        return first, second

    assert run() == (5, 5)
    assert len(calls) == 1


def test_cached_analysis_does_not_leak_between_scopes():
    calls = []

    @cached_analysis
    def calculate(value):
        calls.append(value)
        return value * 2

    @analysis_scope
    def run():
        return calculate(7)

    assert run() == 14
    assert run() == 14
    assert calls == [7, 7]


def test_analysis_context_is_isolated_and_cleared_on_exit():
    with AnalysisContext() as context:
        context.get_or_compute(("x",), lambda: 1)
        assert context.computation_count == 1
    assert context.computation_count == 0
