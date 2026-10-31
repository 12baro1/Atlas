"""Single-screen, command-driven terminal UI. No chatbot and no Telegram."""

from __future__ import annotations

import math
import os
import re
import threading

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from data_engine import exchange
from universe_engine import select_symbols
from utils.signal_card import build_signal_card, format_card_text


_SYMBOL_INPUT_RE = re.compile(r"[A-Z0-9]{2,24}(?:/USDT(?::USDT)?)?\Z")
_BEST_TRADE_COMMANDS = {"işlem ver", "islem ver", "en iyi işlem", "en iyi islem", "best", "best trade"}
DEFAULT_SCAN_LIMIT = 30
DEFAULT_RANK_SCAN_LIMIT = 100
MAX_SCAN_LIMIT = 500


def _configured_scan_limit(default=DEFAULT_SCAN_LIMIT):
    raw = os.getenv("ATLAS_SCAN_LIMIT", str(default)).strip().lower()
    if raw in {"all", "tümü", "tumu", "0"}:
        return None
    return _normalize_scan_limit(raw, default=default, maximum=MAX_SCAN_LIMIT)


def _parse_scan_command(value: str):
    """Return (scan_limit, result_limit) for supported market scan commands."""
    normalized = " ".join(str(value or "").strip().lower().split())
    if normalized in _BEST_TRADE_COMMANDS:
        return _configured_scan_limit(), 1
    if normalized in {"tüm piyasa", "tum piyasa", "tüm piyasayı tara", "tum piyasayi tara",
                      "tüm piyasayı analiz et", "tum piyasayi analiz et", "full scan", "scan all"}:
        return None, 5
    match = re.fullmatch(r"(?:en iyi )?(\d+)\s+(?:tane\s+)?(?:işlem|islem)(?:i|leri)?(?:\s+ver)?", normalized)
    if match:
        count = _normalize_scan_limit(match.group(1), default=1, maximum=20)
        return _configured_scan_limit(default=DEFAULT_RANK_SCAN_LIMIT), count
    match = re.fullmatch(r"(\d+)\s+(?:tane\s+)?(?:(?:coin|piyasa|sembol)\s+)?(?:analiz et|tara)", normalized)
    if match:
        count = _normalize_scan_limit(match.group(1), default=DEFAULT_SCAN_LIMIT, maximum=MAX_SCAN_LIMIT)
        return count, 5
    match = re.fullmatch(r"(?:ilk )?(\d+)\s+(?:piyasa|coin)(?:yı|yi)?\s+tara", normalized)
    if match:
        count = _normalize_scan_limit(match.group(1), default=DEFAULT_SCAN_LIMIT, maximum=MAX_SCAN_LIMIT)
        return count, 5
    return None


def _normalize_scan_limit(value, default=DEFAULT_SCAN_LIMIT, maximum=MAX_SCAN_LIMIT):
    try:
        limit = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if limit <= 0:
        return default
    return min(limit, maximum)


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _is_symbol_input(value: str) -> bool:
    """Accept a plain coin ticker or an explicit USDT perpetual symbol."""
    return bool(_SYMBOL_INPUT_RE.fullmatch(str(value or "").strip().upper()))


def _is_report_command(value: str) -> bool:
    return str(value or "").strip().lower() in {"performans", "istatistik", "öğrenme", "ogrenme", "öğrenme durumu", "ogrenme durumu"}


def _parse_liquidity_command(value: str):
    normalized = " ".join(str(value or "").strip().upper().split())
    if normalized in {"LİKİDİTE", "LIKIDITE"}:
        return None
    for prefix in ("LİKİDİTE ", "LIKIDITE "):
        if normalized.startswith(prefix):
            symbol = normalized[len(prefix):].strip()
            return symbol if _is_symbol_input(symbol) else False
    return False


def _is_supported_input(value: str) -> bool:
    """Recognize supported commands before treating input as a coin ticker."""
    return (
        _parse_scan_command(value) is not None
        or _is_report_command(value)
        or _parse_liquidity_command(value) is not False
        or _is_symbol_input(value)
    )


def _best_symbols(limit=DEFAULT_SCAN_LIMIT):
    if limit is not None:
        limit = _normalize_scan_limit(limit)
    markets = exchange.load_markets()
    symbols, _ = select_symbols(
        markets=markets,
        suffix="/USDT:USDT",
        require_active=True,
        require_swap=False,
        max_symbols=0,
    )
    tickers = exchange.fetch_tickers(symbols)
    ranked = []
    for symbol in symbols:
        ticker = (tickers or {}).get(symbol) or {}
        quote_volume = ticker.get("quoteVolume")
        quote_volume = _finite_number(quote_volume or 0)
        if quote_volume is not None and quote_volume > 0:
            ranked.append((quote_volume, symbol))
    ranked.sort(reverse=True)
    selected = ranked if limit is None else ranked[:limit]
    return [symbol for _, symbol in selected]


class AtlasTUIApp(App):
    """One screen, one command input, output shown locally only."""

    TITLE = "ATLAS"
    SUB_TITLE = "SMC terminal | local-only | no AI | no Telegram"

    CSS = """
    Screen {
        background: $background;
    }
    #main {
        height: 1fr;
        padding: 1 2;
    }
    #brand {
        height: 3;
        content-align: left middle;
        color: $accent;
        text-style: bold;
    }
    #help {
        height: 4;
        color: $text-muted;
    }
    #output {
        height: 1fr;
        border: round $accent;
        padding: 1 2;
        overflow-y: auto;
    }
    #command {
        dock: bottom;
        margin: 1 0;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Çıkış"),
        ("escape", "clear_command", "Komutu temizle"),
        ("pageup", "scroll_output_up", "Yukarı"),
        ("pagedown", "scroll_output_down", "Aşağı"),
        ("ctrl+u", "scroll_output_up", "Yukarı"),
        ("ctrl+d", "scroll_output_down", "Aşağı"),
    ]

    def __init__(self, runtime, initial_symbol=None):
        super().__init__()
        self.runtime = runtime
        self.initial_symbol = initial_symbol
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            yield Static("ATLAS  /  SMC ANALİZ TERMİNALİ", id="brand")
            yield Static(
                "Bir coin yaz: BTC / ETH — tek coin analizi\n"
                "'50 analiz et' — 50 piyasayı tara, en iyi 5 kurulumu göster\n"
                "'en iyi 5 işlem' — 100 piyasadan en iyi 5 kurulumu seç\n"
                "'tüm piyasayı tara' — uygun tüm USDT perpetual piyasaları tara\n"
                "'yardım' — komutların tamamı",
                id="help",
            )
            yield RichLog(
                id="output",
                wrap=True,
                markup=False,
                auto_scroll=True,
                max_lines=5000,
            )
            yield Input(placeholder="Coin veya komut yazıp Enter'a bas...", id="command")
        yield Footer()

    def on_mount(self) -> None:
        self._show("Hazır. Analiz başlatmak için coin sembolünü veya 'işlem ver' yaz.")
        self.query_one("#command", Input).focus()
        if self.initial_symbol:
            self._start_command(self.initial_symbol)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if command:
            self._start_command(command)

    def action_clear_command(self) -> None:
        self.query_one("#command", Input).value = ""

    def action_scroll_output_up(self) -> None:
        self.query_one("#output", RichLog).scroll_relative(y=-10, animate=False)

    def action_scroll_output_down(self) -> None:
        self.query_one("#output", RichLog).scroll_relative(y=10, animate=False)

    def _show(self, message: str) -> None:
        output = self.query_one("#output", RichLog)
        output.clear()
        output.write(message, scroll_end=True)

    def _start_command(self, command: str) -> None:
        if self._busy:
            self._show("Önce devam eden analiz bitsin.")
            return
        normalized = command.strip().lower()
        if normalized in {"yardım", "yardim", "help", "?"}:
            self._show(
                "KOMUTLAR\n"
                "TEK COIN\n"
                "• BTC / ETH / BRC — seçilen coini analiz et\n\n"
                "PIYASA TARAMA\n"
                "• işlem ver — 30 piyasayı tara, en iyi 1 kurulumu göster\n"
                "• 50 analiz et — 50 piyasayı tara, en iyi 5 kurulumu göster\n"
                "• 100 tara — 100 piyasayı tara, en iyi 5 kurulumu göster\n"
                "• en iyi 5 işlem — 100 piyasadan en iyi 5 kurulumu göster\n"
                "• tüm piyasayı tara — tüm uygun USDT perpetual piyasalarını tara\n"
                "• en iyi 10 işlem — 100 piyasadan en iyi 10 kurulumu göster\n\n"
                "Sayısal tarama en fazla 500 piyasa; tüm piyasa taraması uzun sürebilir.\n"
                "PERFORMANS / ANALİZ\n"
                "• performans — sinyal ve manuel işlem sonuçlarını ayrı göster\n"
                "• öğrenme — geçmiş işlem öğrenme verisini göster\n"
                "• likidite BTC — BSL/SSL, EQH/EQL ve sweep haritası\n\n"
                "Atlas emir göndermez. Sıralama puanı kazanma olasılığı değildir.\n"
                "Çıktıda gezinme: PageUp / PageDown veya Ctrl+U / Ctrl+D.\n"
                "• çıkış — Atlas'ı kapat"
            )
            return
        if normalized in {"çıkış", "cikis", "exit", "quit"}:
            self.exit()
            return
        if not _is_supported_input(command):
            self._show(
                "KOMUT TANINMADI\n\n"
                "Örnek: BTC | 50 analiz et | en iyi 5 işlem | tüm piyasayı tara | yardım"
            )
            return
        self._busy = True
        self._show(f"{command.upper()}\nAnaliz ediliyor…\nVeri kaynağına bağlanılıyor.")
        threading.Thread(target=self._run_command, args=(command,), daemon=True).start()

    def _run_command(self, command: str) -> None:
        try:
            lowered = command.strip().lower()
            scan_request = _parse_scan_command(lowered)
            liquidity_symbol = _parse_liquidity_command(command)
            if _is_report_command(command):
                result_text = self._format_performance(command)
            elif liquidity_symbol is not False:
                symbol = liquidity_symbol or self.runtime.current_symbol()
                if not symbol:
                    result_text = "KULLANIM: likidite BTC"
                else:
                    outcome = self.runtime.analyze_symbol(symbol, force_refresh=True)
                    result_text = self._format_liquidity(outcome) if outcome.get("ok") else f"{symbol} likidite analizi yapılamadı: {outcome.get('error')}"
            elif scan_request is not None:
                result_text = self._find_best_trade(*scan_request)
            else:
                outcome = self.runtime.analyze_symbol(command, force_refresh=True)
                if not outcome.get("ok"):
                    result_text = (
                        f"{command.upper()} ANALİZ EDİLEMEDİ\n\n"
                        f"Neden: {outcome.get('error', 'bilinmeyen hata')}\n"
                        "Sembolün USDT perpetual piyasasında bulunduğunu kontrol et."
                    )
                else:
                    card = build_signal_card(outcome["result"])
                    result_text = format_card_text(card)
                    result_text += f"\n\nAnaliz süresi: {outcome.get('elapsed_ms', 0) / 1000:.1f} sn"
            self.call_from_thread(self._finish, result_text)
        except Exception as exc:
            self.call_from_thread(self._finish, f"ANALİZ HATASI\n\n{type(exc).__name__}: {exc}")


    def _format_performance(self, command: str) -> str:
        signal = self.runtime.signal_performance()
        manual = self.runtime.manual_performance()
        learning = self.runtime.learning_panel()
        title = "ÖĞRENME DURUMU" if "öğren" in command.lower() or "ogren" in command.lower() else "PERFORMANS"
        lines = [
            title,
            "",
            "OTOMATİK SİNYAL SONUÇLARI (teorik)",
            f"Kapanan: {signal.get('closed', 0)} | WIN: {signal.get('wins', 0)} | LOSS: {signal.get('losses', 0)} | PARTIAL: {signal.get('partials', 0)}",
            f"Winrate: %{signal.get('winrate', 0)} | Expectancy: {signal.get('expectancy', 0)} R | PF: {signal.get('profit_factor', 0)}",
            f"TP1/TP2/TP3: {signal.get('tp1', 0)}/{signal.get('tp2', 0)}/{signal.get('tp3', 0)} | SL: {signal.get('sl', 0)}",
            "",
            "MANUEL İŞLEMLER (gerçek kullanıcı kayıtları)",
            f"Kapanan: {manual.get('total', 0)} | WIN: {manual.get('wins', 0)} | LOSS: {manual.get('losses', 0)} | Açık: {manual.get('open', 0)}",
            f"Winrate: %{manual.get('winrate', 0)} | Expectancy: {manual.get('expectancy', 0)} R | PF: {manual.get('profit_factor', 0)}",
            "",
            "ÖĞRENME",
            f"Kaynak: {learning.get('source') or 'henüz yok'} | Öğrenmeye giren kayıt: {learning.get('records_fed', 0)}",
            f"Manuel kapanan: {learning.get('closed_manual_trades', 0)} | Eşleşen setup: {learning.get('matched_setups', 0)}",
            f"Güvenilirlik: {learning.get('reliability', 0)} | Öğrenme düzeltmesi: {learning.get('learning_adjustment', 0):+g} puan",
            "",
            "Not: Otomatik sinyal sonuçları ve manuel işlemler ayrı tutulur. Sıralama/kalite puanı kazanma olasılığı değildir.",
        ]
        if signal.get("closed", 0) < 20:
            lines.append("Otomatik sinyal örneklemi 20 kapanan işlemin altında; geçmiş performans kesin sonuç çıkarmaz.")
        return "\\n".join(lines)

    def _format_liquidity(self, outcome: dict) -> str:
        result = outcome.get("result") or {}
        analysis = result.get("analysis") or {}
        layers = analysis.get("liquidity_layers") or {}
        sweep = analysis.get("liquidity_sweep") or {}
        symbol = result.get("symbol") or outcome.get("symbol") or "UNKNOWN"
        lines = [f"LİKİDİTE HARİTASI | {symbol}", ""]
        for key, label in (("bsl", "BUY-SIDE LIQUIDITY / BSL"), ("ssl", "SELL-SIDE LIQUIDITY / SSL"), ("eqh", "EQUAL HIGHS / EQH"), ("eql", "EQUAL LOWS / EQL")):
            levels = layers.get(key) or []
            lines.append(f"{label}:")
            if not levels:
                lines.append("  Bulunamadı")
                continue
            for item in sorted(levels, key=lambda row: float(row.get("touches", 0)), reverse=True)[:5]:
                lines.append(
                    f"  {item.get('price')} | temas: {item.get('touches', 0)} | "
                    f"katman: {item.get('liquidity_kind', 'UNKNOWN')}"
                )
        post = sweep.get("post_structure") or {}
        sweep_direction = "BEARISH" if sweep.get("buy_side") else ("BULLISH" if sweep.get("sell_side") else "YOK")
        lines.extend([
            "",
            "SON LİKİDİTE SÜPÜRMESİ",
            f"Sweep: {'EVET' if sweep.get('is_sweep') else 'HAYIR'} | Yön: {sweep_direction} | Güç: {sweep.get('strength_score', 0)}",
            f"BSL süpürüldü: {'EVET' if sweep.get('buy_side') else 'HAYIR'} | SSL süpürüldü: {'EVET' if sweep.get('sell_side') else 'HAYIR'}",
            f"Kırılım: {'EVET' if sweep.get('is_breakout') else 'HAYIR'} | "
            f"BSL üstü: {sweep.get('breakout_high') or '-'} | SSL altı: {sweep.get('breakout_low') or '-'}",
            f"Sonraki yapı teyidi: {'VAR' if post.get('confirmed') else 'YOK'}",
            "",
            "Bu harita mevcut analiz mumlarına dayanır; tek başına işlem sinyali değildir.",
        ])
        return "\\n".join(lines)

    def _find_best_trade(self, scan_limit=DEFAULT_SCAN_LIMIT, result_limit=1) -> str:
        symbols = _best_symbols(limit=scan_limit)
        if not symbols:
            return "Uygun piyasa bulunamadı. Veri sağlayıcısını kontrol et."
        candidates = []
        errors = []
        diagnostics = {
            "long": 0, "short": 0, "execute": 0,
            "entry_too_far": 0, "entry_zone_crossed": 0,
            "no_entry": 0, "wait_or_skip": 0,
        }
        for index, symbol in enumerate(symbols, start=1):
            self.call_from_thread(
                self._show,
                f"EN İYİ İŞLEM ARANIYOR\n\nTarama {index}/{len(symbols)}: {symbol}\n"
                "Her sembol gerçek piyasa verisiyle ayrı analiz ediliyor…",
            )
            outcome = self.runtime.analyze_symbol(symbol, force_refresh=True)
            if not outcome.get("ok"):
                errors.append(f"{symbol}: {outcome.get('error', 'analiz başarısız')}")
                continue
            raw = outcome["result"]
            signal_data = raw.get("signal") or {}
            analysis_data = raw.get("analysis") or {}
            entry_data = analysis_data.get("entry") or {}
            direction = str(signal_data.get("signal") or "").upper()
            if direction == "LONG":
                diagnostics["long"] += 1
            elif direction == "SHORT":
                diagnostics["short"] += 1
            if entry_data.get("entry_too_far"):
                diagnostics["entry_too_far"] += 1
            if entry_data.get("entry_zone_crossed"):
                diagnostics["entry_zone_crossed"] += 1
            if not entry_data.get("entry"):
                diagnostics["no_entry"] += 1
            card = build_signal_card(raw)
            pending_limit = card.get("entry_type") == "LIMIT" and card.get("direction") in {"LONG", "SHORT"} and bool(card.get("entry")) and bool(card.get("stop_loss"))
            executable_market = card.get("decision_action") == "EXECUTE" and card.get("direction") in {"LONG", "SHORT"}
            if not (executable_market or pending_limit):
                diagnostics["wait_or_skip"] += 1
                continue
            if executable_market:
                diagnostics["execute"] += 1
            rr = _finite_number(
                card.get("net_rr")
                if card.get("net_rr") is not None
                else card.get("rr")
            )
            quality = _finite_number(card.get("setup_quality") or 0)
            confidence = _finite_number(card.get("confidence") or 0)
            if rr is None or quality is None or confidence is None:
                continue
            if not card.get("entry") or not card.get("stop_loss") or rr <= 0:
                continue
            # Ranking is a heuristic sort key, not a win probability.
            score = quality * 0.55 + confidence * 0.25 + min(rr, 5.0) * 4
            candidates.append((score, card, outcome.get("elapsed_ms", 0)))
        if not candidates:
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
            if errors:
                message += "\n\nAnaliz edilemeyenler: " + "; ".join(errors[:3])
            return message
        candidates.sort(key=lambda item: item[0], reverse=True)
        shown = candidates[:max(1, min(int(result_limit), 20))]
        heading = "EN İYİ KURULUMLAR" if len(shown) > 1 else "EN İYİ BULUNAN KURULUM"
        sections = [heading]
        for rank, (score, card, elapsed) in enumerate(shown, start=1):
            sections.append(
                "\n============ #" + str(rank) + " | SIRALAMA PUANI "
                + f"{score:.1f}" + " ============\n"
                + format_card_text(card)
                + f"\nAnaliz süresi: {elapsed / 1000:.1f} sn"
            )
        sections.append(
            f"\nTarama: {len(symbols)} piyasa | Geçerli kurulum: {len(candidates)}"
            + f" | Gösterilen: {len(shown)}"
            + "\nSıralama puanı kazanma olasılığı değildir."
        )
        if errors:
            sections.append("Analiz hatası: " + "; ".join(errors[:3]))
        return "\n".join(sections)

    def _finish(self, message: str) -> None:
        self._show(message)
        self._busy = False
