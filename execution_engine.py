"""
execution_engine.py
Geriye dönük uyumluluk katmanı: BybitExecutionEngine alias'ı.
Yeni kod doğrudan bybit_execution_engine modülünü kullanmalıdır.
"""

from bybit_execution_engine import BybitExecutionEngine

__all__ = ["BybitExecutionEngine", "ExecutionEngine"]


class ExecutionEngine(BybitExecutionEngine):
    """Geriye dönük uyumluluk alias'ı."""
