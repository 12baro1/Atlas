import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_atlas_tui_importable_when_textual_available():
    pytest.importorskip("textual")

    import atlas_tui  # noqa: F401

    assert hasattr(atlas_tui, "AtlasTUIApp")
