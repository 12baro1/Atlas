from core.market_state import MarketState


def test_market_state_defaults_and_reset_signal():
    state = MarketState(signal="LONG", entry=1.0, stop_loss=0.5, take_profit=2.0)

    state.reset_signal()

    assert state.signal == "NONE"
    assert state.entry is None
    assert state.stop_loss is None
    assert state.take_profit is None
