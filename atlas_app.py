"""Atlas CLI entrypoint and full-screen TUI launcher."""

from __future__ import annotations

import argparse
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

from config import Config
from data_engine import ccxt, exchange
from universe_engine import select_symbols

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


def _select_symbols():
    Config.refresh_from_env()
    markets = exchange.load_markets()
    symbols, stats = select_symbols(
        markets=markets,
        suffix="/USDT:USDT",
        require_active=True,
        require_swap=False,
        max_symbols=int(os.getenv("ATLAS_MAX_SYMBOLS", "0").strip() or 0),
    )

    backend = getattr(ccxt, "BACKEND", "unknown")
    if backend == "mock":
        allow_mock = os.getenv("ATLAS_ALLOW_MOCK", "0").strip().lower() in {"1", "true", "yes"}
        if not allow_mock:
            raise RuntimeError(
                "ccxt mock backend aktif. Canli tarama icin once `python3 -m pip install ccxt` calistirin. "
                "Sadece test/offline icin `ATLAS_ALLOW_MOCK=1 atlas` kullanin."
            )
        LOGGER.warning("ccxt mock backend aktif (ATLAS_ALLOW_MOCK=1).")
    LOGGER.info(
        "Sembol secimi | backend=%s toplam=%s kalan=%s suffix_elendi=%s inactive_elendi=%s cap_elendi=%s",
        backend,
        stats.get("total_markets"),
        stats.get("kept"),
        stats.get("skipped_suffix"),
        stats.get("skipped_inactive"),
        stats.get("limited"),
    )
    return symbols


def _normalize_cli_symbol(raw_symbol):
    text = str(raw_symbol or "").strip().upper()
    if not text:
        return None
    text = text.replace(" ", "")
    if "/" in text and ":" in text:
        return text
    if "/" in text and ":" not in text:
        left, right = text.split("/", 1)
        if right == "USDT":
            return f"{left}/USDT:USDT"
        return text
    if text.endswith(":USDT") and "/" not in text:
        base = text[:-5]
        if base:
            return f"{base}/USDT:USDT"
    if text.endswith("USDT") and "/" not in text and len(text) > 4:
        return f"{text[:-4]}/USDT:USDT"
    if text.isalpha() and 2 <= len(text) <= 12:
        return f"{text}/USDT:USDT"
    return text


def _build_telegram_service(runtime):
    if not (bool(getattr(Config, "TELEGRAM_POLLING_ENABLED", True)) or bool(getattr(Config, "TELEGRAM_WEBHOOK_ENABLED", False))):
        return None
    try:
        from telegram_auth import TelegramAuthService
        from telegram_auth_store import TelegramAuthStore
        from telegram_service import TelegramService, TelegramTradeCommandHandler
        from telegram_webhook import TelegramWebhookHandler

        store = TelegramAuthStore(Config.TELEGRAM_AUTH_DB_FILE)
        auth = TelegramAuthService(
            store=store,
            password=Config.BOT_PASSWORD,
            password_hash=Config.BOT_PASSWORD_HASH,
            admin_ids=Config.TELEGRAM_ADMIN_IDS,
        )
        trade_handler = TelegramTradeCommandHandler(manual_trade_service=runtime.manual_service)
        webhook_handler = TelegramWebhookHandler(trade_command_handler=trade_handler)
        service = TelegramService(
            auth_service=auth,
            webhook_handler=webhook_handler,
            trade_command_handler=trade_handler,
            manual_trade_service=runtime.manual_service,
        )
        return service
    except Exception:
        LOGGER.exception("Telegram service init failed")
        return None


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
    os.environ.setdefault("ATLAS_CONSOLE_SIGNAL_PRINT_ENABLED", "0")
    Config.refresh_from_env()

    symbols = []
    if full_scan:
        symbols = _select_symbols()
        if not symbols:
            print("Taranacak sembol bulunamadi.")
            return 1

    runtime = AtlasRuntime(symbols=symbols, full_scan=full_scan)
    service = _build_telegram_service(runtime)
    if service is not None:
        service.start(daemon=True)
        runtime.attach_telegram_service(service)

    runtime.start(daemon=True)

    app = AtlasTUIApp(runtime, initial_symbol=_normalize_cli_symbol(initial_symbol))
    try:
        app.run()
        return 0
    finally:
        runtime.stop()


def build_parser():
    parser = argparse.ArgumentParser(prog="atlas", description="Atlas terminal application")
    parser.add_argument("symbol", nargs="?", help="start TUI and analyze this symbol first (e.g. BTC or BTC/USDT:USDT)")
    parser.add_argument("--background", action="store_true", help="run scanner in background via run_bot.sh")
    parser.add_argument("--stop", action="store_true", help="stop background scanner")
    parser.add_argument("--status", action="store_true", help="background scanner status")
    parser.add_argument("--restart", action="store_true", help="restart background scanner")
    parser.add_argument("--logs", action="store_true", help="show background logs")
    parser.add_argument("--full-scan", action="store_true", help="start TUI with continuous full market scan")
    parser.add_argument("--install-cli", action="store_true", help="install atlas command into ~/.local/bin")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.install_cli:
        return install_cli()
    if args.background:
        return _run_bot_script("start")
    if args.stop:
        return _run_bot_script("stop")
    if args.status:
        return _run_bot_script("status")
    if args.restart:
        return _run_bot_script("restart")
    if args.logs:
        return _run_bot_script("logs", "-f")

    return run_tui(initial_symbol=args.symbol, full_scan=args.full_scan)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
