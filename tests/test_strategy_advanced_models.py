import strategy_lab


class TimedCandle:
    def __init__(self, timestamp, open_, high, low, close, volume=100.0):
        self.time = timestamp
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


def _price_series(returns, start=100.0, start_time=1_700_000_000_000):
    closes = [start]
    for value in returns:
        closes.append(closes[-1] * (1.0 + value))
    candles = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        candles.append(TimedCandle(
            start_time + index * 4 * 60 * 60 * 1000,
            opened, close * 1.006, close * 0.994, close
        ))
    return candles


def test_relative_strength_uses_beta_adjusted_sector_peer_residual():
    market_returns = [
        0.0004 + (index % 5) * 0.00025
        for index in range(59)
    ]
    asset_returns = [
        value if index < 47 else value + 0.003
        for index, value in enumerate(market_returns)
    ]
    own = _price_series(asset_returns)
    btc = _price_series(market_returns)
    eth = _price_series(market_returns)
    peer_a = _price_series(market_returns)
    peer_b = _price_series(market_returns)
    # Relative-strength signals must also supply genuine structural exits.
    # This daily series contributes a protected swing low and three opposing
    # swing-high liquidity levels above the current 4H price.
    daily_highs = [110, 111, 112, 115, 112, 111, 113, 114, 118, 115, 114, 116, 117, 121, 119, 118, 117]
    daily_lows = [108, 107, 108, 108, 106, 108, 108, 107, 108, 108, 107, 108, 108, 107, 108, 108, 107]
    daily_structure = [
        TimedCandle(1_700_000_000_000 + index * 24 * 60 * 60 * 1000, 109, high, low, 109)
        for index, (high, low) in enumerate(zip(daily_highs, daily_lows))
    ]
    plan = strategy_lab._relative_strength({
        "symbol": "SOL/USDT:USDT",
        "4h": own,
        "1d": daily_structure,
        "current_price": own[-1].close,
        "correlation_universe": {"BTC": btc, "ETH": eth},
        "sector_peer_universe": {
            "AVAX/USDT:USDT": {"4h": peer_a},
            "ADA/USDT:USDT": {"4h": peer_b},
        },
    })
    assert plan is not None
    assert plan["direction"] == "LONG"
    assert plan["relative_strength_metrics"]["sector_peers_used"] == 2
    assert plan["relative_strength_metrics"]["beta"] > 0
    assert plan["relative_strength_metrics"]["residual_alpha_12x4h"] >= 0.02


def test_absorption_proxy_detects_stalled_aggressive_flow():
    candle = TimedCandle(1, 100, 100.2, 99.8, 100.05)
    buyer_absorbed = strategy_lab._absorption_proxy({
        "trade_delta": 0.25, "imbalance": -0.20, "trade_count": 40
    }, candle, 1.0)
    seller_absorbed = strategy_lab._absorption_proxy({
        "trade_delta": -0.25, "imbalance": 0.20, "trade_count": 40
    }, candle, 1.0)
    assert buyer_absorbed == "BUYER_FLOW_ABSORBED"
    assert seller_absorbed == "SELLER_FLOW_ABSORBED"


def test_absorption_proxy_rejects_low_sample_or_moving_price():
    candle = TimedCandle(1, 100, 102, 99, 101)
    assert strategy_lab._absorption_proxy({
        "trade_delta": 0.3, "imbalance": -0.2, "trade_count": 8
    }, candle, 1.0) is None
    assert strategy_lab._absorption_proxy({
        "trade_delta": 0.3, "imbalance": -0.2, "trade_count": 40
    }, candle, 1.0) is None

    falling_price = TimedCandle(2, 100, 100.1, 97.9, 98)
    assert strategy_lab._absorption_proxy({
        "trade_delta": 0.3, "imbalance": -0.2, "trade_count": 40
    }, falling_price, 1.0) is None
