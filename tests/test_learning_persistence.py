import json
import math

from learning_engine import LearningEngine


def test_learning_load_sanitizes_invalid_persisted_sections(tmp_path):
    path = tmp_path / "learning.json"
    path.write_text(
        json.dumps({"setups": ["bad"], "index": "bad", "meta": []}),
        encoding="utf-8",
    )
    engine = LearningEngine(path)
    assert engine.stats["setups"] == {}
    assert engine.stats["index"] == {}
    assert engine.stats["meta"] == {}


def test_learning_legacy_migration_skips_malformed_buckets(tmp_path):
    path = tmp_path / "learning.json"
    path.write_text(
        json.dumps({
            "setups": {
                "SHORT|EXPANSION|15M|fvg": "bad-bucket",
                "LONG|EXPANSION|15M|fvg": {
                    "total": "5",
                    "wins": "3",
                    "average_r": "nan",
                    "average_confidence": "inf",
                },
            }
        }),
        encoding="utf-8",
    )
    engine = LearningEngine(path)
    assert "setups" in engine.stats
    assert all(
        math.isfinite(float(metric))
        for bucket in engine.stats["index"].get("exact", {}).values()
        for metric in bucket.values()
        if isinstance(metric, (int, float))
    )


def test_learning_save_is_atomic_and_cleans_temporary_file(tmp_path):
    path = tmp_path / "learning.json"
    engine = LearningEngine(path)
    engine.record_closed_trade({
        "side": "LONG",
        "result": "WIN",
        "confidence": float("nan"),
        "metadata": {"setup_type": "market_structure"},
    })

    assert json.loads(path.read_text(encoding="utf-8"))["setups"]
    assert not list(tmp_path.glob("*.tmp"))
