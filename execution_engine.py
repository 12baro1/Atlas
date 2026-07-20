"""
Execution engine compatibility shim.
"""

from bybit_execution_engine import BybitExecutionEngine


class ExecutionEngine(BybitExecutionEngine):
    """Backward compatible alias for Bybit execution."""

    pass
