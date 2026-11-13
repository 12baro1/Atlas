"""Shared execution-cost model for USDT perpetual backtests and risk sizing.

Rates are fractions of executed notional and apply per filled leg. LIMIT fills
are modeled as maker; MARKET and stop exits are taker. Spread/slippage proxies
are charged only on market-executed legs. Funding is intentionally not modeled.
"""
import math


def _rate(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def _price(value):
    try:
        number = abs(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _weights(targets, weights):
    available = [(str(key), _price(value)) for key, value in (targets or {}).items()
                 if value is not None and _price(value) > 0]
    if not available:
        return []
    parsed = []
    for key, _ in available:
        try:
            weight = float((weights or {}).get(key, 1.0))
        except (TypeError, ValueError, OverflowError):
            weight = 0.0
        parsed.append(weight if math.isfinite(weight) and weight > 0 else 0.0)
    total = sum(parsed)
    if total <= 0:
        parsed = [1.0] * len(available)
        total = float(len(available))
    return [(key, price, weight / total)
            for (key, price), weight in zip(available, parsed)]


def _leg(price, order_type, maker_fee_rate, taker_fee_rate,
         spread_rate, slippage_rate):
    order = str(order_type or "MARKET").upper()
    market = order in {"MARKET", "MARKET_FALLBACK", "MARKETABLE_LIMIT", "TAKER", "STOP", "TRAILING_STOP"}
    fee_rate = _rate(taker_fee_rate if market else maker_fee_rate)
    notional = _price(price)
    fee = notional * fee_rate
    spread = notional * _rate(spread_rate) if market else 0.0
    slippage = notional * _rate(slippage_rate) if market else 0.0
    return {
        "fee": fee,
        "spread": spread,
        "slippage": slippage,
        "total": fee + spread + slippage,
        "fee_rate": fee_rate,
        "execution_type": "TAKER" if market else "MAKER",
    }


def estimate_plan_cost(entry_price, targets, weights, entry_type="LIMIT",
                       maker_fee_rate=0.0002, taker_fee_rate=0.00055,
                       spread_rate=0.0002, slippage_rate=0.0003):
    """Expected fee drag for weighted TP exits, in quote units per unit size."""
    entry = _leg(entry_price, entry_type, maker_fee_rate, taker_fee_rate,
                 spread_rate, slippage_rate)
    exits = _weights(targets, weights)
    exit_fee = sum(price * weight * _rate(maker_fee_rate)
                   for _, price, weight in exits)
    total = entry["total"] + exit_fee
    return {
        "total": total,
        "entry_fee": entry["fee"],
        "exit_fee": exit_fee,
        "spread": entry["spread"],
        "slippage": entry["slippage"],
        "entry_execution_type": entry["execution_type"],
        "exit_execution_type": "MAKER",
    }


def estimate_stop_cost(entry_price, stop_price, entry_type="LIMIT",
                       maker_fee_rate=0.0002, taker_fee_rate=0.00055,
                       spread_rate=0.0002, slippage_rate=0.0003):
    """Worst-case round trip: planned entry followed by a market stop exit."""
    entry = _leg(entry_price, entry_type, maker_fee_rate, taker_fee_rate,
                 spread_rate, slippage_rate)
    exit_leg = _leg(stop_price, "STOP", maker_fee_rate, taker_fee_rate,
                    spread_rate, slippage_rate)
    return {
        "total": entry["total"] + exit_leg["total"],
        "entry_fee": entry["fee"],
        "exit_fee": exit_leg["fee"],
        "spread": entry["spread"] + exit_leg["spread"],
        "slippage": entry["slippage"] + exit_leg["slippage"],
    }


def realized_trade_cost(entry_price, exit_price, entry_type, exit_reason,
                        targets, reached_levels=None, tp_weights=None,
                        partial_exits=True, maker_fee_rate=0.0002,
                        taker_fee_rate=0.00055, spread_rate=0.0002,
                        slippage_rate=0.0003):
    """Actual modeled cost for the fills recorded by the OHLCV simulator."""
    entry = _leg(entry_price, entry_type, maker_fee_rate, taker_fee_rate,
                 spread_rate, slippage_rate)
    reason = str(exit_reason or "").upper()
    target_map = {f"tp{i}": _price((targets or [None, None, None])[i - 1])
                  for i in range(1, 4)
                  if len(targets or []) >= i and (targets or [None] * 3)[i - 1] is not None}
    normalized = _weights(target_map, tp_weights)
    levels = {int(level) for level in (reached_levels or []) if str(level).isdigit()}
    if not levels and reason.startswith("TP"):
        try:
            levels.add(int(reason[2:]))
        except (TypeError, ValueError):
            pass

    exit_fee = 0.0
    exit_spread = 0.0
    exit_slippage = 0.0
    closed_fraction = 0.0

    if partial_exits and normalized:
        for key, price, weight in normalized:
            try:
                level = int(key[2:])
            except (TypeError, ValueError):
                continue
            if level in levels:
                closed_fraction += weight
                exit_fee += price * weight * _rate(maker_fee_rate)

    remaining = max(0.0, 1.0 - closed_fraction)
    if not partial_exits:
        remaining = 1.0
        exit_fee = 0.0
    if remaining > 1e-9:
        market_exit = reason in {"STOP", "TRAILING_STOP"} or not reason.startswith("TP")
        exit_order = "STOP" if market_exit else "LIMIT"
        exit_leg = _leg(exit_price, exit_order, maker_fee_rate, taker_fee_rate,
                        spread_rate, slippage_rate)
        exit_fee += _price(exit_price) * remaining * (
            _rate(taker_fee_rate) if market_exit else _rate(maker_fee_rate)
        )
        exit_spread += exit_leg["spread"] * remaining
        exit_slippage += exit_leg["slippage"] * remaining

    total = entry["total"] + exit_fee + exit_spread + exit_slippage
    return {
        "total": total,
        "entry_fee": entry["fee"],
        "exit_fee": exit_fee,
        "spread": entry["spread"] + exit_spread,
        "slippage": entry["slippage"] + exit_slippage,
        "entry_execution_type": entry["execution_type"],
        "exit_execution_type": "TAKER" if exit_spread or exit_slippage or reason in {"STOP", "TRAILING_STOP"} else "MAKER",
    }
