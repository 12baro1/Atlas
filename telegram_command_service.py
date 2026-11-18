"""On-demand Telegram command interface for the headless Atlas service.

Only messages from the configured group are considered. The bot never pushes
signals or scan results on its own; it replies only to recognized commands.

Slash command support:
- /btc, /eth, /sol — quick symbol analysis
- /analiz BTC — analyze specific symbol
- /20tara, /30tara, /50tara, /100tara — scan N markets
- /tumtara — scan all supported USDT perpetual markets
- /eniyi5 — get best 5 from existing pool (no new scan)
- /mevcut, /setuplar, /takip, /likidite BTC — setup tracking
- /performans, /istatistik, /ogrenme — performance & learning
- /durum, /sistem, /yardim — system status & help

Commands are case-insensitive. Bot username suffix (e.g., /btc@BotName) is supported.
Legacy plain-text commands (e.g., "btc", "en iyi 5 işlem") are preserved for backward compatibility.
"""

from __future__ import annotations

import logging
import math
import os
import queue
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from opportunity_pool import get_opportunity_pool
from telegram_commands import (
    TELEGRAM_COMMANDS,
    TelegramCommand,
    format_help_text,
    get_botfather_commands,
    get_command_by_name,
)

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 3900
MAX_COMMAND_AGE_SECONDS = 900
MAX_QUEUED_COMMANDS = 8

LOGGER = logging.getLogger("atlas.telegram.commands")


def normalize_command(value: str) -> str:
    """Normalize plain text and /commands addressed to this bot.

    Strips leading '/', removes @botusername suffix, trims whitespace.
    """
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
        return "Hesaplanmadı"
    if not math.isfinite(number):
        return "Hesaplanmadı"
    return f"{number:+.2f}R"


def _format_price(value, *, grouping=True):
    """Format prices without hiding small-coin precision."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    rendered = f"{number:,.8f}" if grouping else f"{number:.8f}"
    rendered = rendered.rstrip("0").rstrip(".")
    if "." not in rendered:
        rendered += ".0"
    return rendered or "0"


def _outcome_strategy(item):
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    strategy = (
        payload.get("strategy")
        or payload.get("strategy_id")
        or payload.get("setup_type")
    )
    if not strategy:
        analysis = payload.get("analysis")
        if isinstance(analysis, dict):
            strategy = analysis.get("strategy") or analysis.get("strategy_id") or analysis.get("setup_type")
    if not strategy:
        selected = payload.get("selected_strategy")
        if isinstance(selected, dict):
            strategy = selected.get("strategy") or selected.get("strategy_id")
    if not strategy:
        lab = payload.get("strategy_lab")
        selected = lab.get("selected") if isinstance(lab, dict) else None
        if isinstance(selected, dict):
            strategy = selected.get("strategy") or selected.get("strategy_id")
    return str(strategy) if strategy else "Belirtilmedi"


def _outcome_progress(item):
    hit_levels = sorted({
        int(level) for level in (item.get("tps_hit") or [])
        if str(level).isdigit() and int(level) in (1, 2, 3)
    })
    available = [
        level for level in (1, 2, 3)
        if item.get(f"tp{level}") is not None
    ]
    remaining = [level for level in available if level not in hit_levels]
    if not hit_levels:
        return "Hedef bekleniyor", hit_levels
    progress = "/".join(f"TP{level}" for level in hit_levels) + " ALINDI"
    if remaining:
        progress += "  |  " + "/".join(f"TP{level}" for level in remaining) + " TAKİPTE"
    return progress, hit_levels


def _same_tracked_setup(candidate, outcome):
    """Match a pool setup to its journal outcome by full trade geometry."""
    if (
        str(candidate.symbol).replace(":USDT", "") != str(outcome.get("symbol") or "").replace(":USDT", "")
        or str(candidate.direction).upper() != str(outcome.get("direction") or "").upper()
    ):
        return False
    pairs = (
        (candidate.entry_price, outcome.get("entry")),
        (candidate.stop_loss, outcome.get("stop_loss")),
        (candidate.tp1, outcome.get("tp1")),
        (candidate.tp2, outcome.get("tp2")),
        (candidate.tp3, outcome.get("tp3")),
    )
    try:
        return all(
            left is not None and right is not None
            and math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-10)
            for left, right in pairs
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _format_outcome_item(item, state):
    status = str(item.get("status") or "PENDING").upper()
    symbol = str(item.get("symbol") or "?").replace(":USDT", "")
    direction = str(item.get("direction") or "?").upper()
    progress, hit_levels = _outcome_progress(item)
    lines = [
        f"{symbol} | {direction}",
        f"Strateji: {_outcome_strategy(item)}",
        f"Durum: {state or status}",
    ]
    if item.get("entry_type"):
        lines.append(f"Emir: {str(item.get('entry_type')).upper()}")
    if item.get("entry") is not None:
        lines.append(f"Giriş: {_format_price(item.get('entry'))}")
    if item.get("stop_loss") is not None:
        lines.append(f"Stop Loss: {_format_price(item.get('stop_loss'))}")
    for level in (1, 2, 3):
        value = item.get(f"tp{level}")
        if value is not None:
            lines.append(f"TP{level}: {_format_price(value)}")
    rr = item.get("rr")
    if rr is None:
        try:
            entry = float(item.get("entry"))
            stop = float(item.get("stop_loss"))
            tp1 = float(item.get("tp1"))
            risk = abs(entry - stop)
            if all(math.isfinite(value) and value > 0 for value in (entry, stop, tp1)) and risk > 0:
                rr = abs(tp1 - entry) / risk
        except (TypeError, ValueError, OverflowError):
            rr = None
    lines.append(f"TP1 RR (brüt): {_format_rr(rr) if rr is not None else 'Hesaplanmadı'}")
    if item.get("net_rr") is not None:
        lines.append(f"Net RR: {_format_rr(item.get('net_rr'))}")
    if status == "PENDING":
        if hit_levels:
            lines.append(f"Hedef ilerlemesi: {progress}")
            lines.append(f"Gerçekleşen kısmi getiri (brüt): {_format_rr(item.get('realized_r') or 0)}")
        elif item.get("entry_tracking_source") == "market_reference":
            lines.append("Giriş: MARKET referansı (borsa fill teyidi değil)")
        elif item.get("entry_reached"):
            lines.append("Giriş seviyesi görüldü (borsa fill teyidi değildir)")
        else:
            lines.append("Giriş bekleniyor")
        if item.get("trailing_stop") is not None:
            lines.append(f"Koruma stopu: {_format_price(item.get('trailing_stop'))}")
    elif status in {"TP1", "TP2", "TP3", "SL"}:
        if hit_levels:
            lines.append(f"Hedef ilerlemesi: {progress}")
        if item.get("trailing_stop") is not None:
            lines.append(f"Son koruma stopu: {_format_price(item.get('trailing_stop'))}")
        lines.append(f"Sonuç: {status}")
        lines.append(f"Net sonuç: {_format_rr(item.get('realized_r') or 0)}")
    elif status == "EXPIRED":
        lines.append("Sonuç: Süre doldu")
        lines.append("Giriş seviyesi görüldü" if item.get("entry_reached") else "Giriş seviyesi görülmedi")
    return "\n".join(lines)

def format_daily_signal_report(outcomes, now=None):
    """Render a readable daily setup and outcome report in Europe/Istanbul time."""
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
        status = str(item.get("status") or "PENDING").upper()
        # Keep every still-open signal visible across day boundaries; closed
        # history remains in the daily report only for the current Istanbul day.
        if opened.date() == today or status == "PENDING":
            daily.append(item)

    divider = "━━━━━━━━━━━━━━━━━━━━"
    if not daily:
        return (
            f"{divider}\nATLAS | BUGÜNÜN İŞLEM TAKİBİ\n{today:%d.%m.%Y}\n"
            f"{divider}\n\nBugün henüz kayıtlı setup yok."
        )

    terminal = {"TP1", "TP2", "TP3", "SL"}
    tracking, waiting, no_entry, completed, expired_after_entry = [], [], [], [], []
    for item in sorted(daily, key=lambda row: int(row.get("opened_at") or 0), reverse=True):
        status = str(item.get("status") or "PENDING").upper()
        reached = bool(item.get("entry_reached", status in terminal))
        if status in terminal:
            completed.append(item)
        elif status == "EXPIRED":
            (expired_after_entry if reached else no_entry).append(item)
        elif status == "PENDING":
            (tracking if reached else waiting).append(item)

    tp1_tracking = sum(
        str(item.get("status") or "PENDING").upper() == "PENDING"
        and 1 in [int(level) for level in (item.get("tps_hit") or []) if str(level).isdigit()]
        for item in daily
    )
    net = sum(float(item.get("realized_r") or 0.0) for item in completed)
    positive = sum(max(0.0, float(item.get("realized_r") or 0.0)) for item in completed)
    negative = sum(min(0.0, float(item.get("realized_r") or 0.0)) for item in completed)
    reached_count = sum(
        item.get("entry_tracking_source") == "closed_ohlc"
        or (
            "entry_tracking_source" not in item
            and bool(item.get("entry_reached", str(item.get("status") or "").upper() in terminal))
        )
        for item in daily
    )
    market_reference_count = sum(
        item.get("entry_tracking_source") == "market_reference"
        for item in daily
    )

    lines = [
        divider,
        "ATLAS | SETUP VE İŞLEM TAKİBİ",
        f"{today:%d.%m.%Y}",
        divider,
        f"Bugünkü setup + önceki günlerden açık: {len(daily)}",
        f"Aktif takip: {len(tracking)}",
        f"Giriş bekliyor: {len(waiting)}",
        f"Sonuçlanan: {len(completed)}",
        f"Giriş olmadı (süresi doldu): {len(no_entry)}",
        f"TP1 alındı, TP2/TP3 takipte: {tp1_tracking}",
        f"Giriş seviyesi mumda görüldü: {reached_count}",
        f"MARKET referansı (fill teyitsiz): {market_reference_count}",
    ]
    for heading, items, state in (
        ("AKTİF İŞLEMLER", tracking, "İŞLEM TAKİPTE"),
        ("GİRİŞ BEKLEYENLER", waiting, "GİRİŞ BEKLENİYOR"),
        ("SONUÇLANANLAR", completed, None),
        ("GİRİŞ OLMADAN SÜRESİ DOLANLAR", no_entry, "GİRİŞ OLMADI"),
        ("GİRİŞİ GÖRÜLMÜŞ / SÜRESİ DOLANLAR", expired_after_entry, "SÜRE DOLDU"),
    ):
        if items:
            lines.extend(["", divider, f"{heading} ({len(items)})"])
            for item in items:
                item_state = state
                if state == "İŞLEM TAKİPTE" and item.get("entry_tracking_source") == "market_reference":
                    item_state = "MARKET REFERANSI — FILL TEYİTSİZ"
                lines.extend([_format_outcome_item(item, item_state), ""])

    lines.extend([
        divider,
        "GÜNLÜK NET SONUÇ — YALNIZCA KAPANAN SİNYALLER",
        f"Kazanç: {_format_rr(positive)}",
        f"Kayıp: {_format_rr(negative)}",
        f"Net: {_format_rr(net)}",
        divider,
        "TP1 kısmi hedef olarak kaydedilir; işlem kapanmaz ve kalan hedefler takip edilir.",
        "Giriş seviyesinin mumda görülmesi, borsada emir/fill gerçekleştiği anlamına gelmez.",
    ])
    return "\n".join(lines)


def _format_telegram_card(card, elapsed_ms=0):
    """Render one complete, actionable trade plan without exposing debug details."""
    symbol = str(card.get("symbol") or "?").replace(":USDT", "")
    direction = str(card.get("direction") or "").upper()
    action = str(card.get("decision_action") or "").upper()
    entry_type = str(card.get("entry_type") or "").upper()
    targets = list(card.get("tp_levels") or [])
    try:
        numbers = [float(card.get("entry")), float(card.get("stop_loss")), *map(float, targets[:3])]
        valid_numbers = len(targets) >= 3 and all(math.isfinite(value) and value > 0 for value in numbers)
    except (TypeError, ValueError, OverflowError):
        valid_numbers = False
    geometry_valid = False
    if valid_numbers and direction == "LONG":
        geometry_valid = numbers[1] < numbers[0] < numbers[2] < numbers[3] < numbers[4]
    elif valid_numbers and direction == "SHORT":
        geometry_valid = numbers[1] > numbers[0] > numbers[2] > numbers[3] > numbers[4]
    executable = (
        direction in {"LONG", "SHORT"}
        and entry_type in {"MARKET", "LIMIT"}
        and action in {"EXECUTE", "EXECUTE_WITH_CAUTION"}
        and geometry_valid
    )
    if not executable:
        reason = str(card.get("reason") or "Ortak karar mekanizması geçerli işlem planı üretmedi.")
        reason = reason.splitlines()[0][:160]
        return "\n".join([
            f"ATLAS | {symbol}",
            "GEÇERLİ İŞLEM PLANI YOK",
            f"Neden: {reason}",
            "Giriş, SL ve üç TP birlikte doğrulanmadı.",
            "Karar: İŞLEME GİRME",
        ])

    strategy = str(card.get("strategy") or card.get("strategy_id") or "Belirtilmedi")
    rr = card.get("net_rr")
    if rr is None:
        rr = card.get("weighted_net_rr")
    if rr is None:
        rr = card.get("rr")
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"ATLAS | {symbol} — {direction}",
        f"Strateji: {strategy}",
        f"Emir: {entry_type}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Giriş ({entry_type}): {_format_price(card.get('entry'), grouping=False)}",
        f"SL: {_format_price(card.get('stop_loss'), grouping=False)}",
        f"TP1: {_format_price(targets[0], grouping=False)}",
        f"TP2: {_format_price(targets[1], grouping=False)}",
        f"TP3: {_format_price(targets[2], grouping=False)}",
        f"Net RR: {_format_rr(rr) if rr is not None else 'Hesaplanmadı'}",
        "Durum: LIMIT giriş bekleniyor." if entry_type == "LIMIT"
        else "Durum: MARKET planı hazır; borsaya emir gönderilmedi.",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def is_recognized_command(command: str) -> bool:
    """Check if a command is recognized (slash or legacy plain-text).

    Supports:
    - Slash commands: /btc, /btc@BotName, /analiz BTC, /20tara, etc.
    - Legacy plain-text: "btc", "en iyi 5 işlem", "20 tara", "likidite BTC", etc.
    """
    from atlas_tui import (
        _is_report_command,
        _is_symbol_input,
        _parse_liquidity_command,
        _parse_scan_command,
    )

    raw = str(command or "").strip()
    if not raw:
        return False

    normalized = normalize_command(raw).lower()

    # Direct slash command match
    if raw.startswith("/"):
        cmd_name = normalized.split()[0]
        if get_command_by_name(cmd_name):
            return True
        # Parameterized commands like "/analiz BTC"
        parts = normalized.split(maxsplit=1)
        if len(parts) == 2:
            cmd_def = get_command_by_name(parts[0])
            if cmd_def and cmd_def.takes_parameter:
                return True

    # Legacy plain-text commands (backward compatibility)
    if normalized in {"yardım", "yardim", "help", "?", "mevcut"}:
        return True
    return (
        _is_report_command(normalized)
        or _parse_liquidity_command(normalized) is not False
        or _parse_scan_command(normalized) is not None
        or normalized in {"eniyi5", "en iyi 5", "en iyi 5 işlem", "en iyi 5 islem"}
        or normalized in {"eniyi10", "en iyi 10", "en iyi 10 işlem", "en iyi 10 islem"}
        or normalized in {"tarama durumu", "taramadurum", "tarama durdur", "taramadurdur",
                          "tarama devam", "taramadevam", "yenile", "envanter yenile",
                          "havuz durumu", "havuzdurum"}
        # Bare ticker in group chat is ordinary chat; only analyze explicit slash commands
        or (raw.startswith("/") and _is_symbol_input(normalized))
    )


class TelegramCommandService:
    """Long-poll Telegram and execute recognized commands against one runtime."""

    def __init__(self, runtime, token: str, chat_id: str, logger=None):
        self.runtime = runtime
        self.token = str(token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.logger = logger or LOGGER
        self.stop_flag = threading.Event()
        self._thread = None
        self._offset = None
        self._session = requests.Session()
        self._reply_session = requests.Session()
        self._command_queue = queue.Queue(maxsize=MAX_QUEUED_COMMANDS)
        self._command_thread = None
        self._bot_username = None
        self._bot_info_cache = None
        self._bot_info_cache_time = 0

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
        # Resolve bot identity before starting long polling; requests.Session is
        # then owned by the polling thread instead of being used concurrently.
        self._fetch_bot_info()
        self._command_thread = threading.Thread(
            target=self._command_worker_loop,
            name="atlas-telegram-command-worker",
            daemon=True,
        )
        self._command_thread.start()
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
        if self._command_thread and self._command_thread.is_alive():
            self._command_thread.join(timeout=max(0.0, float(timeout)))
        self._session.close()
        self._reply_session.close()

    def _fetch_bot_info(self) -> None:
        """Fetch bot username for @BotName command parsing."""
        try:
            result = self._api("getMe", {})
            self._bot_username = result.get("username", "").lower()
            self._bot_info_cache = result
            self._bot_info_cache_time = time.time()
            self.logger.info("Telegram bot info: @%s", self._bot_username)
        except Exception:
            self.logger.exception("Failed to fetch bot info")

    def _api(self, method: str, payload: dict, timeout=25, session=None):
        """Make Telegram API call with diagnostics logging."""
        start = time.perf_counter()
        self.logger.debug("Telegram API call: %s", method)
        try:
            http_session = session or self._session
            response = http_session.post(
                f"{TELEGRAM_API}/bot{self.token}/{method}",
                json=payload,
                timeout=(5, timeout),
            )
            elapsed = time.perf_counter() - start
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                self.logger.error("Telegram API error: %s | %s", method, result.get("description"))
                raise RuntimeError(str(result.get("description") or "Telegram API request failed"))
            self.logger.debug("Telegram API success: %s (%.3fs)", method, elapsed)
            if method == "sendMessage":
                self.logger.info("Telegram reply sent | characters=%s", len(str(payload.get("text") or "")))
            return result.get("result")
        except requests.RequestException as exc:
            elapsed = time.perf_counter() - start
            self.logger.error("Telegram API network error: %s | %s (%.3fs)", method, exc, elapsed)
            raise

    def _poll_loop(self) -> None:
        self.logger.info("Telegram command polling started for configured group")
        # Discard messages queued before startup. A stale backlog must not
        # delay or age out commands sent after this process becomes available.
        try:
            pending = self._api(
                "getUpdates",
                {"offset": -1, "timeout": 0, "allowed_updates": ["message", "edited_message"]},
                timeout=5,
            ) or []
            if pending:
                self._offset = max(int(item.get("update_id", 0)) for item in pending) + 1
                self.logger.info(
                    "Discarded pre-start Telegram backlog | updates=%s next_offset=%s",
                    len(pending), self._offset,
                )
        except Exception:
            self.logger.exception("Could not synchronize Telegram update offset; continuing polling")
        while not self.stop_flag.is_set():
            try:
                payload = {
                    "timeout": 15,
                    "allowed_updates": ["message", "edited_message"],
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
                self.logger.warning("Telegram polling network error: %s", type(exc).__name__)
                self.stop_flag.wait(3)
            except Exception:
                self.logger.exception("Telegram polling error")
                self.stop_flag.wait(3)
        self.logger.info("Telegram command polling stopped")

    def _handle_update(self, update: dict) -> None:
        """Process a single Telegram update with full diagnostics."""
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}

        chat_id = str(chat.get("id", ""))
        sender_id = sender.get("id")
        is_bot = sender.get("is_bot", False)

        # INFO-level diagnostics are intentional: the production service runs
        # at INFO, so DEBUG-only update logs made delivery failures invisible.
        self.logger.info(
            "Telegram update received | chat_id=%s sender_id=%s is_bot=%s has_text=%s",
            chat_id, sender_id, is_bot, bool(message.get("text"))
        )

        # Chat ID validation
        if chat_id != self.chat_id:
            self.logger.warning(
                "Telegram message ignored: configured group chat ID does not match "
                "(configured=%s received=%s)",
                self.chat_id, chat_id,
            )
            return
        if is_bot:
            self.logger.debug("Ignoring message from bot")
            return

        # Stale command protection
        try:
            message_ts = int(message.get("date") or 0)
        except (TypeError, ValueError, OverflowError):
            message_ts = 0
        now_ts = int(datetime.now().timestamp())
        if not message_ts or now_ts - message_ts > MAX_COMMAND_AGE_SECONDS or message_ts - now_ts > 30:
            self.logger.info("Ignoring stale Telegram update (age=%ss)", now_ts - message_ts)
            return

        raw_command = str(message.get("text") or "").strip()
        if not raw_command:
            return

        command = normalize_command(raw_command)
        if not command or not is_recognized_command(raw_command):
            self.logger.info("Telegram text received but not recognized as a command: %s", raw_command[:80])
            return

        self.logger.info("Telegram command queued: %s (chat_id=%s)", command[:80], chat_id)
        try:
            self._command_queue.put_nowait((raw_command, command))
            # Keep the group clean: send only the final command result.
        except queue.Full:
            self.logger.warning("Telegram command queue full; rejecting command: %s", command[:80])
            try:
                self._api(
                    "sendMessage",
                    {
                        "chat_id": self.chat_id,
                        "text": "Atlas önceki komutu işliyor. Biraz sonra tekrar deneyin.",
                        "disable_web_page_preview": True,
                    },
                    timeout=10,
                )
            except Exception:
                self.logger.exception("Telegram queue-full reply could not be sent")

    def _send_command_reply(self, message: str) -> None:
        for part in split_message(message):
            try:
                self._api(
                    "sendMessage",
                    {"chat_id": self.chat_id, "text": part, "disable_web_page_preview": True},
                    timeout=10,
                    session=self._reply_session,
                )
            except Exception:
                self.logger.exception("Telegram command reply could not be sent")
                break

    def _command_worker_loop(self) -> None:
        while not self.stop_flag.is_set() or not self._command_queue.empty():
            try:
                raw_command, command_label = self._command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.logger.info("Telegram command execution started: %s", command_label[:80])
                try:
                    result = self.execute_command(raw_command)
                except Exception:
                    self.logger.exception("Telegram command failed: %s", command_label[:80])
                    result = "Komut işlenirken hata oluştu. VPS günlüklerini kontrol et."
                self._send_command_reply(result)
                self.logger.info("Telegram command execution completed: %s", command_label[:80])
            finally:
                self._command_queue.task_done()

    def execute_command(self, command: str) -> str:
        """Execute a recognized command and return formatted response."""
        from atlas_tui import (
            AtlasTUIApp,
            _is_report_command,
            _parse_liquidity_command,
            _parse_scan_command,
            _best_symbols,
        )
        from utils.signal_card import build_selected_strategy_card, build_signal_card

        raw = str(command or "").strip()
        normalized = normalize_command(raw)
        lowered = normalized.lower()

        # Handle slash commands with parameters (e.g., "/analiz BTC")
        if raw.startswith("/"):
            parts = normalized.split(maxsplit=1)
            cmd_name = parts[0]
            param = parts[1] if len(parts) > 1 else None
            cmd_def = get_command_by_name(cmd_name)
            if cmd_def:
                handler_name = cmd_def.handler
                handler = getattr(self, handler_name, None)
                if handler:
                    if cmd_def.takes_parameter:
                        if param:
                            return handler(param)
                        else:
                            return f"KULLANIM: /{cmd_def.name} <{cmd_def.parameter_name}>"
                    else:
                        # For commands like /btc, /eth, /sol that share handle_analyze_symbol
                        # but don't take a parameter in the command, extract symbol from command name
                        if handler_name == "handle_analyze_symbol":
                            # The command name itself is the symbol (btc, eth, sol)
                            return handler(cmd_name.upper())
                        # Scan commands need the requested limit (e.g. /200tara)
                        if handler_name == "handle_scan":
                            return handler(cmd_name)
                        return handler()
                else:
                    self.logger.error("Handler not found: %s", handler_name)
                    return f"Komut işleyici eksik: {handler_name}"

        # Legacy plain-text commands (backward compatibility)
        if lowered in {"yardım", "yardim", "help", "?"}:
            return self.handle_help()

        if lowered == "mevcut":
            return self.handle_mevcut()

        # Best-N legacy text ("en iyi 5", "en iyi 10"): strictly read-only
        # pool reads, never a new scan and never the old scan path.
        if lowered in {"en iyi 5", "eniyi5", "en iyi 5 işlem", "en iyi 5 islem"}:
            return self.handle_best_five()
        if lowered in {"en iyi 10", "eniyi10", "en iyi 10 işlem", "en iyi 10 islem"}:
            return self.handle_best_ten()
        # Scan lifecycle legacy text
        if lowered in {"tarama durumu", "taramadurum"}:
            return self.handle_scan_status()
        if lowered in {"tarama durdur", "taramadurdur"}:
            return self.handle_scan_stop()
        if lowered in {"tarama devam", "taramadevam"}:
            return self.handle_scan_resume()
        if lowered in {"yenile", "envanter yenile"}:
            return self.handle_refresh()
        if lowered in {"havuz durumu", "havuzdurum"}:
            return self.handle_pool_status()

        # Reuse TUI formatting and scan logic
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
            outcome = self.runtime.analyze_symbol(symbol, force_refresh=True, track_signal=False)
            return (
                AtlasTUIApp._format_liquidity(adapter, outcome)
                if outcome.get("ok")
                else f"{symbol} likidite analizi yapılamadı: {outcome.get('error')}"
            )

        if scan_request is not None:
            # All legacy scan text also goes through the real scan queue.
            return self._queue_scan_report(scan_request[0])

        # Single symbol analysis (legacy plain-text like "BTC")
        if _is_symbol_input(normalized) and not raw.startswith("/"):
            # Bare symbol without slash is treated as chat in groups
            return "Slash komut kullanın: /btc, /eth, /analiz BTC"

        outcome = self.runtime.analyze_symbol(
            normalized, force_refresh=True, track_signal=True
        )
        if not outcome.get("ok"):
            return (
                f"{normalized.upper()} ANALİZ EDİLEMEDİ\n\n"
                f"Neden: {outcome.get('error', 'bilinmeyen hata')}\n"
                "Sembolün USDT perpetual piyasasında bulunduğunu kontrol et."
            )
        raw_result = outcome.get("result") or {}
        card = (
            build_selected_strategy_card(raw_result)
            if isinstance(raw_result.get("strategy_lab"), dict)
            else build_signal_card(raw_result)
        )
        if not card.get("strategy") and not card.get("strategy_id"):
            analysis = raw_result.get("analysis") or {}
            card["strategy"] = analysis.get("strategy") or "SMC"
        return _format_telegram_card(card, outcome.get("elapsed_ms", 0))

    # --- Command Handlers ---

    def handle_start(self) -> str:
        """Handle Telegram's conventional /start command."""
        return (
            "ATLAS | KOMUT MERKEZİ\n\n"
            "Analiz: /btc, /eth, /sol, /analiz BTC\n"
            "Tarama: /20tara ... /1000tara, /tumtara\n"
            "Havuz: /eniyi5, /eniyi10, /havuzdurum\n"
            "Takip: /mevcut, /setuplar, /takip, /likidite BTC\n"
            "Sistem: /taramadurum, /durum, /sistem\n\n"
            "Tüm komutlar: /yardim"
        )

    def handle_help(self) -> str:
        return format_help_text()

    def handle_analyze_symbol(self, symbol: str) -> str:
        """Handle /btc, /eth, /sol, /analiz BTC"""
        from atlas_tui import _is_symbol_input
        from utils.signal_card import build_selected_strategy_card, build_signal_card

        if not _is_symbol_input(symbol):
            return f"Geçersiz sembol: {symbol}\nÖrnek: /btc, /analiz ETH"

        outcome = self.runtime.analyze_symbol(
            symbol, force_refresh=True, track_signal=True
        )
        if not outcome.get("ok"):
            return (
                f"ATLAS | {symbol.upper()}\n"
                "ANALİZ TAMAMLANAMADI\n"
                "Piyasa verisi alınamadı veya analiz koşulları tamamlanmadı.\n"
                "Sembolün Gate.io USDT perpetual olduğunu kontrol et."
            )
        raw_result = outcome.get("result") or {}
        card = (
            build_selected_strategy_card(raw_result)
            if isinstance(raw_result.get("strategy_lab"), dict)
            else build_signal_card(raw_result)
        )
        if not card.get("strategy") and not card.get("strategy_id"):
            analysis = raw_result.get("analysis") or {}
            card["strategy"] = analysis.get("strategy") or "SMC"
        return _format_telegram_card(card, outcome.get("elapsed_ms", 0))

    def handle_scan(self, cmd_name=None) -> str:
        """Handle /20tara ... /1000tara — real scan queue, resumable."""
        limit = self._parse_scan_limit(cmd_name)
        return self._queue_scan_report(limit)

    def handle_scan_all(self) -> str:
        """Handle /tumtara — scan the whole Gate.io universe via the queue."""
        return self._queue_scan_report(None)

    def handle_scan_status(self) -> str:
        """Show only scan-queue state; strategy and pool data live in /havuzdurum."""
        status = self.runtime.scan_status()
        inventory = status.get("inventory") or {}
        total = int(status.get("total", 0) or 0)
        done = int(status.get("done", 0) or 0)
        running = int(status.get("running", 0) or 0)
        pending = int(status.get("pending", 0) or 0)
        failed = int(status.get("failed", 0) or 0)
        state = "ÇALIŞIYOR" if status.get("workers_running") else (
            "BEKLEMEDE" if pending else "TAMAMLANDI"
        )
        lines = [
            "ATLAS | TARAMA DURUMU",
            f"Durum: {state}",
            "",
            f"İlerleme: %{float(status.get('percent', 0.0) or 0.0):.1f}",
            f"Tamamlanan: {done}/{total}",
            f"Aktif: {running} | Bekleyen: {pending} | Hatalı: {failed}",
            f"Worker'lar: {'çalışıyor' if status.get('workers_running') else 'durduruldu'}",
            "",
            "PİYASA",
            f"Borsa: Gate.io | USDT Perpetual: {inventory.get('symbol_count', 0)}",
            f"Sıralama: {inventory.get('ranking_source') or 'Bilinmiyor'}",
        ]
        age = inventory.get("last_refresh_age_seconds")
        if age is not None:
            lines.append(f"Envanter güncellemesi: {float(age):.0f} sn önce")
        lines.extend(["", "Havuz ve strateji raporu: /havuzdurum"])
        return "\n".join(lines)

    def handle_scan_stop(self) -> str:
        """Handle /taramadurdur — stop workers; claimed leases requeue on expiry."""
        result = self.runtime.stop_scan()
        progress = result.get("progress") or {}
        alive = result.get("workers_still_alive") or []
        lines = [
            "ATLAS | TARAMA DURDURULDU" if result.get("stopped") else "ATLAS | TARAMA DURDURMA İSTEĞİ",
            "",
            "Worker'lar durdu." if result.get("stopped") else
            "Aktif worker mevcut analizini bitiriyor; yeni worker başlatılmayacak.",
            f"Tamamlanan: {progress.get('done', 0)}",
            f"Aktif: {progress.get('running', 0)}",
            f"Bekleyen: {progress.get('pending', 0)}",
            "Kuyruk ve fırsat havuzu korunuyor.",
            "Devam etmek için: /taramadevam",
        ]
        if alive:
            lines.append("Çalışan: " + ", ".join(alive))
        return "\n".join(lines)

    def handle_scan_resume(self) -> str:
        """Handle /taramadevam — resume pending queue work (checkpoint kept)."""
        result = self.runtime.resume_scan()
        return self._format_scan_progress(result, resumed=True)

    def handle_refresh(self) -> str:
        """Refresh Gate.io market inventory and report a concise result."""
        status = self.runtime.refresh_market_inventory()
        if status.get("last_error"):
            return (
                "ATLAS | ENVANTER YENİLENEMEDİ\n"
                "Mevcut piyasa snapshot'ı korundu.\n"
                "Ayrıntı için VPS servis günlüklerini kontrol et."
            )
        return (
            "ATLAS | ENVANTER YENİLENDİ\n"
            f"Borsa: GATE.IO\nUSDT Perpetual: {status.get('symbol_count', 0)}\n"
            "Kaynak: Gate.io\nDurum: BAŞARILI"
        )

    def handle_best_five(self) -> str:
        """Handle /eniyi5 — strictly read-only from the Setup Pool."""
        return self._format_best_setups(5)

    def handle_best_ten(self) -> str:
        """Handle /eniyi10 — strictly read-only from the Setup Pool."""
        return self._format_best_setups(10)

    def handle_pool_status(self) -> str:
        """Show pool totals and the seven-strategy funnel, without queue noise."""
        pool = get_opportunity_pool()
        stats = pool.get_stats()
        scan = self.runtime.scan_status()
        telemetry = scan.get("strategy_telemetry") or {}
        per_strategy = telemetry.get("per_strategy") or {}
        names = (
            ("smc", "SMC"),
            ("relative_strength", "RELATIVE STRENGTH"),
            ("trend_pullback", "TREND PULLBACK"),
            ("orderflow_momentum", "ORDERFLOW MOMENTUM"),
            ("mean_reversion", "MEAN REVERSION"),
            ("liquidation_cascade", "LIQUIDATION CASCADE"),
            ("volatility_breakout", "VOLATILITY BREAKOUT"),
        )
        lines = [
            "ATLAS | HAVUZ VE STRATEJİLER",
            "",
            "FIRSAT HAVUZU",
            f"Aday: {stats.get('candidates', 0)} | Doğrulanmış: {stats.get('validated', 0)}",
            f"Aktif takip: {stats.get('active', 0)} | Arşiv: {stats.get('history', 0)}",
            "",
            "7 STRATEJİ",
        ]
        for key, label in names:
            row = per_strategy.get(key) or {}
            lines.append(
                f"{label}: {row.get('setups', 0)} setup | "
                f"{row.get('passed', 0)} geçti | {row.get('rejected', 0)} elendi"
            )
        lines.extend([
            "",
            "ORTAK FİLTRE",
            f"Üretilen: {telemetry.get('raw_setups_generated', 0)}",
            f"Geçen: {telemetry.get('common_filter_passed', 0)}",
            f"Elenen: {telemetry.get('common_filter_rejected', 0)}",
            "",
            "Tarama kuyruğu: /taramadurum",
            "En iyi fırsatlar: /eniyi5",
        ])
        return "\n".join(lines)

    @staticmethod
    def _parse_scan_limit(cmd_name) -> Optional[int]:
        """Extract the requested scan size from a command name like '200tara'."""
        import re as _re
        text = str(cmd_name or "")
        match = _re.search(r"(\d+)", text)
        if not match:
            return None
        try:
            limit = int(match.group(1))
        except ValueError:
            return None
        return max(1, min(limit, 1000))

    def _queue_scan_report(self, limit: Optional[int]) -> str:
        """Start/queue a scan via the runtime scan service and report progress."""
        result = self.runtime.start_scan(limit)
        if not result.get("started"):
            return "ATLAS | TARAMA BAŞLATILAMADI\nMevcut tarama kuyruğu değiştirilmedi. /taramadurum ile durumu kontrol et."
        return self._format_scan_progress(result)

    def _format_scan_progress(self, result: dict, resumed: bool = False) -> str:
        progress = result.get("progress") or {}
        title = "TARAMA DEVAM EDİYOR" if resumed else "TARAMA BAŞLADI"
        lines = [
            f"ATLAS | {title}",
            "",
            f"Hedef: {result.get('selected') if result.get('selected') is not None else (result.get('universe_size') or 'Tüm uygun piyasalar')}",
            f"Toplam uygun sözleşme: {result.get('universe_size', '—')}",
            f"Kuyruğa yeni eklenen: {result.get('added', 0)}",
            f"Tamamlanan: {progress.get('done', 0)} | Bekleyen: {progress.get('pending', 0)}",
            f"İlerleme: %{float(progress.get('percent', 0.0) or 0.0):.1f}",
            f"Sıralama: {result.get('ranking_source') or 'Mevcut kuyruk sıralaması'}",
            "",
            "Ayrıntı: /taramadurum",
            "Durdur: /taramadurdur",
            "Fırsatlar: /eniyi5",
        ]
        if resumed:
            lines.insert(2, "Kuyruk kaldığı yerden sürdürülüyor.")
        return "\n".join(lines)

    def _format_best_setups(self, count: int) -> str:
        """Read-only report of complete, validated trade plans from the pool."""
        best = get_opportunity_pool().get_best_setups(limit=count)
        if not best:
            return (
                f"ATLAS | EN İYİ {count} SETUP\n\n"
                "Doğrulanmış setup havuzu boş.\n"
                "Yeni tarama: /20tara"
            )
        now_ms = int(time.time() * 1000)
        lines = [f"ATLAS | EN İYİ {len(best)} SETUP", "Kaynak: Kalıcı doğrulanmış havuz", ""]
        for index, setup in enumerate(best, start=1):
            age_hours = max(0.0, (now_ms - setup.created_at_ms) / 3_600_000.0) if setup.created_at_ms else None
            age = f"{age_hours:.1f} sa" if age_hours is not None else "bilinmiyor"
            entry_type = str(getattr(setup, "entry_type", "") or getattr(setup, "setup_type", "—")).upper()
            lines.extend([
                f"{index}. {str(setup.symbol).replace(':USDT', '')} | {setup.direction}",
                f"Strateji: {setup.strategy_name} | Emir: {entry_type}",
                f"Giriş: {_format_price(setup.entry_price)}",
                f"Stop Loss: {_format_price(setup.stop_loss)}",
                f"TP1: {_format_price(setup.tp1)}",
                f"TP2: {_format_price(setup.tp2)}",
                f"TP3: {_format_price(setup.tp3)}",
                f"RR (TP1/TP2/TP3): "
                f"{_format_rr(getattr(setup, 'rr_tp1', None))} / "
                f"{_format_rr(getattr(setup, 'rr_tp2', None))} / "
                f"{_format_rr(getattr(setup, 'rr_tp3', None))}",
                f"Net RR: {_format_rr(getattr(setup, 'net_rr_after_costs', None))}",
                f"Durum: {setup.status} | Yaş: {age}",
                "",
            ])
        lines.extend([
            "Yeni tarama başlatılmadı; kuyruk ve havuz değiştirilmedi.",
            "Skor sıralama ölçüsüdür, kazanma olasılığı değildir.",
        ])
        return "\n".join(lines)

    def handle_mevcut(self) -> str:
        """Show today's signal outcomes and still-open signals only."""
        return format_daily_signal_report(self.runtime.signal_outcomes(limit=5000))

    def handle_setuplar(self) -> str:
        """List validated pool setups separately from signal-outcome tracking."""
        pool = get_opportunity_pool()
        validated = pool.get_best_setups(limit=20)
        active = pool.get_active_setups()
        if not validated and not active:
            return "ATLAS | SETUPLAR\n\nDoğrulanmış veya kabul edilmiş setup yok."
        lines = ["ATLAS | SETUPLAR"]
        if validated:
            lines.extend(["", f"DOĞRULANMIŞ SETUPLAR ({len(validated)})"])
            for item in validated:
                entry_type = str(getattr(item, "entry_type", "") or getattr(item, "setup_type", "—")).upper()
                lines.extend([
                    f"{str(item.symbol).replace(':USDT', '')} | {item.direction}",
                    f"Strateji: {item.strategy_name} | Emir: {entry_type}",
                    f"Giriş: {_format_price(item.entry_price)}",
                    f"Stop Loss: {_format_price(item.stop_loss)}",
                    f"TP1: {_format_price(item.tp1)}",
                    f"TP2: {_format_price(item.tp2)}",
                    f"TP3: {_format_price(item.tp3)}",
                    f"RR (ağırlıklı): {_format_rr(getattr(item, 'risk_reward', None))}",
                    f"Net RR: {_format_rr(item.net_rr_after_costs)} | Durum: {item.status}",
                    "",
                ])
        if active:
            lines.extend(["", f"KABUL EDİLMİŞ / AKTİF ({len(active)})"])
            for item in active:
                progress = f"TP{item.current_tp} ALINDI" if item.current_tp else "Hedef bekleniyor"
                lines.extend([
                    f"{str(item.symbol).replace(':USDT', '')} | {item.direction}",
                    f"Strateji: {item.strategy_name} | Durum: {item.status}",
                    f"Giriş: {_format_price(item.entry_filled_price or item.entry_price)}",
                    f"Koruma Stop Loss: {_format_price(item.trailing_stop or item.stop_loss)}",
                    f"TP1: {_format_price(item.tp1)}",
                    f"TP2: {_format_price(item.tp2)}",
                    f"TP3: {_format_price(item.tp3)}",
                    f"Net RR: {_format_rr(getattr(item, 'net_rr_after_costs', None))}",
                    f"İlerleme: {progress}",
                    "",
                ])
        return "\n".join(lines).rstrip()

    def handle_takip(self) -> str:
        """Show signal outcomes and accepted pool setups without conflating them."""
        outcomes = self.runtime.signal_outcomes(limit=500)
        pool_active = get_opportunity_pool().get_active_setups()
        if not outcomes and not pool_active:
            return "ATLAS | TAKİP\n\nAçık sinyal veya kabul edilmiş setup yok."

        terminal = {"TP1", "TP2", "TP3", "SL", "EXPIRED"}
        pending = sorted(
            [item for item in outcomes if str(item.get("status") or "PENDING").upper() == "PENDING"],
            key=lambda item: int(item.get("opened_at") or 0),
            reverse=True,
        )
        closed = sorted(
            [item for item in outcomes if str(item.get("status") or "").upper() in terminal],
            key=lambda item: int(item.get("resolved_at") or item.get("opened_at") or 0),
            reverse=True,
        )[:8]
        active_untracked = [
            setup for setup in pool_active
            if not any(
                str(item.get("status") or "PENDING").upper() == "PENDING"
                and _same_tracked_setup(setup, item)
                for item in outcomes
            )
        ]

        lines = ["ATLAS | TAKİP", f"Açık: {len(pending)} | Son kapanan: {len(closed)} | Havuz setup: {len(active_untracked)}"]
        if pending:
            lines.extend(["", "SİNYAL SONUÇ TAKİBİ"])
            for item in pending:
                lines.extend([_format_outcome_item(item, "TAKİPTE"), ""])
        if active_untracked:
            lines.extend(["", "HAVUZDA KABUL EDİLEN SETUPLAR"])
            for item in active_untracked:
                progress = f"TP{item.current_tp} ALINDI" if item.current_tp else "Hedef bekleniyor"
                lines.extend([
                    f"{str(item.symbol).replace(':USDT', '')} | {item.direction}",
                    f"Strateji: {item.strategy_name} | Durum: {item.status}",
                    f"Giriş: {_format_price(item.entry_filled_price or item.entry_price)} | "
                    f"Stop: {_format_price(item.trailing_stop or item.stop_loss)}",
                    f"TP1: {_format_price(item.tp1)} | TP2: {_format_price(item.tp2)} | TP3: {_format_price(item.tp3)}",
                    f"İlerleme: {progress}",
                    "Not: Bu kayıt henüz sinyal sonuç günlüğüyle eşleşmedi.",
                    "",
                ])
        if closed:
            lines.extend(["", "SONUÇLANAN SİNYALLER"])
            for item in closed:
                lines.extend([_format_outcome_item(item, "KAPANDI"), ""])
        lines.append("TP/SL sonuçları son işlenen kapalı 15m mumlarına dayanır; borsa fill teyidi değildir.")
        return "\n".join(lines).rstrip()

    def handle_liquidity(self, symbol: str) -> str:
        """Show a compact liquidity map for one Gate.io perpetual symbol."""
        from atlas_tui import _is_symbol_input
        if not _is_symbol_input(symbol):
            return "ATLAS | LİKİDİTE\nKullanım: /likidite BTC"
        outcome = self.runtime.analyze_symbol(symbol, force_refresh=True, track_signal=False)
        if not outcome.get("ok"):
            return (
                f"ATLAS | {symbol.upper()} LİKİDİTE\n"
                "Analiz tamamlanamadı. Piyasa verisini ve sembolü kontrol et."
            )
        result = outcome.get("result") or {}
        analysis = result.get("analysis") or {}
        layers = analysis.get("liquidity_layers") or {}
        sweep = analysis.get("liquidity_sweep") or {}
        lines = [
            f"ATLAS | {str(result.get('symbol') or symbol).replace(':USDT', '')} LİKİDİTE",
            "",
        ]
        for key, label in (("bsl", "ÜST LİKİDİTE / BSL"), ("ssl", "ALT LİKİDİTE / SSL"),
                           ("eqh", "EŞİT ZİRVELER / EQH"), ("eql", "EŞİT DİPLER / EQL")):
            levels = layers.get(key) or []
            prices = []
            for item in sorted(levels, key=lambda row: float(row.get("touches", 0) or 0), reverse=True)[:3]:
                prices.append(
                    f"{_format_price(item.get('price'))} ({item.get('touches', 0)} temas)"
                )
            lines.append(f"{label}: " + (", ".join(prices) if prices else "Bulunamadı"))
        post = sweep.get("post_structure") or {}
        direction = "BEARISH" if sweep.get("buy_side") else ("BULLISH" if sweep.get("sell_side") else "YOK")
        lines.extend([
            "",
            "SON SÜPÜRME",
            f"Durum: {'VAR' if sweep.get('is_sweep') else 'YOK'} | Yön: {direction}",
            f"BSL alındı: {'Evet' if sweep.get('buy_side') else 'Hayır'}",
            f"SSL alındı: {'Evet' if sweep.get('sell_side') else 'Hayır'}",
            f"Yapı teyidi: {'Var' if post.get('confirmed') else 'Yok'}",
            "",
            "Bu çıktı likidite haritasıdır; tek başına işlem sinyali değildir.",
        ])
        return "\n".join(lines)

    def handle_performance(self) -> str:
        """Show outcome performance only; learning details belong to /ogrenme."""
        signal = self.runtime.signal_performance()
        manual = self.runtime.manual_performance()
        lines = [
            "ATLAS | PERFORMANS",
            "",
            "OTOMATİK SİNYALLER (teorik takip)",
            f"Kapanan: {signal.get('closed', 0)} | Kazanç: {signal.get('wins', 0)} | Kayıp: {signal.get('losses', 0)}",
            f"Winrate: %{float(signal.get('winrate', 0) or 0):.1f}",
            f"Expectancy: {float(signal.get('expectancy', 0) or 0):+.2f}R | PF: {float(signal.get('profit_factor', 0) or 0):.2f}",
            f"TP1/TP2/TP3: {signal.get('tp1', 0)}/{signal.get('tp2', 0)}/{signal.get('tp3', 0)} | SL: {signal.get('sl', 0)}",
            "",
            "MANUEL İŞLEMLER (kullanıcı kayıtları)",
            f"Kapanan: {manual.get('total', 0)} | Kazanç: {manual.get('wins', 0)} | Kayıp: {manual.get('losses', 0)} | Açık: {manual.get('open', 0)}",
            f"Winrate: %{float(manual.get('winrate', 0) or 0):.1f}",
            f"Expectancy: {float(manual.get('expectancy', 0) or 0):+.2f}R | PF: {float(manual.get('profit_factor', 0) or 0):.2f}",
            "",
            "Not: Otomatik sinyal takibi ve manuel işlemler ayrı hesaplanır.",
        ]
        if int(signal.get("closed", 0) or 0) < 20:
            lines.append("Otomatik sinyal örneklemi 20 kapanan işlemin altında.")
        return "\n".join(lines)

    def handle_statistics(self) -> str:
        """Show seven-strategy generation and common-filter statistics."""
        status = self.runtime.scan_status()
        telemetry = status.get("strategy_telemetry") or {}
        rows = telemetry.get("per_strategy") or {}
        names = (
            ("smc", "SMC"),
            ("relative_strength", "RELATIVE STRENGTH"),
            ("trend_pullback", "TREND PULLBACK"),
            ("orderflow_momentum", "ORDERFLOW MOMENTUM"),
            ("mean_reversion", "MEAN REVERSION"),
            ("liquidation_cascade", "LIQUIDATION CASCADE"),
            ("volatility_breakout", "VOLATILITY BREAKOUT"),
        )
        lines = [
            "ATLAS | STRATEJİ İSTATİSTİĞİ",
            "",
            f"Analiz: {telemetry.get('analyses', 0)}",
            f"Ham setup: {telemetry.get('raw_setups_generated', 0)}",
            "",
        ]
        for key, label in names:
            item = rows.get(key) or {}
            no_setup = sum(int(item.get(k, 0) or 0) for k in (
                "no_setup", "condition_not_met", "missing_data",
                "insufficient_history", "errors", "other_no_setup",
            ))
            lines.append(
                f"{label}: {item.get('setups', 0)} setup | "
                f"{item.get('passed', 0)} geçti | {item.get('rejected', 0)} elendi | "
                f"{no_setup} setup yok"
            )
        lines.extend([
            "",
            "ORTAK FİLTRE",
            f"Geçen: {telemetry.get('common_filter_passed', 0)}",
            f"Elenen: {telemetry.get('common_filter_rejected', 0)}",
            "Not: Strateji setup üretimi ile nihai seçim ayrı aşamalardır.",
        ])
        return "\n".join(lines)

    def handle_learning(self) -> str:
        """Show only the learning engine's input and validation state."""
        learning = self.runtime.learning_panel()
        meta = learning.get("feed_meta") or {}
        return "\n".join([
            "ATLAS | ÖĞRENME MOTORU",
            "",
            f"Kaynak: {learning.get('source') or 'Henüz veri yok'}",
            f"Öğrenmeye alınan kayıt: {learning.get('records_fed', 0)}",
            f"Kapanan manuel işlem: {learning.get('closed_manual_trades', 0)}",
            f"Eşleşen setup: {learning.get('matched_setups', 0)}",
            f"Tarihsel edge: {learning.get('historical_edge', '—')}",
            f"Güvenilirlik: {learning.get('reliability', '—')}",
            f"Skor düzeltmesi: {float(learning.get('learning_adjustment', 0) or 0):+g} puan",
            f"Out-of-sample doğrulaması: {'Gerekli' if meta.get('oos_required') else 'Gerekli değil / belirtilmemiş'}",
            "",
            "Öğrenme çıktısı tek başına işlem sinyali veya kârlılık garantisi değildir.",
        ])

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        seconds = max(0.0, float(seconds or 0.0))
        if seconds < 60:
            return f"{seconds:.0f} sn"
        minutes = seconds / 60
        if minutes < 60:
            return f"{minutes:.1f} dk"
        hours = minutes / 60
        if hours < 24:
            return f"{hours:.1f} sa"
        days = hours / 24
        return f"{days:.1f} gün"

    def handle_status(self) -> str:
        """Show bot connectivity and Atlas service state, not host resource details."""
        snap = self.runtime.snapshot()
        scanner = snap.get("scanner") or {}
        tg = self.runtime.telegram_status()
        status = str(scanner.get("status") or "UNKNOWN").upper()
        service = "ÇALIŞIYOR" if tg.get("service_running") else "DURDU"
        polling = "AÇIK" if tg.get("polling_enabled") else "KAPALI"
        uptime = self._format_uptime(
            max(0, int(time.time() * 1000 - int(scanner.get("started_at") or 0)) / 1000)
            if scanner.get("started_at") else 0
        )
        bot = self._bot_info_cache or {}
        return "\n".join([
            "ATLAS | SERVİS DURUMU",
            "",
            f"Bot: {bot.get('first_name', 'Atlas')} (@{bot.get('username', '?')})",
            f"Servis: {service} | Telegram polling: {polling}",
            f"Tarama: {status} | Döngü: {scanner.get('cycle', 0)}",
            f"İşlenen: {scanner.get('processed', 0)} | Başarılı: {scanner.get('success', 0)} | Hatalı: {scanner.get('failed', 0)}",
            f"Çalışma süresi: {uptime}",
            "",
            "Kuyruk ayrıntısı: /taramadurum",
            "Sunucu kaynakları: /sistem",
        ])

    def handle_system(self) -> str:
        """Show host resource usage; service connectivity belongs to /durum."""
        import os
        import shutil
        import resource
        import threading
        try:
            import psutil
        except ImportError:
            total_pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_ram = total_pages * page_size
            available_pages = os.sysconf("SC_AVPHYS_PAGES")
            available_ram = available_pages * page_size
            disk = shutil.disk_usage("/")
            load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return "\n".join([
                "ATLAS | SİSTEM KAYNAKLARI",
                "",
                f"CPU: {os.cpu_count() or 0} çekirdek | Load: {load_avg[0]:.2f}/{load_avg[1]:.2f}/{load_avg[2]:.2f}",
                f"RAM: {total_ram / 1024**3:.1f} GB | Boş: {available_ram / 1024**3:.1f} GB",
                f"Disk: {disk.total / 1024**3:.1f} GB | Boş: {disk.free / 1024**3:.1f} GB",
                f"Atlas tepe belleği: {usage.ru_maxrss / 1024:.1f} MB | Thread: {threading.active_count()}",
                "Anlık CPU/RAM yüzdeleri gösterilemiyor (psutil kurulu değil).",
            ])
        cpu_count = psutil.cpu_count()
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
        process = psutil.Process()
        p_mem = process.memory_info().rss / 1024 / 1024
        p_cpu = process.cpu_percent(interval=0.1)
        return "\n".join([
            "ATLAS | SİSTEM KAYNAKLARI",
            "",
            f"CPU: {cpu_count} çekirdek | Kullanım: %{cpu_percent:.1f} | Load: {load_avg[0]:.2f}/{load_avg[1]:.2f}/{load_avg[2]:.2f}",
            f"RAM: {mem.total / 1024**3:.1f} GB | Kullanım: %{mem.percent:.1f} | Boş: {mem.available / 1024**3:.1f} GB",
            f"Disk: {disk.total / 1024**3:.1f} GB | Kullanım: %{disk.percent:.1f} | Boş: {disk.free / 1024**3:.1f} GB",
            f"Atlas süreci: {p_mem:.1f} MB | CPU: %{p_cpu:.1f} | Thread: {process.num_threads()}",
        ])

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