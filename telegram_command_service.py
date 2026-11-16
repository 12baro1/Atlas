"""On-demand Telegram command interface for the headless Atlas service.

Only messages from the configured group are considered. The bot never pushes
signals or scan results on its own; it replies only to recognized commands.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

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


def _format_rr(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "0.00R"
    return f"{number:+.2f}R"


def format_daily_signal_report(outcomes, now=None):
    """Render only the current Europe/Istanbul day; historical rows stay in SQLite."""
    tz = ZoneInfo("Europe/Istanbul")
    current = now.astimezone(tz) if now is not None else datetime.now(tz)
    today = current.date()
    daily = []
    for item in outcomes or []:
        try:
            stamp = int(item.get("opened_at") or 0)
            if stamp < 100_000_000_000:
                stamp *= 1000
            opened = datetime.fromtimestamp(stamp / 1000, tz=tz)
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        if opened.date() == today:
            daily.append(item)

    if not daily:
        return f"ATLAS | GÜNLÜK İŞLEMLER\n{today:%d.%m.%Y}\n\nBugün henüz kayıtlı setup yok."

    terminal = {"TP1", "TP2", "TP3", "SL"}
    tracking = []
    waiting = []
    no_entry = []
    completed = []
    expired_after_entry = []
    for item in sorted(daily, key=lambda row: int(row.get("opened_at") or 0)):
        status = str(item.get("status") or "PENDING").upper()
        reached = bool(item.get("entry_reached", status in terminal))
        if status in terminal:
            completed.append(item)
        elif status == "EXPIRED":
            (expired_after_entry if reached else no_entry).append(item)
        elif status == "PENDING":
            (tracking if reached else waiting).append(item)

    def describe(item, state=None):
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        strategy = payload.get("strategy") or payload.get("strategy_id") or payload.get("setup_type")
        label = f" | {strategy}" if strategy else ""
        status = state or str(item.get("status") or "PENDING").upper()
        rr = _format_rr(item.get("realized_r") or 0)
        return (
            f"{item.get('signal_id', 'ID yok')} | {item.get('symbol', '?')} "
            f"{item.get('direction', '?')}{label} | {status} | {rr}"
        )

    net = sum(float(item.get("realized_r") or 0.0) for item in completed)
    positive = sum(max(0.0, float(item.get("realized_r") or 0.0)) for item in completed)
    negative = sum(min(0.0, float(item.get("realized_r") or 0.0)) for item in completed)
    reached_count = sum(
        bool(item.get("entry_reached", str(item.get("status") or "").upper() in terminal))
        for item in daily
    )
    lines = [
        "ATLAS | GÜNLÜK İŞLEMLER",
        f"{today:%d.%m.%Y}",
        "",
        f"Verilen setup: {len(daily)}",
        f"Giriş seviyesi görüldü: {reached_count}",
        f"Giriş bekliyor: {len(waiting)}",
        f"Giriş olmadı (süresi doldu): {len(no_entry)}",
    ]
    for heading, items, state in (
        ("TAKİPTE", tracking, "TAKİPTE"),
        ("SONUÇLANAN", completed, None),
        ("GİRİŞ BEKLEYEN", waiting, "LIMIT BEKLİYOR"),
        ("GİRİŞ OLMAYAN", no_entry, "GİRİŞ OLMADI"),
        ("GİRİŞİ GÖRÜLMÜŞ / SÜRESİ DOLAN", expired_after_entry, "SÜRE DOLDU"),
    ):
        if items:
            lines.extend(["", heading])
            lines.extend(describe(item, state) for item in items)
    lines.extend([
        "",
        "GÜNLÜK TOPLAM (yalnızca sonuçlananlar)",
        f"Kazanç: {_format_rr(positive)}",
        f"Zarar: {_format_rr(negative)}",
        f"Net: {_format_rr(net)}",
        "",
        "Not: Giriş seviyesi görülmesi borsa emri/fill gerçekleştiğini kanıtlamaz.",
    ])
    return "\n".join(lines)


def _format_telegram_card(card, elapsed_ms=0):
    symbol = card.get("symbol") or "?"
    direction = str(card.get("direction") or "").upper()
    action = str(card.get("decision_action") or "").upper()
    entry_type = str(card.get("entry_type") or "").upper()
    executable = (
        direction in {"LONG", "SHORT"}
        and entry_type in {"MARKET", "LIMIT"}
        and action in {"EXECUTE", "EXECUTE_WITH_CAUTION"}
        and card.get("entry") is not None
        and card.get("stop_loss") is not None
        and bool(card.get("tp_levels"))
    )
    if not executable:
        reason = str(card.get("reason") or "Ortak karar mekanizması işlem planı üretmedi.")
        return f"ATLAS | {symbol}\nŞu an geçerli işlem planı yok.\n{reason[:180]}"

    strategy = card.get("strategy") or card.get("strategy_id") or "SMC"
    targets = card.get("tp_levels") or []
    rr = card.get("net_rr")
    if rr is None:
        rr = card.get("weighted_net_rr")
    if rr is None:
        rr = card.get("rr")
    lines = [
        f"ATLAS | {symbol}",
        f"Strateji: {strategy}",
        f"Yön: {direction} | Emir: {entry_type}",
        f"Giriş: {card.get('entry')}",
        f"SL: {card.get('stop_loss')}",
    ]
    lines.extend(f"TP{index}: {target}" for index, target in enumerate(targets, start=1))
    lines.append(f"Net RR: {_format_rr(rr) if rr is not None else 'Hesaplanmadı'}")
    if entry_type == "LIMIT":
        lines.append("Durum: Giriş seviyesi bekleniyor; emir otomatik açılmaz.")
    else:
        lines.append("Durum: Teorik MARKET sinyali; borsa fill teyidi değildir.")
    return "\n".join(lines)


def is_recognized_command(command: str) -> bool:
    """Use the same command grammar as the terminal UI."""
    from atlas_tui import (
        _is_report_command,
        _is_symbol_input,
        _parse_liquidity_command,
        _parse_scan_command,
    )

    normalized = normalize_command(command).lower()
    if normalized in {"yardım", "yardim", "help", "?", "mevcut"}:
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
                payload = {
                    "timeout": 15,
                    "allowed_updates": ["message"],
                }
                if self._offset is not None:
                    payload["offset"] = self._offset
                updates = self._api("getUpdates", payload, timeout=20) or []
                for update in updates:
                    self._offset = int(update.get("update_id", 0)) + 1
                    if self.stop_flag.is_set():
                        break
                    self._handle_update(update)
            except requests.RequestException as exc:
                self.logger.warning("Telegram polling network error (%s)", type(exc).__name__)
                self.stop_flag.wait(3)
            except Exception:
                self.logger.error("Telegram polling error")
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
            self.logger.error("Telegram command failed: %s", command[:80])
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
                self.logger.error("Telegram command reply could not be sent")
                break

    def execute_command(self, command: str) -> str:
        """Run the existing TUI command operations without creating a second runtime."""
        from atlas_tui import (
            AtlasTUIApp,
            _is_report_command,
            _parse_liquidity_command,
            _parse_scan_command,
            _best_symbols,
        )
        from utils.signal_card import build_selected_strategy_card, build_signal_card

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
                "performans — tüm geçmiş performans\n"
                "mevcut — bugünün setup ve işlem takibi\n"
                "öğrenme — öğrenme verisi\n"
                "yardım — komutları göster\n\n"
                "Atlas otomatik emir göndermez. Otomatik Telegram sinyal bildirimi kapalıdır."
            )

        if lowered == "mevcut":
            outcomes = self.runtime.signal_outcomes(limit=5000)
            return format_daily_signal_report(outcomes)

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
            scan_limit, result_limit = scan_request
            symbols = _best_symbols(limit=scan_limit)
            candidates = []
            for symbol in symbols:
                scanned = self.runtime.analyze_symbol(symbol, force_refresh=True)
                if not scanned.get("ok"):
                    continue
                raw = scanned.get("result") or {}
                card = (
                    build_selected_strategy_card(raw)
                    if isinstance(raw.get("strategy_lab"), dict)
                    else build_signal_card(raw)
                )
                if not (
                    card.get("direction") in {"LONG", "SHORT"}
                    and card.get("entry_type") in {"MARKET", "LIMIT"}
                    and card.get("decision_action") in {"EXECUTE", "EXECUTE_WITH_CAUTION"}
                    and card.get("entry") is not None
                    and card.get("stop_loss") is not None
                    and card.get("tp_levels")
                ):
                    continue
                rr = card.get("net_rr")
                if rr is None:
                    rr = card.get("rr")
                try:
                    rr_value = float(rr)
                    if rr_value <= 0:
                        continue
                    score = float(card.get("setup_quality") or 0) * 0.55 + float(card.get("confidence") or 0) * 0.25 + min(rr_value, 5.0) * 4
                except (TypeError, ValueError, OverflowError):
                    continue
                if not card.get("strategy") and not card.get("strategy_id"):
                    analysis = raw.get("analysis") or {}
                    card["strategy"] = analysis.get("strategy") or "SMC"
                candidates.append((score, card))
            candidates.sort(key=lambda item: item[0], reverse=True)
            if not candidates:
                return f"ATLAS | TARAMA\nTaranan piyasa: {len(symbols)}\nGeçerli MARKET/LIMIT setup bulunamadı."
            shown = candidates[:max(1, min(int(result_limit), 20))]
            lines = [f"ATLAS | EN İYİ {len(shown)} SETUP", f"Taranan piyasa: {len(symbols)}"]
            for rank, (_score, card) in enumerate(shown, start=1):
                lines.extend(["", f"#{rank}", _format_telegram_card(card)])
            return "\n".join(lines)

        outcome = self.runtime.analyze_symbol(normalized, force_refresh=True)
        if not outcome.get("ok"):
            return (
                f"{normalized.upper()} ANALİZ EDİLEMEDİ\n\n"
                f"Neden: {outcome.get('error', 'bilinmeyen hata')}\n"
                "Sembolün USDT perpetual piyasasında bulunduğunu kontrol et."
            )
        raw = outcome.get("result") or {}
        card = (
            build_selected_strategy_card(raw)
            if isinstance(raw.get("strategy_lab"), dict)
            else build_signal_card(raw)
        )
        if not card.get("strategy") and not card.get("strategy_id"):
            analysis = raw.get("analysis") or {}
            card["strategy"] = analysis.get("strategy") or "SMC"
        return _format_telegram_card(card, outcome.get("elapsed_ms", 0))


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
