"""Atlas CLI entrypoint for the terminal-only command screen."""

from __future__ import annotations

import argparse
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

from config import Config
from data_engine import ccxt


LOGGER = logging.getLogger("atlas.app")


def _repo_root():
    return Path(__file__).resolve().parent


def _run_bot_script(*args):
    script = _repo_root() / "run_bot.sh"
    command = [str(script), *args]
    return subprocess.run(command, cwd=str(_repo_root()), check=False).returncode


def install_cli():
    source = _repo_root() / "atlas"
    if not source.exists():
        raise RuntimeError(f"launcher not found: {source}")

    source.chmod(source.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    bin_dir = Path.home() / ".local" / "bin"
    target = bin_dir / "atlas"
    bin_dir.mkdir(parents=True, exist_ok=True)

    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(source)

    _ensure_path_in_shell_rc(bin_dir)
    print(f"Installed: {target}")
    print("Restart terminal or run: source ~/.bashrc")
    print("Then verify: which atlas")
    return 0


def _ensure_path_in_shell_rc(bin_dir):
    export_line = 'export PATH="$HOME/.local/bin:$PATH"\n'
    for rc_name in (".bashrc", ".profile", ".zshrc"):
        rc_path = Path.home() / rc_name
        try:
            if rc_path.exists():
                content = rc_path.read_text(encoding="utf-8")
                if ".local/bin" in content:
                    continue
            with rc_path.open("a", encoding="utf-8") as handle:
                handle.write("\n# Atlas CLI\n")
                handle.write(export_line)
        except Exception:
            continue


def run_tui(initial_symbol=None, full_scan=False):
    try:
        from atlas_runtime import AtlasRuntime
        from atlas_tui import AtlasTUIApp
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            print("Textual kurulu degil. Lutfen calistirin: python3 -m pip install textual")
            return 2
        raise

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    # Terminal-only product: no AI model startup and no Telegram notifications.
    os.environ["ATLAS_CONSOLE_SIGNAL_PRINT_ENABLED"] = "0"
    Config.refresh_from_env()
    Config.TELEGRAM_ENABLED = False
    Config.TELEGRAM_POLLING_ENABLED = False
    Config.TELEGRAM_WEBHOOK_ENABLED = False
    Config.TELEGRAM_BOT_TOKEN = ""
    Config.TELEGRAM_CHAT_ID = ""

    runtime = AtlasRuntime(symbols=[], full_scan=False)
    app = AtlasTUIApp(runtime, initial_symbol=initial_symbol)
    try:
        app.run()
        return 0
    finally:
        runtime.stop()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="Atlas terminal-only SMC analysis. No AI chat, Telegram, or exchange execution.",
    )
    parser.add_argument(
        "symbol",
        nargs="?",
        default=None,
        help="optional coin to analyze immediately (e.g. BRC, BTC, ETH); omit to open the command screen",
    )
    parser.add_argument("--install-cli", action="store_true", help="install atlas command into ~/.local/bin")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.install_cli:
        return install_cli()
    return run_tui(initial_symbol=args.symbol)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
