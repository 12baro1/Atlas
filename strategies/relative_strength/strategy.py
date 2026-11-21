import math


"""Independent beta-adjusted relative_strength setup generator."""

from shared.analysis_services import (
    _value,
    _series,
    _atr,
    _ema,
    _current_price,
    _entry_reference,
)
from shared.market_structure_services import volatility_regime
from shared.microstructure_services import beta_stability, relative_volume
from strategies.candidate import _raw_candidate
from shared.specialist_evidence import evidence_for_strategy, attach_strategy_evidence


def generate(data):
    specialist_evidence = evidence_for_strategy(data, "relative_strength")
    """Beta-adjusted relative strength versus market and optional sector peers."""
    candles = data.get("4h") or []
    closes = _series(candles)
    atr = _atr(candles)
    if len(closes) < 55 or atr is None:
        return None
    symbol = str(data.get("symbol") or "").upper()
    universe = data.get("correlation_universe") or {}
    benchmark_keys = ["ETH"] if symbol.startswith("BTC/") else ["BTC"] if symbol.startswith("ETH/") else ["BTC", "ETH"]

    def returns_by_time(series):
        output = {}
        for previous, current in zip(series, series[1:]):
            previous_close = _value(previous, "close")
            current_close = _value(current, "close")
            try:
                timestamp = int(current.time)
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
            if previous_close and current_close and previous_close > 0:
                value = current_close / previous_close - 1.0
                if math.isfinite(value):
                    output[timestamp] = value
        return output

    own_returns = returns_by_time(candles)
    benchmark_maps = []
    for benchmark_key in benchmark_keys:
        benchmark_candles = universe.get(benchmark_key) or []
        if len(benchmark_candles) < 55:
            return None
        benchmark_maps.append(returns_by_time(benchmark_candles))
    common_times = set(own_returns)
    for values in benchmark_maps:
        common_times.intersection_update(values)
    if len(common_times) < 48:
        return None

    market_by_time = {
        timestamp: sum(values[timestamp] for values in benchmark_maps) / len(benchmark_maps)
        for timestamp in common_times
    }
    sector_maps = []
    for frames in (data.get("sector_peer_universe") or {}).values():
        peer_candles = frames.get("4h") if isinstance(frames, dict) else frames
        if peer_candles and len(peer_candles) >= 55:
            sector_maps.append(returns_by_time(peer_candles))
    sector_coverage = {}
    if len(sector_maps) >= 2:
        for timestamp in common_times:
            peer_values = [values[timestamp] for values in sector_maps if timestamp in values]
            if len(peer_values) >= 2:
                sector_coverage[timestamp] = sum(peer_values) / len(peer_values)
    use_sector = len(sector_maps) >= 2 and len(sector_coverage) >= int(len(common_times) * 0.70)
    aligned_times = sorted(
        timestamp for timestamp in common_times
        if not use_sector or timestamp in sector_coverage
    )
    benchmark_returns = [
        0.70 * market_by_time[timestamp] + 0.30 * sector_coverage[timestamp]
        if use_sector else market_by_time[timestamp]
        for timestamp in aligned_times
    ]
    asset_returns = [own_returns[timestamp] for timestamp in aligned_times]
    if len(asset_returns) < 48:
        return None

    # Estimate beta over the prior 48 closed 4H return observations.
    beta_asset = asset_returns[-48:]
    beta_market = benchmark_returns[-48:]
    mean_asset = sum(beta_asset) / len(beta_asset)
    mean_market = sum(beta_market) / len(beta_market)
    variance = sum((value - mean_market) ** 2 for value in beta_market)
    if variance <= 1e-12:
        return None
    covariance = sum(
        (asset_value - mean_asset) * (market_value - mean_market)
        for asset_value, market_value in zip(beta_asset, beta_market)
    )
    beta = covariance / variance
    if not math.isfinite(beta) or abs(beta) > 5.0:
        return None

    residual_returns = [asset_value - beta * market_value
                        for asset_value, market_value in zip(asset_returns[-48:], benchmark_returns[-48:])]
    own_return_12 = sum(asset_returns[-12:])
    benchmark_return_12 = sum(benchmark_returns[-12:])
    residual_alpha = own_return_12 - beta * benchmark_return_12
    residual_alpha_6 = sum(residual_returns[-6:])
    residual_volatility = math.sqrt(sum(value * value for value in residual_returns) / len(residual_returns))
    alpha_signal = max(0.008, 0.55 * residual_volatility * math.sqrt(12.0))
    e20 = _ema(closes, 20)
    e20_previous = _ema(closes[:-3], 20)
    if e20 is None or e20_previous is None:
        return None
    direction = (
        "LONG" if residual_alpha >= alpha_signal and residual_alpha_6 > 0
        and closes[-1] > e20 and e20 > e20_previous
        else "SHORT" if residual_alpha <= -alpha_signal and residual_alpha_6 < 0
        and closes[-1] < e20 and e20 < e20_previous
        else None
    )
    if not direction:
        return None
    entry = _current_price(data)
    if entry is None or (direction == "LONG" and entry <= e20) or (direction == "SHORT" and entry >= e20):
        return None
    # Do not chase an already-extended 4H trend at market. The raw strategy
    # can still report its relative-strength evidence, but entry timing must
    # remain near the trend baseline; the common selector handles final risk.
    extension_atr = abs(entry - e20) / atr if atr > 0 else float("inf")
    # Overextension is advisory: preserve independent setup generation and
    # let the common quality gate and final selector decide execution.
    
    # _valid_plan in common filter computes structural stop; pass dummy stop (ignored)
    dummy_stop = entry - atr if direction == "LONG" else entry + atr
    stability = beta_stability(asset_returns, benchmark_returns, 24)
    volume_evidence = relative_volume(
        _value(candles[-1], "volume"),
        [_value(x, "volume") for x in candles[-21:-1]],
    )
    # These are quality evidence, not mandatory entry conditions.
    # Unavailable observations are neutral rather than fabricated.
    evidence_delta = -min(18.0, max(0.0, extension_atr - 2.0) * 6.0)
    if stability.get("state") == "UNSTABLE":
        evidence_delta -= 9.0
    elif stability.get("state") == "STABLE":
        evidence_delta += 3.0
    if volume_evidence.get("state") == "LOW":
        evidence_delta -= 5.0
    elif volume_evidence.get("state") == "HIGH":
        evidence_delta += 3.0
    # A recent alpha close to zero is weaker than one that persists.
    if abs(residual_alpha_6) < abs(residual_alpha) * 0.15:
        evidence_delta -= 5.0
    strength = max(0.0, min(90.0, 64.0 + min(abs(residual_alpha) * 450.0, 22.0) + min(abs(beta) * 2.0, 4.0) + evidence_delta))
    plan = _raw_candidate(direction, entry, dummy_stop, atr, "relative_strength", strength, entry_reference=_entry_reference(data))
    if plan:
        benchmark_label = "/".join(benchmark_keys)
        sector_label = f" + sector peers ({len(sector_maps)})" if use_sector else ""
        plan["reasons"] = [
            f"12x4H beta-adjusted residual alpha={residual_alpha * 100:+.2f}% (required {alpha_signal * 100:.2f}%)",
            f"Recent 6x4H residual alpha={residual_alpha_6 * 100:+.2f}%",
            f"Estimated beta={beta:.2f} vs {benchmark_label}{sector_label}",
            f"EMA20 slope={(e20 - e20_previous) / atr:.2f} ATR; absolute trend confirmation",
        ]
        plan["relative_strength_metrics"] = {
            "beta": round(beta, 4),
            "entry_extension_atr": round(extension_atr, 4),
            "residual_alpha_12x4h": round(residual_alpha, 6),
            "residual_alpha_6x4h": round(residual_alpha_6, 6),
            "required_alpha_12x4h": round(alpha_signal, 6),
            "residual_volatility_4h": round(residual_volatility, 6),
            "market_return_12x4h": round(benchmark_return_12, 6),
            "sector_peers_used": len(sector_maps) if use_sector else 0,
            "beta_stability": stability,
            "relative_volume": volume_evidence,
            "evidence_strength_adjustment": evidence_delta,
            "volatility_regime": volatility_regime(candles),
        }
    if plan:
        attach_strategy_evidence(plan, specialist_evidence)
    return plan
