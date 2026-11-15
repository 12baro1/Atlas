"""On-demand Telegram command interface for the headless Atlas service.

Only messages from the configured group are considered. The bot never pushes
signals or scan results on its own; it replies only to recognized commands.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from types import SimpleNamespace

import requests

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 3900


def normalize_command(value: str) -> str:
    """Normalize plain text and /commands addressed to this bot."""
    command = " ".join(str(value or "").strip().split())
    if command.startswith("/"):
        command = command[1:].split("@", 1)[0]
    return command.strip()


def split_message(value: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    text = str(value or "")
    if not text:
        return [""]
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def is_recognized_command(command: str) -> bool:
    """Use the same command grammar as the terminal UI."""
    from atlas_tui import (
        _is_report_command,
        _is_symbol_input,
        _parse_liquidity_command,
        _parse_scan_command,
    )

    normalized = normalize_command(command).lower()
    if normalized in {"yardım", "yardim", "help", "?"}:
        return True
    return (
        _is_report_command(normalized)
        or _parse_liquidity_command(normalized) is not False
        or _parse_scan_command(normalized) is not None
        or _is_symbol_input(normalized)
    )


class TelegramCommandService:
    """Long-poll Telegram and execute recognized commands against one runtime."""

    def __init__(self, runtime, token: str, chat_id: str, logger=None):
        self.runtime = runtime
        self.token = str(token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.logger = logger or logging.getLogger("atlas.telegram.commands")
        self.stop_flag = threading.Event()
        self._thread = None
        self._offset = None
        self._session = requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def start(self) -> bool:
        if not self.enabled:
            self.logger.info("Telegram command interface disabled: token or group chat ID missing")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self.stop_flag.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="atlas-telegram-commands",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self, timeout: float = 25.0) -> None:
        self.stop_flag.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.0, float(timeout)))
        self._session.close()

    def _api(self, method: str, payload: dict, timeout=25):
        response = self._session.post(
            f"{TELEGRAM_API}/bot{self.token}/{method}",
            json=payload,
            timeout=(5, timeout),
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(str(result.get("description") or "Telegram API request failed"))
        return result.get("result")

    def _poll_loop(self) -> None:
        self.logger.info("Telegram command polling started for configured group")
        while not self.stop_flag.is_set():
            try:
                updates = self._api(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": 15,
                        "allowed_updates": ["message"],
                    },
                    timeout=20,
                ) or []
                for update in updates:
                    self._offset = int(update.get("update_id", 0)) + 1
                    if self.stop_flag.is_set():
                        break
                    self._handle_update(update)
            except requests.RequestException as exc:
                self.logger.warning("Telegram polling network error: %s", exc)
                self.stop_flag.wait(3)
            except Exception:
                self.logger.exception("Telegram polling error")
                self.stop_flag.wait(3)
        self.logger.info("Telegram command polling stopped")

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if str(chat.get("id", "")) != self.chat_id or sender.get("is_bot"):
            return
        command = normalize_command(message.get("text") or "")
        if not command or not is_recognized_command(command):
            return
        self.logger.info("Telegram command received: %s", command[:80])
        try:
            result = self.execute_command(command)
        except Exception:
            self.logger.exception("Telegram command failed: %s", command[:80])
            result = "Komut işlenirken hata oluştu. VPS günlüklerini kontrol et."
        for part in split_message(result):
            if self.stop_flag.is_set():
                break
            try:
                self._api(
                    "sendMessage",
                    {"chat_id": self.chat_id, "text": part, "disable_web_page_preview": True},
                    timeout=10,
                )
            except Exception:
                self.logger.exception("Telegram command reply could not be sent")
                break

    def execute_command(self, command: str) -> str:
        """Run the existing TUI command operations without creating a second runtime."""
        from atlas_tui import (
            AtlasTUIApp,
            _is_report_command,
            _parse_liquidity_command,
            _parse_scan_command,
        )
        from utils.signal_card import build_signal_card, format_card_text

        normalized = normalize_command(command)
        lowered = normalized.lower()
        if lowered in {"yardım", "yardim", "help", "?"}:
            return (
                "ATLAS KOMUTLARI\n"
                "BTC / ETH / SOL — 7 strateji analizi\n"
                "en iyi 5 işlem — en iyi 5 kurulumu tara\n"
                "50 analiz et — 50 piyasayı tara\n"
                "tüm piyasayı tara — desteklenen tüm USDT perpetual piyasaları\n"
                "likidite BTC — BTC likidite haritası\n"
                "performans — kayıtlı performans\n"
                "öğrenme — öğrenme verisi\n"
                "yardım — komutları göster\n\n"
                "Atlas otomatik emir göndermez. Otomatik Telegram sinyal bildirimi kapalıdır."
            )

        # The formatter and scan implementation are reused from the TUI. This
        # lightweight adapter deliberately suppresses terminal-only progress UI.
        adapter = SimpleNamespace(
            runtime=self.runtime,
            _show=lambda _message: None,
            call_from_thread=lambda callback, *args, **kwargs: callback(*args, **kwargs),
        )
        scan_request = _parse_scan_command(lowered)
        liquidity_symbol = _parse_liquidity_command(normalized)
        if _is_report_command(normalized):
            return AtlasTUIApp._format_performance(adapter, normalized)
        if liquidity_symbol is not False:
            symbol = liquidity_symbol or self.runtime.current_symbol()
            if not symbol:
                return "KULLANIM: likidite BTC"
            outcome = self.runtime.analyze_symbol(symbol, force_refresh=True)
            return (
                AtlasTUIApp._format_liquidity(adapter, outcome)
                if outcome.get("ok")
                else f"{symbol} likidite analizi yapılamadı: {outcome.get('error')}"
            )
        if scan_request is not None:
            return AtlasTUIApp._find_best_trade(adapter, *scan_request)

        outcome = self.runtime.analyze_symbol(normalized, force_refresh=True)
        if not outcome.get("ok"):
            return (
                f"{normalized.upper()} ANALİZ EDİLEMEDİ\n\n"
                f"Neden: {outcome.get('error', 'bilinmeyen hata')}\n"
                "Sembolün USDT perpetual piyasasında bulunduğunu kontrol et."
            )
        strategy_report = (outcome.get("result") or {}).get("strategy_lab")
        if isinstance(strategy_report, dict):
            return AtlasTUIApp._format_strategy_report(adapter, outcome)
        card = build_signal_card(outcome["result"])
        action = str(card.get("decision_action") or "").upper()
        direction = card.get("direction") in {"LONG", "SHORT"}
        entry_type = str(card.get("entry_type") or "").upper()
        has_levels = bool(card.get("entry")) and bool(card.get("stop_loss")) and bool(card.get("tp_levels"))
        executable = (
            action in {"EXECUTE", "EXECUTE_WITH_CAUTION"}
            and direction
            and entry_type in {"MARKET", "LIMIT"}
            and has_levels
        )
        result = format_card_text(card) if executable else "Şu an girilebilir MARKET/LIMIT sinyali yok."
        return f"{result}\n\nAnaliz süresi: {outcome.get('elapsed_ms', 0) / 1000:.1f} sn"


def create_telegram_command_service(runtime, logger=None):
    """Build the opt-in command service from environment configuration."""
    enabled = os.getenv("ATLAS_TELEGRAM_COMMANDS_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if not enabled:
        return None
    token = os.getenv("ATLAS_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("ATLAS_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "ATLAS_TELEGRAM_COMMANDS_ENABLED=1 requires "
            "ATLAS_TELEGRAM_BOT_TOKEN and ATLAS_TELEGRAM_CHAT_ID"
        )
    return TelegramCommandService(runtime, token, chat_id, logger=logger)
