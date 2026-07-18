"""Utilities for building the tradable symbol universe."""


def select_symbols(markets, suffix="/USDT:USDT", require_active=True, require_swap=False, max_symbols=0):
    """Return sorted symbol list with filter diagnostics.

    Args:
        markets: Mapping of market symbol -> metadata.
        suffix: Required symbol suffix. Use None/"" to disable suffix filter.
        require_active: Keep only active markets when metadata is available.
        require_swap: Keep only swap markets when metadata is available.
        max_symbols: Hard cap after sorting. 0 means unlimited.
    """
    stats = {
        "total_markets": 0,
        "kept": 0,
        "skipped_suffix": 0,
        "skipped_inactive": 0,
        "skipped_not_swap": 0,
        "limited": 0,
    }

    symbols = []

    for symbol, meta in (markets or {}).items():
        stats["total_markets"] += 1

        if suffix and not str(symbol).endswith(suffix):
            stats["skipped_suffix"] += 1
            continue

        if isinstance(meta, dict):
            if require_active and not meta.get("active", True):
                stats["skipped_inactive"] += 1
                continue

            if require_swap and not meta.get("swap", False):
                stats["skipped_not_swap"] += 1
                continue

        symbols.append(symbol)

    symbols.sort()

    if max_symbols and max_symbols > 0 and len(symbols) > max_symbols:
        stats["limited"] = len(symbols) - max_symbols
        symbols = symbols[:max_symbols]

    stats["kept"] = len(symbols)
    return symbols, stats
