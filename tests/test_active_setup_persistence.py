import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from state_engine import StateEngine


class ActiveSetupPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "atlas_state.json"
        self.engine = StateEngine(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def result(side="LONG", stop=95.0, tp3=115.0):
        return {
            "signal": {"signal": side, "confidence": 80},
            "risk": {"entry": 100.0, "stop_loss": stop, "tp1": 105.0, "tp2": 110.0, "tp3": tp3},
            "decision": {"action": "EXECUTE"},
            "dynamic_tp": {"tp3": tp3},
            "analysis": {"setup_quality": {"setup_fingerprint": "stable-setup"}},
        }

    def test_active_setup_survives_engine_restart(self):
        self.engine.store_active_setup("BTC/USDT:USDT", self.result())
        restored = StateEngine(self.path).get_active_setup("BTC/USDT:USDT")
        self.assertIsNotNone(restored)
        self.assertEqual(restored["signal"]["signal"], "LONG")
        self.assertTrue(restored["decision"]["active_setup_restored"])

    def test_active_setup_is_retained_when_no_exit_level_is_hit(self):
        self.engine.store_active_setup("BTC/USDT:USDT", self.result())
        candle = SimpleNamespace(time=9999999999999, high=104.0, low=98.0)
        restored = self.engine.get_active_setup("BTC/USDT:USDT", candles=[candle])
        self.assertIsNotNone(restored)

    def test_stop_hit_clears_active_setup(self):
        self.engine.store_active_setup("BTC/USDT:USDT", self.result())
        candle = SimpleNamespace(time=9999999999999, high=101.0, low=94.0)
        self.assertIsNone(self.engine.get_active_setup("BTC/USDT:USDT", candles=[candle]))
        self.assertIsNone(self.engine.state["active_setups"].get("BTC/USDT:USDT"))

    def test_final_target_hit_clears_active_setup(self):
        self.engine.store_active_setup("BTC/USDT:USDT", self.result())
        candle = SimpleNamespace(time=9999999999999, high=116.0, low=99.0)
        self.assertIsNone(self.engine.get_active_setup("BTC/USDT:USDT", candles=[candle]))

    def test_non_executable_analysis_does_not_create_active_setup(self):
        result = self.result()
        result["decision"]["action"] = "SKIP"
        self.assertIsNone(self.engine.store_active_setup("BTC/USDT:USDT", result))


if __(!__name__ == "__main__"):
    unittest.main()
