"""On-demand Telegram command interface for the headless Atlas service.

Only messages from the configured group are considered. The bot never pushes
signals or scan results on its own; it replies only to recognized commands.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 3900
MAX_COMMAND_AGE_SECONDS = 120


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
        return "Hesaplanmadı"
    if not math.isfinite(number):
        return "Hesaplanmadı"
    return f"{number:+.2f}R"


def _format_price(value):
    """Format prices without hiding small-coin precision."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    rendered = f"{number:,.8f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _outcome_strategy(item):
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    strategy = (
        payload.get("strategy")
        or payload.get("strategy_id")
        or payload.get("setup_type")
    )
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
        f"Durum: {state}",
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
        "TP1 alınması işlemi kapatmaz; kalan hedefler takip edilir.",
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
        f"{'🟢' if direction == 'LONG' else '🔴'} {symbol} — {direction_label}",
        divider,
        "İŞLEM PLANI",
        f"Strateji: {strategy}",
        f"Emir tipi: {entry_type}",
        f"Giriş: {_format_price(card.get('entry'))}",
        f"Stop Loss: {_format_price(card.get('stop_loss'))}",
    ]
    if targets:
        lines.extend(["", "HEDEFLER"])
        lines.extend(
            f"TP{index}: {_format_price(target)}"
            for index, target in enumerate(targets[:3], start=1)
        )
    lines.extend([
        "",
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
        lines.append("Fiyat belirlenen LIMIT seviyesine gelmeden giriş varsayılmaz.")
    else:
        lines.append("DURUM: MARKET planı hazır.")
        lines.append("Bu mesaj borsa emri veya gerçekleşmiş fill teyidi değildir.")
    lines.append("Atlas otomatik emir göndermez.")
    lines.append(divider)
    return "\n".join(lines)

def is_recognized_command(command: str) -> bool:
    """Use the same command grammar as the terminal UI."""
    from atlas_tui import (
        _is_report_command,
        _is_symbol_input,
        _parse_liquidity_command,
        _parse_scan_command,
    )

    raw = str(command or "").strip()
    normalized = normalize_command(raw).lower()
    if normalized in {"yardım", "yardim", "help", "?", "mevcut"}:
        return True
    return (
        _is_report_command(normalized)
        or _parse_liquidity_command(normalized) is not False
        or _parse_scan_command(normalized) is not None
        or normalized == "eniyi5"
        # A bare ticker in group conversation is ordinary chat. Analyze only
        # explicit Telegram slash commands such as /btc or /btc@Oakmontincbot.
        or (raw.startswith("/") and _is_symbol_input(normalized))
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
        # Telegram can replay queued updates after a service restart. Ignore
        # old commands so an outage cannot trigger unattended analyses.
        try:
            message_ts = int(message.get("date") or 0)
        except (TypeError, ValueError, OverflowError):
            message_ts = 0
        now_ts = int(datetime.now().timestamp())
        if not message_ts or now_ts - message_ts > MAX_COMMAND_AGE_SECONDS or message_ts - now_ts > 30:
            self.logger.info("Ignoring stale Telegram update")
            return
        raw_command = str(message.get("text") or "").strip()
        command = normalize_command(raw_command)
        if not command or not is_recognized_command(raw_command):
            return
        self.logger.info("Telegram command received: %s", command[:80])
        try:
            result = self.execute_command(raw_command)
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
                "/btc /eth /sol — 7 strateji analizi\n"
                "/eniyi5 — arka plan havuzundan en iyi 5 setup\n"
                "en iyi 5 işlem — 100 piyasayı yeniden tara\n"
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
            scan_limit, result_limit = scan_request
            cached_items = self.runtime.latest_analyses(max_age_seconds=1800) if cached_best_request else []
            symbols = [item.get("symbol") for item in cached_items] if cached_best_request else _best_symbols(limit=scan_limit)
            candidates = []
            for symbol in symbols:
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
                    continue
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
                    quality = float(card.get("setup_quality") or 0)
                    confidence = float(card.get("confidence") or 0)
                    score = quality * 0.55 + confidence * 0.25 + min(rr_value, 5.0) * 4
                except (TypeError, ValueError, OverflowError):
                    continue
                if not card.get("strategy") and not card.get("strategy_id"):
                    analysis = raw.get("analysis") or {}
                    card["strategy"] = analysis.get("strategy") or "SMC"
                candidates.append((score, card, raw))
            candidates.sort(key=lambda item: item[0], reverse=True)
            if not candidates:
                if cached_best_request:
                    return "ATLAS | EN İYİ 5 SETUP\nArka plan tarama havuzunda henüz güncel ve geçerli setup yok. İlk tarama döngüsünün tamamlanmasını bekle."
                return f"ATLAS | TARAMA\nTaranan piyasa: {len(symbols)}\\nGeçerli MARKET/LIMIT setup bulunamadı."
            shown = candidates[:max(1, min(int(result_limit), 20))]
            # Bulk analysis inspects every market, but only displayed setups
            # are registered as user-requested daily signals.
            for _score, _selected_card, selected_raw in shown:
                self.runtime.track_requested_result(selected_raw)
            lines = [f"ATLAS | EN İYİ {len(shown)} SETUP", f"Taranan piyasa: {len(symbols)}"]
            for rank, (_score, card, _raw) in enumerate(shown, start=1):
                lines.extend(["", f"#{rank}", _format_telegram_card(card)])
            return "\n".join(lines)

        outcome = self.runtime.analyze_symbol(
            normalized, force_refresh=True, track_signal=True
        )
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
