import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.swing_engine import Swing
from utils.structure_labels import label_swings


def test_label_swings_identifies_higher_highs_and_lower_lows():
    swings = [
        Swing(1, 10.0, "HIGH"),
        Swing(2, 8.0, "LOW"),
        Swing(3, 12.0, "HIGH"),
        Swing(4, 7.0, "LOW"),
    ]

    labels = label_swings(swings)

    assert [item["label"] for item in labels] == ["H?", "L?", "HH", "LL"]
    assert [item["type"] for item in labels] == ["HIGH", "LOW", "HIGH", "LOW"]
