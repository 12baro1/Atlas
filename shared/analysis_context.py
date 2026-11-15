"""Per-analysis memoization for deterministic, strategy-neutral market analytics.

The cache lifetime is one SevenStrategyLab analysis call. It deliberately does
not persist across market snapshots, symbols, or analysis runs.
"""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
import math


_CURRENT_CONTEXT = ContextVar("atlas_analysis_context", default=None)


def _key_part(value):
    if value is None or isinstance(value, (str, bytes, int, bool)):
        return value
    if isinstance(value, float):
        return ("float", value.hex()) if math.isfinite(value) else ("float", repr(value))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(_key_part(item) for item in value))
    if isinstance(value, dict):
        return ("dict", tuple(sorted((str(key), _key_part(item)) for key, item in value.items())))
    # Candle/model instances are treated as immutable during one analysis pass.
    return ("identity", id(value))


class AnalysisContext:
    """A single-symbol, single-snapshot cache shared by all strategy generators."""

    def __init__(self):
        self._cache = {}
        self._token = None

    def __enter__(self):
        self._token = _CURRENT_CONTEXT.set(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._token is not None:
            _CURRENT_CONTEXT.reset(self._token)
            self._token = None
        self._cache.clear()
        return False

    def get_or_compute(self, key, compute):
        if key not in self._cache:
            self._cache[key] = compute()
        return self._cache[key]

    @property
    def computation_count(self):
        """Number of distinct cached computations, exposed for diagnostics/tests."""
        return len(self._cache)


def cached_analysis(function):
    """Memoize a pure analysis helper only while an AnalysisContext is active."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        context = _CURRENT_CONTEXT.get()
        if context is None:
            return function(*args, **kwargs)
        key = (function.__module__, function.__qualname__,
               _key_part(args), _key_part(kwargs))
        return context.get_or_compute(key, lambda: function(*args, **kwargs))
    return wrapped


def analysis_scope(function):
    """Give one top-level analysis call an isolated shared cache."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _CURRENT_CONTEXT.get() is not None:
            return function(*args, **kwargs)
        with AnalysisContext():
            return function(*args, **kwargs)
    return wrapped
