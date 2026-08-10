import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atlas_runtime import AtlasRuntime


@pytest.mark.skipif(not os.getenv("ATLAS_RUN_RUNTIME_HEAVY_TESTS"), reason="runtime test is heavy")
def test_runtime_manual_mode_ready_by_default():
    runtime = AtlasRuntime(symbols=[], full_scan=False)
    snap = runtime.snapshot()

    assert snap["scanner"]["mode"] == "MANUAL_ANALYSIS"
    assert snap["scanner"]["status"] == "READY"


@pytest.mark.skipif(not os.getenv("ATLAS_RUN_RUNTIME_HEAVY_TESTS"), reason="runtime test is heavy")
def test_runtime_normalize_symbol():
    runtime = AtlasRuntime(symbols=[], full_scan=False)

    assert runtime.normalize_symbol("btc") == "BTC/USDT:USDT"
    assert runtime.normalize_symbol("ETH/USDT") == "ETH/USDT:USDT"
    assert runtime.normalize_symbol("SOLUSDT") == "SOL/USDT:USDT"
