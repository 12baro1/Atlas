"""On-demand Telegram command interface for the headless Atlas service.

Only the configured chat receives replies and durable virtual-position events.

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

import heapq
import logging
import math
import os
import queue
import re
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Optional
from zoneinfo import ZoneInfo

from telegram_prices import format_price as _format_price, format_plan_levels, tracked_levels

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
        command = re.sub(r"@[A-Za-z0-9_]+(?=\s|$)", "", command[1:], count=1)
    return command.strip()


def split_message(value: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    text = str(value or "")
    if not text:
        return [""]
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n\n", 0, limit + 1)
        if split_at <= 0:
            split_at = text.rfind("\n", 0, limit)
            if split_at < limit // 2:
                split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def _confirmed_targets(plan):
    hits = set(plan.get("tps_hit") or ())
    return [f"TP{level}" for level in (1, 2, 3)
            if level in hits or plan.get(f"hit_tp{level}") or plan.get("status") == f"TP{level}"]


def _trade_progress(plan):
    targets = _confirmed_targets(plan)
    parts = [", ".join(targets) + " alındı"] if targets else []
    if plan.get("status") == "SL":
        parts.append("Stop")
    return " · ".join(parts)


def _format_rr(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "Hesaplanmadı"
    if not math.isfinite(number):
        return "Hesaplanmadı"
    return f"{number:+.2f}R"


def _format_strategy_name(value):
    """Translate internal strategy IDs into readable Telegram labels."""
    raw = str(value or "Belirtilmedi").strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")
    labels = {
        "liquidation_cascade": "LIQUIDATION CASCADE",
        "mean_reversion": "MEAN REVERSION",
        "orderflow_momentum": "ORDERFLOW MOMENTUM",
        "relative_strength": "RELATIVE STRENGTH",
        "smc": "SMC",
        "trend_pullback": "TREND PULLBACK",
        "volatility_breakout": "VOLATILITY BREAKOUT",
    }
    return labels.get(key, raw.upper() if "_" in raw else raw)


def _format_ranking_source(value):
    """Hide internal ranking identifiers from Telegram users."""
    labels = {
        "gateio_24h_quote_volume": "24 saatlik USDT işlem hacmi",
        "alphabetical_fallback": "Alfabetik yedek sıralama",
    }
    raw = str(value or "").strip()
    return labels.get(raw, raw or "Bilinmiyor")


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
    return _format_strategy_name(strategy)


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

    strategy = _format_strategy_name(card.get("strategy") or card.get("strategy_id"))
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
        cmd_name = normalized.partition(" ")[0]
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


class TelegramDeliveryError(requests.RequestException):
    def __init__(self, state, retry_after=0):
        super().__init__("Telegram sendMessage failed")
        self.state = state
        self.retry_after = retry_after


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
        self._analysis_lock = threading.Lock()
        self._analysis_threads = {}
        self._reply_lock = threading.Lock()
        self._delivery = threading.local()
        self._bot_username = None
        self._bot_info_cache = None
        self._bot_info_cache_time = 0

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    @property
    def polling_active(self) -> bool:
        """Return whether the dedicated Telegram long-polling thread is alive."""
        return bool(
            self.enabled
            and not self.stop_flag.is_set()
            and self._thread is not None
            and self._thread.is_alive()
        )

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

    def stop(self, timeout: float = 25.0) -> bool:
        """Stop polling, command execution and active analyses within one deadline."""
        deadline = time.monotonic() + max(0.0, float(timeout))

        def remaining():
            return max(0.0, deadline - time.monotonic())

        self.stop_flag.set()
        for thread in (self._thread, self._command_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=remaining())

        with self._analysis_lock:
            analysis_threads = list(self._analysis_threads.values())
        for thread in analysis_threads:
            if thread.is_alive():
                thread.join(timeout=remaining())

        polling_alive = bool(self._thread and self._thread.is_alive())
        command_alive = bool(self._command_thread and self._command_thread.is_alive())
        analysis_alive = [thread.name for thread in analysis_threads if thread.is_alive()]

        # A Session must not be closed while another thread is using it.
        if not polling_alive:
            self._session.close()
        else:
            self.logger.warning("Telegram polling thread still active at shutdown")

        if not analysis_alive and not command_alive and not polling_alive:
            self._reply_session.close()
        else:
            if analysis_alive:
                self.logger.warning(
                    "Telegram analyses still finishing at shutdown: %s", analysis_alive
                )
            if command_alive:
                self.logger.warning("Keeping Telegram reply session open while command worker exits")
        return not polling_alive and not command_alive and not analysis_alive

    def _fetch_bot_info(self) -> None:
        """Fetch bot username for @BotName command parsing."""
        try:
            result = self._api("getMe", {})
            self._bot_username = result.get("username", "").lower()
            self._bot_info_cache = result
            self._bot_info_cache_time = time.time()
            self.logger.info("Telegram bot info: @%s", self._bot_username)
            try:
                self._api("setMyCommands", {"commands": get_botfather_commands()})
                self.logger.info("Telegram command menu synchronized | commands=%s", len(get_botfather_commands()))
            except Exception:
                self.logger.exception("Telegram command menu synchronization failed")
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
            if method == "sendMessage":
                try:
                    body = response.json()
                except ValueError:
                    body = None
                rejected = isinstance(body, dict) and body.get("ok") is False
                code = body.get("error_code", response.status_code) if rejected else response.status_code
                if code == 429:
                    params = body.get("parameters") if isinstance(body, dict) else None
                    try:
                        delay = int((params or {}).get("retry_after", 0))
                    except (AttributeError, ValueError, TypeError):
                        delay = 0
                    raise TelegramDeliveryError("retry", max(1, delay))
                if rejected:
                    raise TelegramDeliveryError("retry" if isinstance(code,int) and code >= 500 else "failed")
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                raise RuntimeError(f"Telegram {method} was rejected")
            self.logger.debug("Telegram API success: %s (%.3fs)", method, elapsed)
            if method == "sendMessage":
                self.logger.info("Telegram reply sent | characters=%s", len(str(payload.get("text") or "")))
            return result.get("result")
        except TelegramDeliveryError:
            raise
        except requests.RequestException as exc:
            elapsed = time.perf_counter() - start
            status = getattr(exc.response, "status_code", None)
            self.logger.error("Telegram %s failed | type=%s status=%s (%.3fs)",
                              method, type(exc).__name__, status, elapsed)
            if method == "sendMessage":
                if isinstance(exc, requests.ConnectTimeout):
                    raise TelegramDeliveryError("retry") from None
                if status and 400 <= status < 500:
                    raise TelegramDeliveryError("failed") from None
                raise TelegramDeliveryError("uncertain") from None
            # requests exceptions can contain the entire bot-token URL.
            raise requests.RequestException(f"Telegram {method} failed (HTTP {status})") from None

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
                try:
                    self._deliver_notifications()
                except Exception as exc:
                    self.logger.warning("Notification delivery deferred | type=%s", type(exc).__name__)
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

    def _deliver_notifications(self):
        tracking = get_opportunity_pool().tracking
        for _ in range(5):
            claim = tracking.claim_notification(self.chat_id)
            if not claim:
                return
            event_id, message, attempt = claim
            try:
                with self._reply_lock:
                    receipt = self._api("sendMessage", {"chat_id": self.chat_id, "text": message},
                                        timeout=10, session=self._reply_session)
                if (not isinstance(receipt, dict) or type(receipt.get("message_id")) is not int
                        or receipt["message_id"] <= 0
                        or str((receipt.get("chat") or {}).get("id")) != self.chat_id):
                    raise TelegramDeliveryError("uncertain")
            except TelegramDeliveryError as exc:
                state = "failed" if exc.state == "retry" and attempt >= 8 else exc.state
                delay = max(exc.retry_after, min(600, 2 ** attempt)) if state == "retry" else 0
                tracking.finish_notification(self.chat_id,event_id,attempt,state,retry_after=delay)
                return
            except Exception:
                tracking.finish_notification(self.chat_id,event_id,attempt,"uncertain")
                return
            tracking.finish_notification(self.chat_id,event_id,attempt,"sent",message_id=receipt["message_id"])

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

        head = raw_command.split()[0]
        if head.startswith("/") and "@" in head and self._bot_username:
            if head.partition("@")[2].lower() != self._bot_username:
                return
        command = normalize_command(raw_command)
        if not command or not is_recognized_command(raw_command):
            self.logger.debug("Telegram text ignored: unrecognized command")
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

    def _send_command_reply(self, message: str) -> bool:
        # requests.Session is not thread-safe. Background analyses may finish
        # concurrently, so serialize access to the dedicated reply session.
        with self._reply_lock:
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
                    return False
        return True

    def _command_and_reply(self, command):
        self._delivery.actions = []
        try:
            message = self.execute_command(command)
            if self._send_command_reply(message):
                for callback in self._delivery.actions:
                    callback()
        except Exception as exc:
            self.logger.warning("Telegram delivery or subscription failed | type=%s",type(exc).__name__)
        finally:
            del self._delivery.actions

    def _analysis_symbol_for_command(self, raw_command: str):
        """Return a symbol only for commands routed to the long-running analyzer."""
        normalized = normalize_command(raw_command)
        if not str(raw_command or "").strip().startswith("/"):
            return None
        parts = normalized.split(maxsplit=1)
        if not parts:
            return None
        command = get_command_by_name(parts[0].lower())
        if command is None and len(parts) == 1:
            from atlas_tui import _is_symbol_input
            return parts[0].upper() if _is_symbol_input(parts[0]) else None
        if not command or command.handler != "handle_analyze_symbol":
            return None
        symbol = parts[1] if command.takes_parameter and len(parts) > 1 else parts[0]
        return str(symbol or "").strip().upper() or None

    def _run_background_analysis(self, raw_command: str, command_label: str, symbol: str):
        try:
            self.logger.info(
                "Telegram background analysis started: %s | symbol=%s",
                command_label[:80], symbol,
            )
            self._command_and_reply(raw_command)
            self.logger.info(
                "Telegram background analysis completed: %s | symbol=%s",
                command_label[:80], symbol,
            )
        finally:
            with self._analysis_lock:
                self._analysis_threads.pop(symbol, None)

    def _dispatch_background_analysis(self, raw_command: str, command_label: str) -> bool:
        """Run slow single-symbol analyses outside the serial command worker."""
        symbol = self._analysis_symbol_for_command(raw_command)
        if not symbol:
            return False
        with self._analysis_lock:
            existing = self._analysis_threads.get(symbol)
            if existing and existing.is_alive():
                self._send_command_reply(
                    f"ATLAS | {symbol}\nBu sembolün analizi zaten çalışıyor. Sonuç bekleniyor."
                )
                return True
            if len(self._analysis_threads) >= 3:
                self._send_command_reply(
                    "ATLAS | ANALİZ KUYRUĞU DOLU\nEn fazla 3 sembol analizi aynı anda çalışabilir."
                )
                return True
            thread = threading.Thread(
                target=self._run_background_analysis,
                args=(raw_command, command_label, symbol),
                name=f"atlas-telegram-analysis-{symbol.lower()}",
                daemon=True,
            )
            self._analysis_threads[symbol] = thread
            self._send_command_reply(
                f"ATLAS | {symbol} ANALİZİ BAŞLADI\nSonuç hazır olduğunda bu gruba gönderilecek."
            )
            thread.start()
        return True

    def _command_worker_loop(self) -> None:
        while not self.stop_flag.is_set() or not self._command_queue.empty():
            try:
                raw_command, command_label = self._command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.logger.info("Telegram command execution started: %s", command_label[:80])
                if self._dispatch_background_analysis(raw_command, command_label):
                    self.logger.info(
                        "Telegram analysis delegated to background worker: %s",
                        command_label[:80],
                    )
                    continue
                self._command_and_reply(raw_command)
                self.logger.info("Telegram command execution completed: %s", command_label[:80])
            finally:
                self._command_queue.task_done()

    def execute_command(self, command: str) -> str:
        try:
            return self._execute_command(command)
        except Exception as exc:
            self.logger.warning("Telegram command unavailable | type=%s", type(exc).__name__)
            return "Komut tamamlanamadı. Biraz sonra tekrar deneyin."

    def _execute_command(self, command: str) -> str:
        """Execute a recognized command and return formatted response."""
        from atlas_tui import (
            AtlasTUIApp,
            _is_report_command,
            _is_symbol_input,
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
            if not parts:
                return self.handle_help()
            cmd_name = parts[0].lower()
            param = parts[1] if len(parts) > 1 else None
            cmd_def = get_command_by_name(cmd_name)
            if cmd_def:
                handler_name = cmd_def.handler
                handler = getattr(self, handler_name, None)
                if handler:
                    if cmd_def.takes_parameter:
                        if param:
                            return handler(param)
                        return f"KULLANIM: /{cmd_def.name} <{cmd_def.parameter_name}>"
                    else:
                        if param:
                            return f"KULLANIM: /{cmd_def.name}"
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

        if lowered in {"mevcut", "setuplar", "takip", "islemler"}:
            return self.handle_islemler()

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

        plain_scan = re.fullmatch(r"([+-]?[0-9]+)\s+tara", lowered)
        if plain_scan:
            return self.handle_scan(plain_scan[1])
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
                else (
                    f"ATLAS | {symbol.upper()}\n"
                    "Likidite analizi tamamlanamadı. Sembolü ve piyasa verisini kontrol et."
                )
            )

        if scan_request is not None:
            # All legacy scan text also goes through the real scan queue.
            return self._queue_scan_report(scan_request[0])

        # Single symbol analysis (legacy plain-text like "BTC")
        if _is_symbol_input(normalized) and not raw.startswith("/"):
            # Bare symbol without slash is treated as chat in groups
            return "Slash komut kullanın: /btc, /eth, /analiz BTC"

        if raw.startswith("/") and _is_symbol_input(normalized):
            return self.handle_analyze_symbol(normalized)
        return "Komut tanınmadı. /yardim"

    # --- Command Handlers ---

    def handle_start(self) -> str:
        """Handle Telegram's conventional /start command."""
        return (
            "ATLAS | KOMUT MERKEZİ\n\n"
            "Analiz: /btc, /eth, /sol, /analiz BTC\n"
            "Tarama: /tara 20, /tara 30, /20tara, /tumtara\n"
            "Havuz: /havuz, /eniyi5, /eniyi10, /setup BTC\n"
            "İşlemler: /islemler, /gecmis, /likidite BTC\n"
            "Sistem: /motorlar, /veri, /taramadurum, /durum, /sistem\n\n"
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

        from opportunity_pool import get_opportunity_pool

        pool = get_opportunity_pool()
        normalized_symbol = self.runtime.normalize_symbol(symbol)
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

        message = _format_telegram_card(card, outcome.get("elapsed_ms", 0))
        if "cycle_result" in outcome:
            row = outcome["cycle_result"]
            if row.get("setup") and card.get("decision_action") not in {"EXECUTE","EXECUTE_WITH_CAUTION"}:
                return message
            if hasattr(self._delivery,"actions"):
                self._delivery.actions.append(lambda: pool.tracking.follow_analysis(self.chat_id, row))
            else:
                pool.tracking.follow_analysis(self.chat_id, row)
            return message
        return message

    def handle_scan(self, cmd_name=None) -> str:
        """Handle /tara [N] and legacy /20tara ... commands."""
        limit = self._parse_scan_limit(cmd_name)
        if limit is None:
            return "KULLANIM: /tara <1-1000>"
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
            f"Sıralama: {_format_ranking_source(inventory.get('ranking_source'))}",
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
        if not result.get("started"):
            return (
                "ATLAS | TARAMA SÜRDÜRÜLEMEDİ\n"
                "Bekleyen iş bulunmuyor veya tarama başlatılamadı.\n"
                "Mevcut kuyruk: /taramadurum"
            )
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


    def handle_pool(self) -> str:
        """Show the current validated opportunity pool without starting a scan."""
        return self._format_best_setups(20)

    def handle_setup_symbol(self, symbol: str) -> str:
        """Show every live pool setup for one symbol, grouped by lifecycle."""
        from atlas_tui import _is_symbol_input
        if not _is_symbol_input(symbol):
            return "KULLANIM: /setup BTC"
        normalized = self.runtime.normalize_symbol(symbol)
        items = get_opportunity_pool().get_validated_setups(symbol=normalized, limit=1)
        if not items:
            return f"{normalized} — Doğrulanmış setup yok."
        item = items[0]
        return _format_telegram_card(dict(symbol=item.symbol, direction=item.direction,
            strategy=item.strategy_name, decision_action="EXECUTE", entry_type=item.entry_type,
            entry=item.entry_price, stop_loss=item.stop_loss, tp_levels=[item.tp1,item.tp2,item.tp3],
            net_rr=item.net_rr_after_costs))

    def handle_history(self) -> str:
        """Show recent completed and invalidated signal records."""
        rows = get_opportunity_pool().tracking.iter_tracked(self.chat_id)
        history = heapq.nlargest(15, (row for row in rows if row[2] in {"CLOSED", "INVALIDATED"}),
                                 key=lambda row: row[3].get("resolved_at") or row[3]["opened_at"])
        lines = ["SİNYAL GEÇMİŞİ"]
        for symbol, revision, state, plan in history:
            label = "Geçersizleşti" if state == "INVALIDATED" else f"{_trade_progress(plan) or plan['status']} | {plan['realized_r']:+.2f}R"
            lines.append(f"{symbol.split('/')[0]} | {plan['direction']} | {plan['strategy']} | {label} (v{revision})")
            lines.append(tracked_levels(plan))
        if not history:
            lines.append("Henüz kapanan veya geçersizleşen takip kaydı yok.")
        return "\n".join(lines)

    def handle_motors(self) -> str:
        """Report all seven independent strategy generation counters."""
        telemetry = (self.runtime.scan_status().get("strategy_telemetry") or {})
        rows = telemetry.get("per_strategy") or {}
        strategies = (
            ("smc", "SMC"),
            ("trend_pullback", "TREND PULLBACK"),
            ("volatility_breakout", "VOLATILITY BREAKOUT"),
            ("mean_reversion", "MEAN REVERSION"),
            ("liquidation_cascade", "LIQUIDATION CASCADE"),
            ("orderflow_momentum", "ORDERFLOW MOMENTUM"),
            ("relative_strength", "RELATIVE STRENGTH"),
        )
        lines = ["ATLAS | 7 BAĞIMSIZ STRATEJİ", f"Toplam analiz: {telemetry.get('analyses', 0)}"]
        for key, label in strategies:
            item = rows.get(key) or {}
            lines.extend([
                "",
                label,
                f"Setup: {item.get('setups', 0)} | Filtreyi geçti: {item.get('passed', 0)} | Elendi: {item.get('rejected', 0)}",
                f"Setup yok: {item.get('no_setup', 0)} | Veri eksik: {item.get('missing_data', 0)} | Hata: {item.get('errors', 0)}",
            ])
        lines.extend(["", "Ayrıntılı ortak filtre istatistiği: /istatistik"])
        return "\n".join(lines)

    def handle_data_status(self) -> str:
        """Report Gate.io market inventory freshness and scan data availability."""
        status = self.runtime.scan_status()
        inventory = status.get("inventory") or {}
        error = inventory.get("last_error")
        age = inventory.get("last_refresh_age_seconds")
        age_text = (str(int(float(age))) + " saniye önce") if age is not None else "Bilinmiyor"
        lines = [
            "ATLAS | PİYASA VERİSİ",
            "",
            "Borsa: Gate.io",
            f"USDT Perpetual sözleşme: {inventory.get('symbol_count', 0)}",
            f"Envanter sıralaması: {_format_ranking_source(inventory.get('ranking_source'))}",
            f"Son yenileme: {age_text}",
            f"Envanter durumu: {'HATA' if error else 'KULLANILABİLİR'}",
        ]
        if error:
            lines.append("Son hata: " + str(error)[:180])
        lines.extend(["", "Tarama kuyruğu: /taramadurum"])
        return "\n".join(lines)

    def handle_pool_status(self) -> str:
        """Show only persistent opportunity-pool contents."""
        pool = get_opportunity_pool()
        stats = pool.get_stats()
        best = pool.get_best_setups(limit=1)
        lines = [
            "ATLAS | FIRSAT HAVUZU",
            "",
            f"Aday: {stats.get('candidates', 0)}",
            f"Doğrulanmış: {stats.get('validated', 0)}",
            f"Aktif takip: {stats.get('active', 0)}",
            f"Arşiv: {stats.get('history', 0)}",
        ]
        if best:
            item = best[0]
            entry_type = str(getattr(item, "entry_type", "") or getattr(item, "setup_type", "—")).upper()
            lines.extend([
                "",
                "EN YÜKSEK SIRALAMALI SETUP",
                f"{str(item.symbol).replace(':USDT', '')} | {item.direction}",
                f"Strateji: {_format_strategy_name(item.strategy_name)} | Emir: {entry_type}",
                f"Giriş: {_format_price(item.entry_price)} | SL: {_format_price(item.stop_loss)}",
                f"TP1: {_format_price(item.tp1)} | TP2: {_format_price(item.tp2)} | TP3: {_format_price(item.tp3)}",
                f"Net RR: {_format_rr(item.net_rr_after_costs)}",
            ])
        else:
            lines.extend(["", "Doğrulanmış setup bulunmuyor."])
        lines.extend([
            "",
            "İşlem ve setup listesi: /islemler",
            "En iyi fırsatlar: /eniyi5",
        ])
        return "\n".join(lines)

    @staticmethod
    def _parse_scan_limit(cmd_name) -> Optional[int]:
        """Extract the requested scan size from a command name like '200tara'."""
        match = re.fullmatch(r"([0-9]{1,4})(?:tara)?", str(cmd_name or ""))
        if match and 1 <= int(match[1]) <= 1000:
            return int(match[1])
        return None

    def _queue_scan_report(self, limit: Optional[int]) -> str:
        """Start/queue a scan via the runtime scan service and report progress."""
        result = self.runtime.start_scan(limit)
        if not result.get("started"):
            return "ATLAS | TARAMA BAŞLATILAMADI\nMevcut tarama kuyruğu değiştirilmedi. /taramadurum ile durumu kontrol et."
        if result.get("continuous"):
            progress = result["progress"]
            return (f"300 sembollük tarama | Döngü {progress['generation']}\n"
                    f"Öncelik: hacim sıralamasındaki ilk {result['selected']} sembolün bekleyen işleri.\n"
                    f"Başarılı: {progress['done']} | Başarısız: {progress['failed']} | Bekleyen: {progress['pending']}")
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
            f"Sıralama: {_format_ranking_source(result.get('ranking_source'))}",
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
        pool = get_opportunity_pool()
        if count == 20:
            best = pool.get_best_setups(limit=pool.max_validated)
        elif hasattr(self._delivery,"actions"):
            best, shown = pool.prepare_best_reply(self.chat_id, count)
            if best:
                self._delivery.actions.append(lambda: pool.tracking.follow_delivered(self.chat_id,shown))
        else:
            best = pool.follow_best(self.chat_id, count)
        title = "HAVUZ" if count == 20 else f"EN İYİ {count} SETUP"
        if not best:
            return f"{title}\nDoğrulanmış setup havuzu boş."
        lines = [title]
        for index, item in enumerate(best, 1):
            lines.append(f"{index}. {item.symbol.replace(':USDT','')} | {item.direction} | "
                         f"{_format_strategy_name(item.strategy_name)} | {_format_rr(item.net_rr_after_costs)}")
            lines.append(format_plan_levels(item.entry_price, item.stop_loss, item.tp1, item.tp2, item.tp3))
        return "\n".join(lines)

    def handle_islemler(self) -> str:
        rows = get_opportunity_pool().tracking.iter_tracked(self.chat_id)
        tz = ZoneInfo("Europe/Istanbul")
        today = datetime.now(tz).date()
        sections = {
            "ACTIVE": ("Aktif", []),
            "WAITING": ("Giriş bekliyor", []),
            "AMBIGUOUS": ("DOĞRULAMA BEKLİYOR", []),
            "CLOSED": ("Bugün kapanan", []),
            "INVALIDATED": ("Bugün geçersizleşen", []),
        }
        closed_count = wins = losses = target_count = 0
        total = 0.0
        has_rows = False
        earlier_targets = []
        for symbol, _, state, plan in rows:
            has_rows = True
            if state not in sections:
                continue
            if state == "CLOSED":
                net = plan.get("realized_r", 0)
                closed_count += 1
                total += net
                wins += net > 0
                losses += net < 0
            if state in {"CLOSED", "INVALIDATED"}:
                resolved = datetime.fromtimestamp((plan.get("resolved_at") or 0) / 1000, tz)
                if resolved.date() != today:
                    if state == "CLOSED" and plan.get("resolved_at") and resolved.date() < today and _confirmed_targets(plan):
                        target_count += 1
                        row = (resolved, -target_count, symbol, plan)
                        if len(earlier_targets) < 10:
                            heapq.heappush(earlier_targets, row)
                        else:
                            heapq.heappushpop(earlier_targets, row)
                    continue
            sections[state][1].append((symbol, plan))

        count = sum(len(items) for _, items in sections.values())
        blocks = [f"İŞLEMLERİM — {count}"]
        for state, (heading, items) in sections.items():
            for index, (symbol, plan) in enumerate(items):
                card = []
                if index == 0:
                    card.append(f"{heading} ({len(items)})")
                label = f"{symbol.split('/')[0]} · {plan['direction']}"
                progress = _trade_progress(plan) or (plan["status"] if state == "CLOSED" else "")
                if progress:
                    label += f" · {progress}"
                card.append(label)
                card.append(tracked_levels(plan))
                if state == "AMBIGUOUS":
                    card.append(plan.get("ambiguity_reason") or "Geçmiş mumlar doğrulanacak")
                    if plan.get("manual_review"):
                        card.append("Kalıcı inceleme")
                    elif plan.get("retry_at"):
                        retry = datetime.fromtimestamp(plan["retry_at"] / 1000, tz)
                        card.append(f"Yeniden kontrol {retry:%H.%M} TSİ")
                blocks.append("\n".join(card))
        if not count:
            blocks.append("Takipte güncel setup yok.")
        if earlier_targets:
            shown = sorted(earlier_targets, reverse=True)
            history = [f"Önceki günlerde kapanan TP işlemleri ({len(shown)}/{target_count})"]
            for resolved, _, symbol, plan in shown:
                history.append(f"{resolved:%d.%m.%Y} · {symbol.split('/')[0]} · {plan['direction']} · "
                               f"{_trade_progress(plan)} · {plan['realized_r']:+.2f}R")
            blocks.append("\n".join(history))
        if has_rows:
            summary = ["Tüm dönem · kapanan işlemler",
                       f"Kapanan: {closed_count} | Kazanan: {wins} | Kaybeden: {losses}"]
            if closed_count:
                summary.append(f"Başarı: %{100*wins/closed_count:.1f}")
            summary.append(f"Kapanan net: {total:+.2f}R")
            blocks.append("\n".join(summary))

            live = [p for state in ("ACTIVE", "AMBIGUOUS") for _, p in sections[state][1]]
            if live:
                partial = sum(p.get("realized_r", 0) for p in live)
                marks = [p.get("open_r") for p in live]
                pnl = (f"{sum(marks):+.2f}R" if all(value is not None for value in marks)
                       else "doğrulanmış kapanış bekleniyor")
                blocks.append(f"Açık takip · kısmi TP (brüt): {partial:+.2f}R\nAçık sinyal PnL: {pnl}")
        blocks.append("Sanal sinyal takibi. Gerçek emir gönderilmez.")
        return "\n\n".join(blocks)

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
                    f"Strateji: {_format_strategy_name(item.strategy_name)} | Emir: {entry_type}",
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
                    f"Strateji: {_format_strategy_name(item.strategy_name)} | Durum: {item.status}",
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
        """Show journal-tracked signals only; pool setups belong to /setuplar."""
        outcomes = self.runtime.signal_outcomes(limit=500)
        if not outcomes:
            return "ATLAS | SİNYAL TAKİBİ\n\nAçık veya sonuçlanmış sinyal kaydı yok.\nBirleşik görünüm: /islemler"

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
        lines = [
            "ATLAS | SİNYAL TAKİBİ",
            f"Açık: {len(pending)} | Son kapanan: {len(closed)}",
        ]
        if pending:
            lines.extend(["", "AÇIK SİNYALLER"])
            for item in pending[:10]:
                lines.extend([_format_outcome_item(item, "TAKİPTE"), ""])
            if len(pending) > 10:
                lines.append(f"Diğer açık sinyaller: +{len(pending) - 10}")
        if closed:
            lines.extend(["", "SON KAPANAN SİNYALLER"])
            for item in closed:
                lines.extend([_format_outcome_item(item, "SONUÇLANDI"), ""])
        lines.extend([
            "",
            "TP/SL sonuçları son işlenen kapalı 15m mumlarına dayanır.",
            "Giriş seviyesinin görülmesi borsada fill gerçekleştiğini kanıtlamaz.",
        ])
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
        """Show cumulative profit/loss in R for automated and manual records."""
        signal = self.runtime.signal_performance()
        manual = self.runtime.manual_performance()
        lines = [
            "ATLAS | PERFORMANS",
            "",
            "OTOMATİK SİNYALLER",
            f"Kapanan: {signal.get('closed', 0)} | Kazançlı: {signal.get('wins', 0)} | Kayıplı: {signal.get('losses', 0)}",
            f"Toplam kazanç: {_format_rr(signal.get('positive_r', 0))}",
            f"Toplam kayıp: {_format_rr(signal.get('negative_r', 0))}",
            f"Net sonuç: {_format_rr(signal.get('net_r', 0))}",
            f"Başarı: %{float(signal.get('winrate', 0) or 0):.1f} | PF: {float(signal.get('profit_factor', 0) or 0):.2f}",
            f"TP1/TP2/TP3: {signal.get('tp1', 0)}/{signal.get('tp2', 0)}/{signal.get('tp3', 0)} | SL: {signal.get('sl', 0)}",
            "",
            "MANUEL İŞLEMLER",
            f"Kapanan: {manual.get('total', 0)} | Kazançlı: {manual.get('wins', 0)} | Kayıplı: {manual.get('losses', 0)} | Açık: {manual.get('open', 0)}",
            f"Toplam kazanç: {_format_rr(manual.get('positive_r', 0))}",
            f"Toplam kayıp: {_format_rr(manual.get('negative_r', 0))}",
            f"Net sonuç: {_format_rr(manual.get('net_r', 0))}",
            f"Başarı: %{float(manual.get('winrate', 0) or 0):.1f} | PF: {float(manual.get('profit_factor', 0) or 0):.2f}",
            "",
            "R toplamlarıdır; TL/USDT tutarı değildir. Otomatik sinyal ve manuel kayıtlar ayrı hesaplanır.",
        ]
        basis = manual.get("performance_basis")
        if basis == "mixed":
            lines.append("Manuel kayıtların bir kısmında gerçek komisyon/slippage, bir kısmında yalnızca fiyat farkı kullanılmış.")
        elif basis == "gross_price_only":
            lines.append("Manuel sonuçlar komisyon ve slippage düşülmeden hesaplanmış.")
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
        generation = (snap.get("scan_queue") or {}).get("generation", scanner.get("cycle", 0))
        return "\n".join([
            "ATLAS | SERVİS DURUMU",
            "",
            f"Bot: {bot.get('first_name', 'Atlas')} (@{bot.get('username', '?')})",
            f"Servis: {service} | Telegram polling: {polling}",
            f"Tarama: {status} | Döngü: {generation}",
            f"İşlenen: {scanner.get('processed', 0)} | Başarılı: {scanner.get('success', 0)} | Hatalı: {scanner.get('failed', 0)}",
            f"Çalışma süresi: {uptime}",
            "",
            f"Teslimi doğrulanamayan bildirim: {get_opportunity_pool().tracking.unconfirmed_notifications(self.chat_id)}",
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
