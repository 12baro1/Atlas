"""Single-screen, command-driven terminal UI. No chatbot and no Telegram."""

from __future__ import annotations

import re
import threading

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Static

from data_engine import exchange
from universe_engine import select_symbols
from utils.signal_card import build_signal_card, format_card_text


_SYMBOL_INPUT_RE = re.compile(r"[A-Z0-9]{2,24}(?:/USDT(?::USDT)?)?\Z")
_BEST_TRADE_COMMANDS = {"işlem ver", "islem ver", "en iyi işlem", "en iyi islem", "best", "best trade"}


def _is_symbol_input(value: str) -> bool:
    """Accept a plain coin ticker or an explicit USDT perpetual symbol."""
    return bool(_SYMBOL_INPUT_RE.fullmatch(str(value or "").strip().upper()))


def _is_supported_input(value: str) -> bool:
    """Recognize supported commands before treating input as a coin ticker."""
    normalized = str(value or "").strip().lower()
    return normalized in _BEST_TRADE_COMMANDS or _is_symbol_input(value)


def _best_symbols(limit=5):
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
        try:
            quote_volume = float(quote_volume or 0)
        except (TypeError, ValueError):
            quote_volume = 0
        if quote_volume > 0:
            ranked.append((quote_volume, symbol))
    ranked.sort(reverse=True)
    return [symbol for _, symbol in ranked[:limit]]


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
                "Bir coin yaz: BRC, BTC, ETH\n"
                "'işlem ver' yaz: hacmi yüksek coinlerde en iyi geçerli kurulumu ara\n"
                "'yardım' yaz: komutları göster",
                id="help",
            )
            yield Static(
                "Hazır. Analiz başlatmak için aşağıya coin sembolünü veya 'işlem ver' yaz.",
                id="output",
            )
            yield Input(placeholder="Coin veya komut yazıp Enter'a bas...", id="command")
        yield Footer()

    def on_mount(self) -> None:
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

    def _show(self, message: str) -> None:
        self.query_one("#output", Static).update(message)

    def _start_command(self, command: str) -> None:
        if self._busy:
            self._show("Önce devam eden analiz bitsin.")
            return
        normalized = command.strip().lower()
        if normalized in {"yardım", "yardim", "help", "?"}:
            self._show(
                "KOMUTLAR\n"
                "• BRC / BTC / ETH — seçilen coin'i analiz et\n"
                "• işlem ver / en iyi işlem — hacmi yüksek ilk 5 uygun piyasayı tara\n"
                "• çıkış — Atlas'ı kapat\n\n"
                "Atlas emir göndermez. İşlem önerisi oluşmazsa BEKLE gösterir."
            )
            return
        if normalized in {"çıkış", "cikis", "exit", "quit"}:
            self.exit()
            return
        if not _is_supported_input(command):
            self._show(
                "KOMUT TANINMADI\n\n"
                "Bir coin sembolü (BTC, ETH, BRC), 'işlem ver' veya 'yardım' yaz."
            )
            return
        self._busy = True
        self._show(f"{command.upper()}\nAnaliz ediliyor…\nVeri kaynağına bağlanılıyor.")
        threading.Thread(target=self._run_command, args=(command,), daemon=True).start()

    def _run_command(self, command: str) -> None:
        try:
            lowered = command.strip().lower()
            if lowered in _BEST_TRADE_COMMANDS:
                result_text = self._find_best_trade()
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

    def _find_best_trade(self) -> str:
        symbols = _best_symbols(limit=5)
        if not symbols:
            return "Uygun piyasa bulunamadı. Veri sağlayıcısını kontrol et."
        candidates = []
        errors = []
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
            card = build_signal_card(raw)
            if card.get("decision_action") != "EXECUTE" or card.get("direction") not in {"LONG", "SHORT"}:
                continue
            try:
                rr = float(card.get("rr") or 0)
                quality = float(card.get("setup_quality") or 0)
                confidence = float(card.get("confidence") or 0)
            except (TypeError, ValueError):
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
                "Zorla LONG/SHORT üretmek yerine BEKLE."
            )
            if errors:
                message += "\n\nAnaliz edilemeyenler: " + "; ".join(errors[:3])
            return message
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, card, elapsed = candidates[0]
        return (
            "EN İYİ BULUNAN KURULUM (seçilenler arasında)\n"
            + format_card_text(card)
            + f"\n\nTarama: {len(symbols)} piyasa | Geçerli kurulum: {len(candidates)}"
            + f"\nSıralama puanı: {candidates[0][0]:.1f} (olasılık değildir)"
            + f"\nSeçilen analiz süresi: {elapsed / 1000:.1f} sn"
        )

    def _finish(self, message: str) -> None:
        self._show(message)
        self._busy = False
