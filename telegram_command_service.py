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
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests

from telegram_commands import (
    TELEGRAM_COMMANDS,
    TelegramCommand,
    format_help_text,
    get_botfather_commands,
    get_command_by_name,
)

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 3900
MAX_COMMAND_AGE_SECONDS = 120

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


def _format_outcome_item(item, state):
    status = str(item.get("status") or "PENDING").upper()
    symbol = str(item.get("symbol") or "?").replace(":USDT", "")
    direction = str(item.get("direction") or "?").upper()
    progress, hit_levels = _outcome_progress(item)
    lines = [
        f"{symbol}  |  {direction}",
        f"Strateji: {_outcome_strategy(item)}",
        f"Durum: {state or status}",
    ]
    if item.get("signal_id"):
        lines.append(f"Sinyal ID: {item['signal_id']}")
    if item.get("entry") is not None:
        lines.append(f"Giriş: {_format_price(item.get('entry'))}")
    if item.get("stop_loss") is not None:
        lines.append(f"Stop: {_format_price(item.get('stop_loss'))}")
    targets = [
        f"TP{level}: {_format_price(item.get(f'tp{level}'))}"
        for level in (1, 2, 3) if item.get(f"tp{level}") is not None
    ]
    if targets:
        lines.append("Hedefler: " + "  |  ".join(targets))
    if status == "PENDING":
        if hit_levels:
            lines.append(f"Hedef ilerlemesi: {progress}")
            lines.append(f"Gerçekleşen kısmi getiri (brüt): {_format_rr(item.get('realized_r') or 0)}")
        elif item.get("entry_tracking_source") == "market_reference":
            lines.append("Giriş: MARKET referansı (borsa fill teyidi değil)")
        elif not item.get("entry_reached"):
            lines.append("Koşul: Giriş fiyatı bekleniyor")
    elif status in {"TP1", "TP2", "TP3", "SL"}:
        lines.append(f"Sonuç: {status}")
        lines.append(f"Net sonuç: {_format_rr(item.get('realized_r') or 0)}")
    elif status == "EXPIRED":
        lines.append("Sonuç: Süre doldu")
        if item.get("entry_reached"):
            lines.append("Not: Giriş seviyesi görülmüştü")
        else:
            lines.append("Not: Giriş seviyesi görülmedi")
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
        if opened.date() == today:
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
        "ATLAS | BUGÜNÜN İŞLEM TAKİBİ",
        f"{today:%d.%m.%Y}",
        divider,
        f"Verilen setup: {len(daily)}",
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
    """Format one selected setup as a human-readable Telegram trade plan."""
    symbol = str(card.get("symbol") or "?").replace(":USDT", "")
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
    divider = "━━━━━━━━━━━━━━━━━━━━"
    if not executable:
        reason = str(card.get("reason") or "Ortak karar mekanizması geçerli işlem planı üretmedi.")
        blockers = card.get("critical_blocks") or []
        lines = [
            divider,
            f"ATLAS | {symbol}",
            divider,
            "GEÇERLİ SETUP YOK",
            f"Neden: {reason[:240]}",
        ]
        if blockers:
            lines.append("Kontrol edilecekler: " + " | ".join(str(item) for item in blockers[:3]))
        lines.extend([
            "",
            "Bu sembolde şu an işlem açılabilecek doğrulanmış bir plan bulunmadı.",
        ])
        return "\n".join(lines)

    strategy = card.get("strategy") or card.get("strategy_id") or "Belirtilmedi"
    targets = card.get("tp_levels") or []
    rr = card.get("net_rr")
    if rr is None:
        rr = card.get("weighted_net_rr")
    if rr is None:
        rr = card.get("rr")

    direction_label = "LONG" if direction == "LONG" else "SHORT"
    lines = [
        f"ATLAS  |  {card.get('symbol') or symbol}",
        f"{'🟢' if direction == 'LONG' else '🔴'} {symbol} — {direction_label}",
        divider,
        "İŞLEM PLANI",
        f"Strateji: {strategy}",
        f"Emir tipi: {entry_type}",
        f"Giriş: {_format_price(card.get('entry'), grouping=False)}",
        f"Stop Loss: {_format_price(card.get('stop_loss'), grouping=False)}",
    ]
    if targets:
        lines.extend(["", "HEDEFLER"])
        lines.extend(
            f"TP{index}: {_format_price(target, grouping=False)}"
            for index, target in enumerate(targets[:3], start=1)
        )
    lines.extend([
        "",
        f"Net RR: {_format_rr(rr) if rr is not None else 'Hesaplanmadı'}",
        f"Risk/Getiri (Net RR): {_format_rr(rr) if rr is not None else 'Hesaplanmadı'}",
    ])

    thesis = str(card.get("setup_thesis") or "").strip()
    supporting = card.get("supporting_evidence") or []
    context = card.get("market_context") or []
    opposing = card.get("opposing_evidence") or []
    evidence_lines = []
    if thesis and thesis.lower() != str(strategy).lower():
        evidence_lines.append(thesis)
    evidence_lines.extend(str(item).strip() for item in supporting if str(item).strip())
    evidence_lines.extend(str(item).strip() for item in context if str(item).strip())
    if evidence_lines:
        lines.extend(["", "SETUP GEREKÇESİ"])
        lines.extend(f"• {item[:180]}" for item in evidence_lines[:4])
    if opposing:
        lines.extend(["", "DİKKAT"])
        lines.extend(f"• Karşı kanıt: {str(item)[:160]}" for item in opposing[:2])

    lines.extend(["", divider])
    if entry_type == "LIMIT":
        lines.append("DURUM: Giriş fiyatı bekleniyor.")
        lines.append("LIMIT giriş seviyesi bekleniyor.")
        lines.append("Fiyat belirlenen LIMIT seviyesine gelmeden giriş varsayılmaz.")
    else:
        lines.append("DURUM: MARKET planı hazır.")
        lines.append("Borsa emri veya gerçekleşmiş fill teyidi değildir.")
        lines.append("Bu mesaj yalnızca analiz planıdır; borsada emir gönderilmez.")
    lines.append("Atlas otomatik emir göndermez.")
    lines.append(divider)
    if elapsed_ms:
        lines.append(f"Analiz süresi: {elapsed_ms / 1000:.1f} sn")
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
        or normalized == "eniyi5"
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
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="atlas-telegram-commands",
            daemon=True,
        )
        self._thread.start()
        # Fetch bot username for @BotName command support
        self._fetch_bot_info()
        return True

    def stop(self, timeout: float = 25.0) -> None:
        self.stop_flag.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.0, float(timeout)))
        self._session.close()

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

    def _api(self, method: str, payload: dict, timeout=25):
        """Make Telegram API call with diagnostics logging."""
        start = time.perf_counter()
        self.logger.debug("Telegram API call: %s", method)
        try:
            response = self._session.post(
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
            return result.get("result")
        except requests.RequestException as exc:
            elapsed = time.perf_counter() - start
            self.logger.error("Telegram API network error: %s | %s (%.3fs)", method, exc, elapsed)
            raise

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

        self.logger.debug(
            "Update received: chat_id=%s sender_id=%s is_bot=%s text=%s",
            chat_id, sender_id, is_bot, str(message.get("text", ""))[:80]
        )

        # Chat ID validation
        if chat_id != self.chat_id:
            self.logger.debug("Chat ID mismatch: expected=%s got=%s", self.chat_id, chat_id)
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
            self.logger.debug("Unrecognized command ignored: %s", raw_command[:80])
            return

        self.logger.info("Telegram command received: %s (chat_id=%s)", command[:80], chat_id)
        try:
            result = self.execute_command(raw_command)
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
                        return handler()
                else:
                    self.logger.error("Handler not found: %s", handler_name)
                    return f"Komut işleyici eksik: {handler_name}"

        # Legacy plain-text commands (backward compatibility)
        if lowered in {"yardım", "yardim", "help", "?"}:
            return self.handle_help()

        if lowered == "mevcut":
            return self.handle_mevcut()

        # Reuse TUI formatting and scan logic
        adapter = SimpleNamespace(
            runtime=self.runtime,
            _show=lambda _message: None,
            call_from_thread=lambda callback, *args, **kwargs: callback(*args, **kwargs),
        )

        cached_best_request = lowered == "eniyi5"
        scan_request = _parse_scan_command("en iyi 5 işlem" if cached_best_request else lowered)
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
            return self._execute_scan(scan_request, cached_best_request)

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
                f"{symbol.upper()} ANALİZ EDİLEMEDİ\n\n"
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

    def handle_scan(self) -> str:
        """Handle /20tara, /30tara, /50tara, /100tara"""
        from atlas_tui import _parse_scan_command

        # Extract number from command name like "20tara"
        cmd_name = normalize_command(self._last_raw_command or "").split()[0]
        # We don't have the raw command here, so we'll parse from the command
        # This is a limitation - we'll need to pass the raw command
        # For now, default to configured scan limit
        return self._execute_scan((None, 5), False)

    def handle_scan_all(self) -> str:
        """Handle /tumtara - scan all supported markets"""
        from atlas_tui import _best_symbols

        scan_limit = None  # None means all
        return self._execute_scan((scan_limit, 5), False)

    def handle_best_five(self) -> str:
        """Handle /eniyi5 - get best 5 from existing pool, no new scan"""
        return self._execute_scan((None, 5), True)

    def handle_mevcut(self) -> str:
        """Handle /mevcut - today's setup and trade tracking"""
        outcomes = self.runtime.signal_outcomes(limit=5000)
        return format_daily_signal_report(outcomes)

    def handle_setuplar(self) -> str:
        """Handle /setuplar - list active setup pool"""
        analyses = self.runtime.latest_analyses(max_age_seconds=86400)  # 24h
        if not analyses:
            return "ATLAS | SETUP HAVUZU\n\nHenüz tarama yapılmamış veya havuz boş."

        lines = ["ATLAS | SETUP HAVUZU", f"Toplam: {len(analyses)} analiz (son 24 saat)", ""]
        for item in sorted(analyses, key=lambda x: x.get("analyzed_at_ms", 0), reverse=True)[:20]:
            symbol = item.get("symbol", "?")
            result = item.get("result") or {}
            signal = result.get("signal") or {}
            decision = result.get("decision") or {}
            direction = signal.get("signal", "WAIT")
            action = decision.get("action", "WAIT")
            analyzed_at = item.get("analyzed_at_ms", 0)
            if analyzed_at:
                dt = datetime.fromtimestamp(analyzed_at / 1000).strftime("%H:%M:%S")
            else:
                dt = "?"
            lines.append(f"  {symbol} | {direction} | {action} | {dt}")

        lines.extend(["", "Not: /eniyi5 ile en iyi 5'i görüntüleyin."])
        return "\n".join(lines)

    def handle_takip(self) -> str:
        """Handle /takip - track open signals"""
        outcomes = self.runtime.signal_outcomes(limit=200, status="PENDING")
        if not outcomes:
            return "ATLAS | AÇIK SİNYAL TAKİBİ\n\nAçık sinyal yok."

        lines = ["ATLAS | AÇIK SİNYAL TAKİBİ", f"Toplam: {len(outcomes)}", ""]
        for item in outcomes:
            symbol = str(item.get("symbol") or "?").replace(":USDT", "")
            direction = str(item.get("direction") or "?").upper()
            signal_id = item.get("signal_id", "?")
            entry = _format_price(item.get("entry"))
            stop = _format_price(item.get("stop_loss"))
            tp1 = _format_price(item.get("tp1"))
            lines.append(f"{symbol} {direction} | {signal_id}")
            lines.append(f"  Giriş: {entry} | SL: {stop} | TP1: {tp1}")
            lines.append("")

        return "\n".join(lines)

    def handle_liquidity(self, symbol: str) -> str:
        """Handle /likidite BTC"""
        from atlas_tui import _is_symbol_input

        if not _is_symbol_input(symbol):
            return f"Geçersiz sembol: {symbol}\nKULLANIM: /likidite BTC"

        outcome = self.runtime.analyze_symbol(symbol, force_refresh=True, track_signal=False)
        if not outcome.get("ok"):
            return f"{symbol} likidite analizi yapılamadı: {outcome.get('error')}"

        # Reuse TUI formatting
        adapter = SimpleNamespace(
            runtime=self.runtime,
            _show=lambda _message: None,
            call_from_thread=lambda callback, *args, **kwargs: callback(*args, **kwargs),
        )
        from atlas_tui import AtlasTUIApp
        return AtlasTUIApp._format_liquidity(adapter, outcome)

    def handle_performance(self) -> str:
        """Handle /performans"""
        adapter = SimpleNamespace(
            runtime=self.runtime,
            _show=lambda _message: None,
            call_from_thread=lambda callback, *args, **kwargs: callback(*args, **kwargs),
        )
        from atlas_tui import AtlasTUIApp
        return AtlasTUIApp._format_performance(adapter, "performans")

    def handle_statistics(self) -> str:
        """Handle /istatistik"""
        signal = self.runtime.signal_performance()
        manual = self.runtime.manual_performance()
        learning = self.runtime.learning_panel()

        lines = [
            "ATLAS | İSTATİSTİKLER",
            "",
            "OTOMATİK SİNYAL SONUÇLARI (teorik)",
            f"Kapanan: {signal.get('closed', 0)} | WIN: {signal.get('wins', 0)} | LOSS: {signal.get('losses', 0)}",
            f"Winrate: %{signal.get('winrate', 0)} | Expectancy: {signal.get('expectancy', 0)} R | PF: {signal.get('profit_factor', 0)}",
            "",
            "MANUEL İŞLEMLER (gerçek kullanıcı kayıtları)",
            f"Kapanan: {manual.get('total', 0)} | WIN: {manual.get('wins', 0)} | LOSS: {manual.get('losses', 0)} | Açık: {manual.get('open', 0)}",
            f"Winrate: %{manual.get('winrate', 0)} | Expectancy: {manual.get('expectancy', 0)} R | PF: {manual.get('profit_factor', 0)}",
            "",
            "ÖĞRENME",
            f"Kaynak: {learning.get('source') or 'henüz yok'} | Kayıt: {learning.get('records_fed', 0)}",
            f"Manuel kapanan: {learning.get('closed_manual_trades', 0)} | Eşleşen setup: {learning.get('matched_setups', 0)}",
            f"Güvenilirlik: {learning.get('reliability', 0)} | Düzeltme: {learning.get('learning_adjustment', 0):+g} puan",
            "",
            "Not: Sıralama puanı kazanma olasılığı değildir.",
        ]
        return "\n".join(lines)

    def handle_learning(self) -> str:
        """Handle /ogrenme"""
        learning = self.runtime.learning_panel()
        lines = [
            "ATLAS | ÖĞRENME DURUMU",
            "",
            f"Kaynak: {learning.get('source') or 'henüz yok'}",
            f"Kayıt sayısı: {learning.get('records_fed', 0)}",
            f"Manuel kapanan işlem: {learning.get('closed_manual_trades', 0)}",
            f"Eşleşen setup: {learning.get('matched_setups', 0)}",
            f"Tarihsel edge: {learning.get('historical_edge', 0)}",
            f"Güvenilirlik: {learning.get('reliability', 0)}",
            f"Öğrenme düzeltmesi: {learning.get('learning_adjustment', 0):+g} puan",
            f"OOS gerekli: {'Evet' if learning.get('feed_meta', {}).get('oos_required') else 'Hayır'}",
            "",
            "Not: Öğrenme motoru manuel işlemlerden çıkarım yapar; kesin kârlılık kanıtı değildir.",
        ]
        return "\n".join(lines)

    def handle_status(self) -> str:
        """Handle /durum - bot and service status"""
        import psutil
        import sys

        # Telegram bot info
        bot_info = self._bot_info_cache or {}
        bot_name = bot_info.get("first_name", "Atlas")
        bot_username = bot_info.get("username", "?")

        # Runtime status
        snap = self.runtime.snapshot()
        scanner = snap.get("scanner") or {}
        mode = scanner.get("mode", "UNKNOWN")
        status = scanner.get("status", "UNKNOWN")
        cycle = scanner.get("cycle", 0)
        processed = scanner.get("processed", 0)
        success = scanner.get("success", 0)
        failed = scanner.get("failed", 0)
        skipped = scanner.get("skipped", 0)

        # Telegram status
        tg_status = self.runtime.telegram_status()
        polling = "AÇIK" if tg_status.get("polling_enabled") else "KAPALI"
        webhook = "AÇIK" if tg_status.get("webhook_enabled") else "KAPALI"
        service_running = "ÇALIŞIYOR" if tg_status.get("service_running") else "DURDU"

        # System info
        process = psutil.Process()
        mem_mb = process.memory_info().rss / 1024 / 1024
        cpu_pct = process.cpu_percent(interval=0.1)
        threads = process.num_threads()

        # Uptime
        started_at = scanner.get("started_at", 0)
        uptime_s = int(time.time() * 1000 - started_at) / 1000 if started_at else 0
        uptime_str = self._format_uptime(uptime_s)

        lines = [
            "ATLAS | SERVİS DURUMU",
            "",
            f"Bot: {bot_name} (@{bot_username})",
            f"Chat ID: {self.chat_id}",
            f"Polling: {polling} | Webhook: {webhook} | Servis: {service_running}",
            "",
            f"Tarama modu: {mode}",
            f"Durum: {status} | Döngü: {cycle}",
            f"İşlenen: {processed} | Başarılı: {success} | Hatalı: {failed} | Atlanan: {skipped}",
            f"Çalışma süresi: {uptime_str}",
            "",
            f"Python: {sys.version.split()[0]}",
            f"Bellek: {mem_mb:.1f} MB | CPU: {cpu_pct:.1f}% | Thread: {threads}",
        ]
        return "\n".join(lines)

    def handle_system(self) -> str:
        """Handle /sistem - system resources"""
        import psutil
        import os

        # System-wide stats
        cpu_count = psutil.cpu_count()
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)

        # Process stats
        process = psutil.Process()
        p_mem = process.memory_info().rss / 1024 / 1024
        p_cpu = process.cpu_percent(interval=0.1)
        p_threads = process.num_threads()
        open_files = len(process.open_files())
        connections = len(process.connections())

        lines = [
            "ATLAS | SİSTEM KAYNAKLARI",
            "",
            f"CPU: {cpu_count} çekirdek | Kullanım: {cpu_percent:.1f}% | Load: {load_avg[0]:.2f} {load_avg[1]:.2f} {load_avg[2]:.2f}",
            f"RAM: {mem.total / 1024**3:.1f} GB | Kullanım: {mem.percent:.1f}% | Boş: {mem.available / 1024**3:.1f} GB",
            f"Disk: {disk.total / 1024**3:.1f} GB | Kullanım: {disk.percent:.1f}% | Boş: {disk.free / 1024**3:.1f} GB",
            "",
            f"Süreç: PID={process.pid} | Bellek: {p_mem:.1f} MB | CPU: {p_cpu:.1f}% | Thread: {p_threads}",
            f"Açık dosya: {open_files} | Bağlantı: {connections}",
        ]
        return "\n".join(lines)

    def _execute_scan(self, scan_request, cached_best_request: bool) -> str:
        """Execute a scan request and return formatted results."""
        from atlas_tui import (
            _parse_scan_command,
            _best_symbols,
            AtlasTUIApp,
        )
        from utils.signal_card import build_selected_strategy_card, build_signal_card

        scan_limit, result_limit = scan_request

        # Do NOT clear scanner on each scan. The scanner accumulates results
        # across scans; the persistent OpportunityPool handles capacity/eviction.
        # Clearing here would wipe the pool that /eniyi5 and background scans rely on.

        if cached_best_request:
            # Use existing pool
            cached_items = self.runtime.latest_analyses()
            symbols = [item.get("symbol") for item in cached_items]
        else:
            symbols = _best_symbols(limit=scan_limit)

        if not symbols:
            return "Uygun piyasa bulunamadı. Veri sağlayıcısını kontrol et."

        candidates = []
        errors = []
        blocker_counts = {}
        diagnostics = {
            "long": 0, "short": 0, "execute": 0,
            "entry_too_far": 0, "entry_zone_crossed": 0,
            "no_entry": 0, "wait_or_skip": 0,
        }

        for index, symbol in enumerate(symbols, start=1):
            if cached_best_request:
                cached = next((item for item in cached_items if item.get("symbol") == symbol), None)
                raw = (cached or {}).get("result") or {}
                scanned = {"ok": bool(raw)}
            else:
                scanned = self.runtime.analyze_symbol(
                    symbol, force_refresh=True, track_signal=False
                )
                raw = scanned.get("result") or {}

            if not scanned.get("ok"):
                error_text = str(scanned.get("error") or "analiz başarısız").splitlines()[0][:180]
                errors.append(f"{symbol}: {error_text}")
                continue

            card = (
                build_selected_strategy_card(raw)
                if isinstance(raw.get("strategy_lab"), dict)
                else build_signal_card(raw)
            )

            direction = str(card.get("direction") or "").upper()
            if direction == "LONG":
                diagnostics["long"] += 1
            elif direction == "SHORT":
                diagnostics["short"] += 1

            if card.get("entry_distance_label") == "FAR" or (card.get("entry_distance_atr") is not None and card.get("entry_distance_atr") > 3):
                diagnostics["entry_too_far"] += 1
            if not card.get("entry"):
                diagnostics["no_entry"] += 1

            pending_limit = (
                card.get("decision_action") in {"EXECUTE", "EXECUTE_WITH_CAUTION"}
                and card.get("entry_type") == "LIMIT"
                and card.get("direction") in {"LONG", "SHORT"}
                and card.get("entry") is not None
                and card.get("stop_loss") is not None
                and card.get("tp_levels")
            )
            executable_market = (
                card.get("decision_action") in {"EXECUTE", "EXECUTE_WITH_CAUTION"}
                and card.get("entry_type") == "MARKET"
                and card.get("direction") in {"LONG", "SHORT"}
            )

            if not (executable_market or pending_limit):
                diagnostics["wait_or_skip"] += 1
                reasons = card.get("critical_blocks") or [card.get("reason")]
                for reason in reasons:
                    label = str(reason or "").strip()
                    if label:
                        blocker_counts[label] = blocker_counts.get(label, 0) + 1
                continue

            if executable_market:
                diagnostics["execute"] += 1

            rr = card.get("net_rr")
            if rr is None:
                rr = card.get("rr")
            try:
                rr_value = float(rr)
                if rr_value <= 0:
                    continue
                quality = float(card.get("setup_quality") or 0)
                confidence = float(card.get("confidence") or 0)
                score = quality * 0.55 + confidence * 0.25 + min(rr_value, 5.0) * 4
            except (TypeError, ValueError, OverflowError):
                continue

            if not card.get("strategy") and not card.get("strategy_id"):
                analysis = raw.get("analysis") or {}
                card["strategy"] = analysis.get("strategy") or "SMC"

            candidates.append((score, card, raw))

        if not candidates:
            if cached_best_request:
                return "ATLAS | EN İYİ 5 SETUP\nArka plan tarama havuzunda henüz güncel ve geçerli setup yok. İlk tarama döngüsünün tamamlanmasını bekle."
            message = (
                "ŞU AN GEÇERLİ İŞLEM YOK\n\n"
                "Taranan piyasalarda Atlas'ın işlem koşullarını geçen kurulum bulunmadı. "
                "Zorla LONG/SHORT üretmek yerine İŞLEME GİRME."
            )
            message += (
                "\n\nTARAMA TEŞHİSİ"
                f"\nLONG yön adayı: {diagnostics['long']}"
                f"\nSHORT yön adayı: {diagnostics['short']}"
                f"\nUzak LIMIT nedeniyle elenen: {diagnostics['entry_too_far']}"
                f"\nPOI geçilmiş: {diagnostics['entry_zone_crossed']}"
                f"\nGiriş seviyesi üretilemeyen: {diagnostics['no_entry']}"
                f"\nKarar filtresinde kalan: {diagnostics['wait_or_skip']}"
            )
            if blocker_counts:
                top_blockers = sorted(
                    blocker_counts.items(), key=lambda item: (-item[1], item[0])
                )[:5]
                message += "\n\nEN SIK ENGELLER"
                for reason, count in top_blockers:
                    message += f"\n{count}x {reason}"
            if errors:
                message += "\n\nAnaliz edilemeyenler: " + "; ".join(errors[:3])
            return message

        candidates.sort(key=lambda item: item[0], reverse=True)
        shown = candidates[:max(1, min(int(result_limit), 20))]

        for _score, _selected_card, selected_raw in shown:
            self.runtime.track_requested_result(selected_raw)

        lines = [f"ATLAS | EN İYİ {len(shown)} SETUP", f"Taranan piyasa: {len(symbols)}"]
        for rank, (score, card, _raw) in enumerate(shown, start=1):
            lines.extend(["", f"#{rank}", _format_telegram_card(card)])
        lines.append(
            f"\nTarama: {len(symbols)} piyasa | Geçerli kurulum: {len(candidates)}"
            f" | Gösterilen: {len(shown)}"
            f"\nSıralama puanı kazanma olasılığı değildir."
        )
        if errors:
            lines.append("Analiz hatası: " + "; ".join(errors[:3]))
        return "\n".join(lines)

    def _format_uptime(self, seconds: float) -> str:
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