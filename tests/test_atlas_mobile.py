import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atlas_mobile


def test_help_command_does_not_initialize_runtime():
    result = atlas_mobile.analyze_command("yardım")
    assert result["ok"] is True
    assert result["kind"] == "help"
    assert "emir göndermez" in result["message"].lower()


def test_mobile_static_assets_exist():
    root = Path(atlas_mobile.__file__).resolve().parent / "mobile"
    assert (root / "index.html").is_file()
    assert (root / "manifest.webmanifest").is_file()
    assert (root / "sw.js").is_file()


def test_mobile_manifest_is_installable_web_app():
    root = Path(atlas_mobile.__file__).resolve().parent / "mobile"
    manifest = json.loads((root / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "Atlas Mobile"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
