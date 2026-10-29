import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atlas_app
from atlas_app import build_parser, install_cli


def test_parser_opens_command_screen_without_default_symbol(monkeypatch):
    monkeypatch.delenv("ATLAS_DEFAULT_SYMBOL", raising=False)
    args = build_parser().parse_args([])
    assert args.symbol is None


def test_parser_accepts_symbol_for_immediate_analysis():
    args = build_parser().parse_args(["BRC"])
    assert args.symbol == "BRC"


def test_parser_has_only_cli_install_option():
    options = {option for action in build_parser()._actions for option in action.option_strings}
    assert "--install-cli" in options
    assert "--background" not in options
    assert "--full-scan" not in options
    assert "--status" not in options


def test_main_passes_symbol_to_tui(monkeypatch):
    captured = {}

    def _fake_run_tui(initial_symbol=None):
        captured["initial_symbol"] = initial_symbol
        return 7

    monkeypatch.setattr(atlas_app, "run_tui", _fake_run_tui)
    code = atlas_app.main(["BRC"])

    assert code == 7
    assert captured["initial_symbol"] == "BRC"


def test_main_opens_empty_command_screen(monkeypatch):
    captured = {}

    def _fake_run_tui(initial_symbol=None):
        captured["initial_symbol"] = initial_symbol
        return 0

    monkeypatch.setattr(atlas_app, "run_tui", _fake_run_tui)
    assert atlas_app.main([]) == 0
    assert captured["initial_symbol"] is None


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
