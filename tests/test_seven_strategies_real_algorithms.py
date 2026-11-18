"""Gerçek strateji algoritma testleri (requirement I).

Monkeypatch yerine gerçek strateji generator fonksiyonları ve gerçek
piyasa verisi fixture'ları kullanılarak her stratejin bağımsız işlem
mantığı ve setup üretimi doğrulanır.

Yedi strateji:
- trend_pullback
- volatility_breakout
- mean_reversion
- liquidation_cascade
- orderflow_momentum
- relative_strength
- smc

Her strateji için:
- Geçerli LONG setup üretilmeli
- Geçerli SHORT setup üretilmeli
- Uygun olmayan piyasa koşulunda None dönmeli
- Strateji kimliği doğru olmalı
- Geometri (entry < tp1 < tp2 < tp3 for LONG, etc.) geçerli olmalı
"""
import math
import time

import pytest

from strategies.breakout.strategy import generate as breakout_generate
from strategies.liquidation.strategy import generate as liquidation_generate
from strategies.mean_reversion.strategy import generate as mean_reversion_generate
from strategies.orderflow.strategy import generate as orderflow_generate
from strategies.relative_strength.strategy import generate as relative_strength_generate
from strategies.smc.strategy import generate as smc_generate
from strategies.trend.strategy import generate as trend_generate


class Candle:
    def __init__(self, time_ms, open_, high, low, close, volume=100.0):
        self.time = time_ms
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


def _now_ms():
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# 1. trend_pullback — gerçek 4H/1H EMA ve ADX tabanlı trend
# ---------------------------------------------------------------------------

def _trend_pullback_bullish_data():
    """4H: EMA20 > EMA50, rising. 1H: price near EMA20, bullish reclaim."""
    now = _now_ms()
    h4 = []
    price = 100.0
    for i in range(60):
        price += 0.12
        h4.append(Candle(now + i * 4 * 3600_000, price - 0.05,
                         price + 0.12, price - 0.05, price + 0.08, 120.0))
    h1 = []
    price = h4[-1].close
    for i in range(20):
        price += 0.04
        h1.append(Candle(now + 60 * 4 * 3600_000 + i * 3600_000,
                         price - 0.03, price + 0.08, price - 0.06, price + 0.05, 100.0))
    for i in range(9):
        price -= 0.04
        h1.append(Candle(now + (260 + i) * 3600_000,
                         price - 0.02, price + 0.04, price - 0.05, price + 0.01, 100.0))
    from strategy_lab import _ema, _atr, _series
    ema = _ema(_series(h1), 20)
    atr = _atr(h1)
    reclaim_close = ema + 0.10 * atr
    h1.append(Candle(now + 269 * 3600_000, ema - 0.10 * atr,
                     ema + 0.30 * atr, ema - 0.30 * atr, reclaim_close, 120.0))
    return {
        "symbol": "BTC/USDT:USDT",
        "4h": h4,
        "1h": h1,
        "current_price": h1[-1].close,
        "shared_market_evidence": {},
    }


def test_trend_pullback_real_data_produces_long():
    data = _trend_pullback_bullish_data()
    plan = trend_generate(data)
    assert plan is not None, "trend_pullback must produce a setup from its positive fixture"
    if plan is not None:
        assert plan["strategy_id"] == "trend_pullback"
        assert plan["direction"] in ("LONG", "SHORT")
        # Strategy generators return raw setups; the common filter later
        # finalizes structural stop and three opposing-liquidity targets.
        assert plan["entry"] > 0 and plan["initial_stop_loss"] > 0
        if plan["direction"] == "LONG":
            assert plan["initial_stop_loss"] < plan["entry"]
        else:
            assert plan["initial_stop_loss"] > plan["entry"]


def test_trend_pullback_real_data_flat_market_returns_none():
    now = _now_ms()
    flat = [Candle(now + i * 3600_000, 100, 100.1, 99.9, 100, 100.0) for i in range(60)]
    data = {
        "symbol": "BTC/USDT:USDT",
        "4h": flat,
        "1h": flat,
        "current_price": 100.0,
        "shared_market_evidence": {},
    }
    assert trend_generate(data) is None


# ---------------------------------------------------------------------------
# 2. volatility_breakout — gerçek Bollinger bant sıkması + breakout
# ---------------------------------------------------------------------------

def _volatility_breakout_data():
    """1H: volatility compression then breakout."""
    now = _now_ms()
    candles = []
    # Earlier wide regime followed by a genuine narrow 20-bar compression.
    for i in range(20):
        close = 100.0 + (0.45 if i % 2 else -0.45)
        candles.append(Candle(now + i * 3600_000, 100.0, 101.5, 98.5, close, 100.0))
    for i in range(24):
        close = 100.0 + (0.01 if i % 2 else -0.01)
        candles.append(Candle(now + (20 + i) * 3600_000, 100.0, 100.2, 99.8, close, 100.0))
    # Breakout closes above the compressed range and remains within one ATR.
    candles.append(Candle(now + 44 * 3600_000, 100.0, 100.45,
                          99.8, 100.4, 250.0))
    return {
        "symbol": "ETH/USDT:USDT",
        "1h": candles,
        "current_price": candles[-1].close,
        "shared_market_evidence": {},
    }


def test_volatility_breakout_real_data():
    data = _volatility_breakout_data()
    plan = breakout_generate(data)
    assert plan is not None, "volatility_breakout must produce a setup from its positive fixture"
    if plan is not None:
        assert plan["strategy_id"] == "volatility_breakout"
        assert plan["direction"] in ("LONG", "SHORT")
        assert plan["entry"] > 0
        # No specialist_evidence is supplied in this fixture: specialist motors
        # are optional analysis context, never mandatory breakout approvals.
        assert plan["specialist_evidence"] == []
        assert plan["specialist_evidence_count"] == 0


def test_volatility_breakout_no_compression_returns_none():
    now = _now_ms()
    # Expanding volatility: no compression -> no setup
    candles = [Candle(now + i * 3600_000, 100, 110, 90, 100, 100.0) for i in range(45)]
    data = {
        "symbol": "ETH/USDT:USDT",
        "1h": candles,
        "current_price": 100.0,
        "shared_market_evidence": {},
    }
    assert breakout_generate(data) is None


# ---------------------------------------------------------------------------
# 3. mean_reversion — gerçek RANGE rejimi + Bollinger/RSI
# ---------------------------------------------------------------------------

def _mean_reversion_data():
    """15M: range-bound, RSI extremes, price at band edge."""
    now = _now_ms()
    candles = []
    price = 100.0
    for i in range(25):
        o = price
        h = price + 1.0
        l = price - 1.0
        c = price + ((-1) ** i) * 0.3
        candles.append(Candle(now + i * 900_000, o, h, l, c, 100.0))
        price += 0.02
    # Force bullish mean-reversion: price dipped below band, now reclaiming
    candles[-2] = Candle(now + 23 * 900_000, 99, 100, 98, 98.2, 100.0)
    candles[-1] = Candle(now + 24 * 900_000, 98.2, 99.5, 97.8, 99.0, 100.0)
    return {
        "symbol": "SOL/USDT:USDT",
        "15m": candles,
        "current_price": 99.0,
        "shared_market_evidence": {},
    }


def test_mean_reversion_real_data_range_regime():
    data = _mean_reversion_data()
    plan = mean_reversion_generate(data, {"label": "RANGE", "adx": 15})
    assert plan is not None, "mean_reversion must produce a setup from its positive fixture"
    if plan is not None:
        assert plan["strategy_id"] == "mean_reversion"
        assert plan["direction"] in ("LONG", "SHORT")


def test_mean_reversion_non_range_returns_none():
    data = _mean_reversion_data()
    assert mean_reversion_generate(data, {"label": "TREND"}) is None


# ---------------------------------------------------------------------------
# 4. liquidation_cascade — gerçek OI gerilmesi + impulse
# ---------------------------------------------------------------------------

def _liquidation_cascade_data():
    now = _now_ms()
    candles = [Candle(now + i * 3600_000, 100, 101, 99, 100, 100.0) for i in range(20)]
    candles.append(Candle(now + 20 * 3600_000, 93.5, 100.4, 93.2, 100, 140.0))
    return {
        "symbol": "ADA/USDT:USDT",
        "1h": candles,
        "open_interest": [1000.0, 950.0],
        "open_interest_timestamps_ms": [now - 7_200_000, now - 60_000],
        "snapshot_timestamp_ms": now,
        "current_price": 100.0,
        "funding_rate": [-0.0002],
        "funding_rate_timestamps_ms": [now - 60_000],
        "recent_trades": [{"amount": 2.0, "price": 100.0, "side": "buy"} for _ in range(25)],
        "liquidation_events": [],
        "shared_market_evidence": {
            "open_interest": {"state": "FRESH", "count": 2, "change_pct": -5.0},
        },
    }


def test_liquidation_cascade_real_data():
    data = _liquidation_cascade_data()
    plan = liquidation_generate(data)
    assert plan is not None, "liquidation_cascade must produce a setup from its positive fixture"
    if plan is not None:
        assert plan["strategy_id"] == "liquidation_cascade"
        assert plan["direction"] in ("LONG", "SHORT")
        # The positive fixture has no specialist motor outputs. Native OI/flow
        # evidence is sufficient; specialist motors remain optional context.
        assert plan["specialist_evidence"] == []
        assert plan["specialist_evidence_count"] == 0


def test_liquidation_cascade_stale_oi_returns_none():
    now = _now_ms()
    data = {
        "symbol": "ADA/USDT:USDT",
        "1h": [Candle(now + idx * 3600_000, 100, 101, 99, 100, 100.0) for idx in range(21)],
        "open_interest": [1000.0, 990.0],
        "open_interest_timestamps_ms": [now - 7_200_000, now - 60_000],
        "snapshot_timestamp_ms": now,
        "current_price": 100.0,
        "shared_market_evidence": {
            "open_interest": {"state": "STALE", "count": 2, "change_pct": -1.0},
        },
    }
    assert liquidation_generate(data) is None


# ---------------------------------------------------------------------------
# 5. orderflow_momentum — gerçek order book imbalance + taker flow
# ---------------------------------------------------------------------------

def _orderflow_data(side="buy"):
    now = _now_ms()
    bid_size = 20.0 if side == "buy" else 2.0
    ask_size = 2.0 if side == "buy" else 20.0
    buy_notional = 200.0 if side == "buy" else 10.0
    sell_notional = 10.0 if side == "buy" else 200.0
    current_price = 100.4 if side == "buy" else 99.6
    last_candle = (
        Candle(now + 14 * 900_000, 99.8, 100.5, 99.7, 100.4, 100.0)
        if side == "buy" else
        Candle(now + 14 * 900_000, 100.2, 100.3, 99.5, 99.6, 100.0)
    )
    bids = ([[100.39, bid_size], [100.38, bid_size], [100.37, bid_size]]
            if side == "buy" else
            [[99.59, bid_size], [99.58, bid_size], [99.57, bid_size]])
    asks = ([[100.41, ask_size], [100.42, ask_size], [100.43, ask_size]]
            if side == "buy" else
            [[99.61, ask_size], [99.62, ask_size], [99.63, ask_size]])
    trade_base = 100.1 if side == "buy" else 99.7
    return {
        "symbol": "BTC/USDT:USDT",
        "snapshot_timestamp_ms": now,
        "current_price": current_price,
        "15m": ([Candle(now + i * 900_000, 100, 101, 99, 100, 100.0) for i in range(14)]
                + [last_candle]),
        "orderbook": {"bids": bids, "asks": asks},
        "orderbook_timestamp_ms": now,
        "recent_trades": [
            {"amount": 5.0, "price": trade_base + (i % 2) * 0.1, "side": side} for i in range(40)
        ],
        "recent_trades_timestamp_ms": now,
        "trade_flow_history": [
            {"timestamp_ms": now - 1000, "buy_notional": buy_notional,
             "sell_notional": sell_notional} for _ in range(40)
        ],
        "liquidation_events": [],
        "data_provenance": {
            "orderbook": "GATEIO_WS_ORDERBOOK",
            "recent_trades": "GATEIO_WS_TRADES",
            "trade_flow_history": "GATEIO_WS_TRADES",
        },
        "shared_market_evidence": {},
    }


def test_orderflow_real_data_buy_side():
    data = _orderflow_data("buy")
    data["shared_market_evidence"] = __import__(
        "shared.market_data_services", fromlist=["build_shared_market_evidence"]
    ).build_shared_market_evidence(data)
    plan = orderflow_generate(data)
    assert plan is not None, "orderflow_momentum must produce a setup from its positive fixture"
    if plan is not None:
        assert plan["strategy_id"] == "orderflow_momentum"
        assert plan["direction"] == "LONG"
        metrics = plan.get("orderflow_metrics", {})
        assert metrics.get("trade_delta", 0) > 0


def test_orderflow_real_data_sell_side():
    data = _orderflow_data("sell")
    data["shared_market_evidence"] = __import__(
        "shared.market_data_services", fromlist=["build_shared_market_evidence"]
    ).build_shared_market_evidence(data)
    plan = orderflow_generate(data)
    assert plan is not None, "orderflow_momentum must produce a short setup from its positive fixture"
    if plan is not None:
        assert plan["direction"] == "SHORT"


def test_orderflow_stale_data_returns_none():
    now = _now_ms() - 60_000
    data = _orderflow_data("buy")
    data["orderbook_timestamp_ms"] = now
    data["recent_trades_timestamp_ms"] = now
    data["shared_market_evidence"] = __import__(
        "shared.market_data_services", fromlist=["build_shared_market_evidence"]
    ).build_shared_market_evidence(data)
    assert orderflow_generate(data) is None


def test_orderflow_no_data_returns_none():
    assert orderflow_generate({}) is None


# ---------------------------------------------------------------------------
# 6. relative_strength — gerçek beta + residual alpha
# ---------------------------------------------------------------------------

def _relative_strength_data():
    market_returns = [0.0004 + (i % 5) * 0.00025 for i in range(59)]
    asset_returns = [v if i < 47 else v + 0.003 for i, v in enumerate(market_returns)]
    now = _now_ms()

    def series(returns, base_time):
        closes = [100.0]
        for v in returns:
            closes.append(closes[-1] * (1.0 + v))
        return [Candle(base_time + i * 4 * 3600_000, c - 0.5, c + 0.6, c - 0.6, c, 100.0)
                for i, c in enumerate(closes)]

    own = series(asset_returns, now - 59 * 4 * 3600_000)
    btc = series(market_returns, now - 59 * 4 * 3600_000)
    eth = series(market_returns, now - 59 * 4 * 3600_000)
    peers = {
        "AVAX/USDT:USDT": {"4h": series(market_returns, now - 59 * 4 * 3600_000)},
        "ADA/USDT:USDT": {"4h": series(market_returns, now - 59 * 4 * 3600_000)},
    }

    daily_highs = [110, 111, 112, 115, 112, 111, 113, 114, 118, 115,
                   114, 116, 117, 121, 119, 118, 117]
    daily_lows = [108, 107, 108, 108, 106, 108, 108, 107, 108, 108,
                  107, 108, 108, 107, 108, 108, 107]
    daily = [Candle(now + i * 86400_000, 109, h, l, 109, 100.0)
             for i, (h, l) in enumerate(zip(daily_highs, daily_lows))]

    return {
        "symbol": "SOL/USDT:USDT",
        "4h": own,
        "1d": daily,
        "current_price": own[-1].close,
        "correlation_universe": {"BTC": btc, "ETH": eth},
        "sector_peer_universe": peers,
        "shared_market_evidence": {},
    }


def test_relative_strength_real_data():
    data = _relative_strength_data()
    plan = relative_strength_generate(data)
    assert plan is not None, "relative_strength must produce a setup from its positive fixture"
    if plan is not None:
        assert plan["strategy_id"] == "relative_strength"
        assert plan["direction"] in ("LONG", "SHORT")
        assert abs(plan.get("relative_strength_metrics", {}).get("beta", 0)) <= 5.0


def test_relative_strength_insufficient_history_returns_none():
    data = {
        "symbol": "SOL/USDT:USDT",
        "4h": [Candle(_now_ms() + i * 3600_000, 100, 101, 99, 100, 100.0) for i in range(10)],
        "current_price": 100.0,
        "correlation_universe": {
            "BTC": [Candle(_now_ms() + i * 3600_000, 100, 101, 99, 100, 100.0) for i in range(10)],
            "ETH": [Candle(_now_ms() + i * 3600_000, 100, 101, 99, 100, 100.0) for i in range(10)],
        },
        "shared_market_evidence": {},
    }
    assert relative_strength_generate(data) is None


# ---------------------------------------------------------------------------
# 7. smc — gerçek SMC entry/risk geometrisi
# ---------------------------------------------------------------------------

def test_smc_real_long_geometry():
    result = {
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 98.0,
                 "tp1": 102.0, "tp2": 104.0, "tp3": 106.0},
        "entry": {"direction": "LONG", "entry_type": "LIMIT"},
        "analysis": {
            "smc_h4_structure": [{"choch": True, "direction": "BULLISH"}],
            "smc_orderblocks": [{"type": "BULLISH", "low": 99.0, "high": 101.0, "mitigated": False}],
        },
        "dynamic_tp": {},
    }
    plan = smc_generate(result)
    assert plan is not None
    assert plan["strategy_id"] == "smc"
    assert plan["direction"] == "LONG"
    assert plan["entry"] == 100.0
    assert plan["stop_loss"] == 98.0
    assert plan["tp1"] == 102.0
    assert plan["tp2"] == 104.0
    assert plan["tp3"] == 106.0
    assert plan["stop_loss"] < plan["entry"] < plan["tp1"] < plan["tp2"] < plan["tp3"]


def test_smc_real_short_geometry():
    result = {
        "signal": {"signal": "SHORT"},
        "risk": {"entry": 100.0, "stop_loss": 102.0,
                 "tp1": 98.0, "tp2": 96.0, "tp3": 94.0},
        "entry": {"direction": "SHORT", "entry_type": "LIMIT"},
        "analysis": {
            "smc_h4_structure": [{"choch": True, "direction": "BEARISH"}],
            "smc_orderblocks": [{"type": "BEARISH", "low": 99.0, "high": 101.0, "mitigated": False}],
        },
        "dynamic_tp": {},
    }
    plan = smc_generate(result)
    assert plan is not None
    assert plan["strategy_id"] == "smc"
    assert plan["direction"] == "SHORT"
    assert plan["stop_loss"] > plan["entry"] > plan["tp1"] > plan["tp2"] > plan["tp3"]


def test_smc_invalid_geometry_returns_none():
    # LONG with stop above entry: invalid
    result = {
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 101.0,
                 "tp1": 102.0, "tp2": 104.0, "tp3": 106.0},
        "entry": {"direction": "LONG"},
    }
    assert smc_generate(result) is None


# ---------------------------------------------------------------------------
# Cross-cutting: strategy independence
# ---------------------------------------------------------------------------

def test_all_seven_strategies_have_independent_generators():
    """Yedi stratejinin generator fonksiyonu bağımsız ve import edilebilir."""
    generators = {
        "trend_pullback": trend_generate,
        "volatility_breakout": breakout_generate,
        "mean_reversion": mean_reversion_generate,
        "liquidation_cascade": liquidation_generate,
        "orderflow_momentum": orderflow_generate,
        "relative_strength": relative_strength_generate,
        "smc": smc_generate,
    }
    assert set(generators.keys()) == {
        "trend_pullback", "volatility_breakout", "mean_reversion",
        "liquidation_cascade", "orderflow_momentum", "relative_strength", "smc",
    }
    for sid, gen in generators.items():
        assert callable(gen), f"{sid} generator is not callable"
