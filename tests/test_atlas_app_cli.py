import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atlas_app
from atlas_app import build_parser, install_cli


def test_parser_background_flag():
    parser = build_parser()
    args = parser.parse_args(["--background"])
    assert args.background is True
    assert args.stop is False


def test_parser_symbol_and_full_scan_flags():
    parser = build_parser()
    args = parser.parse_args(["BTC", "--full-scan"])
    assert args.symbol == "BTC"
    assert args.full_scan is True


def test_main_passes_symbol_to_tui(monkeypatch):
    captured = {}

    def _fake_run_tui(initial_symbol=None, full_scan=False):
        captured["initial_symbol"] = initial_symbol
        captured["full_scan"] = full_scan
        return 7

    monkeypatch.setattr(atlas_app, "run_tui", _fake_run_tui)
    code = atlas_app.main(["BTC/USDT:USDT"])

    assert code == 7
    assert captured["initial_symbol"] == "BTC/USDT:USDT"
    assert captured["full_scan"] is False


def test_install_cli_creates_symlink(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))

    rc_file = home / ".bashrc"
    rc_file.write_text("# test rc\n", encoding="utf-8")

    source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas")
    assert os.path.exists(source)

    code = install_cli()
    assert code == 0

    target = home / ".local" / "bin" / "atlas"
    assert target.exists()
    assert target.is_symlink()

    mode = os.stat(source).st_mode
    assert mode & stat.S_IXUSR
