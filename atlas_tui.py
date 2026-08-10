"""Textual full-screen TUI for Atlas runtime."""

from __future__ import annotations

import threading
from collections import Counter, defaultdict
from datetime import datetime

from atlas_assistant import AtlasAssistant
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Log, Static


def _fmt_num(value, digits=4):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    text = f"{number:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _fmt_pct(value):
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "-"


def _fmt_time(ts_ms):
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


class OpenTradeModal(ModalScreen):
    CSS = """
    OpenTradeModal {
        align: center middle;
    }

    #open-trade-dialog {
        width: 74;
        max-width: 96%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }

    #open-trade-dialog Input {
        margin: 1 0;
    }

    #open-trade-actions {
        height: auto;
        margin-top: 1;
    }

    #open-trade-actions Button {
        width: 1fr;
        margin-right: 1;
    }
    """

    def __init__(self, signal):
        super().__init__()
        self.signal = signal or {}

    def compose(self) -> ComposeResult:
        atlas_entry = self.signal.get("entry")
        yield Container(
            Static("Manual Trade: GIRDIM", classes="title"),
            Static(f"Signal ID: {self.signal.get('signal_id', '-')}") ,
            Static(f"Symbol: {self.signal.get('symbol', '-')}  Direction: {self.signal.get('direction', '-')}") ,
            Static(f"Atlas Entry: {_fmt_num(atlas_entry)}"),
            Input(value=_fmt_num(atlas_entry), placeholder="Actual Entry Price", id="actual-entry"),
            Input(placeholder="Position Size", id="position-size"),
            Horizontal(
                Button("CONFIRM", id="confirm", variant="success"),
                Button("CANCEL", id="cancel", variant="default"),
                id="open-trade-actions",
            ),
            id="open-trade-dialog",
        )

    def on_mount(self):
        self.query_one("#actual-entry", Input).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        actual_entry = self._num(self.query_one("#actual-entry", Input).value)
        position_size = self._num(self.query_one("#position-size", Input).value)
        self.dismiss({"actual_entry": actual_entry, "position_size": position_size})

    @staticmethod
    def _num(value):
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None


class ExitTradeModal(ModalScreen):
    CSS = """
    ExitTradeModal {
        align: center middle;
    }

    #exit-trade-dialog {
        width: 70;
        max-width: 96%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }

    #exit-trade-actions {
        margin-top: 1;
    }

    #exit-trade-actions Button {
        width: 1fr;
        margin-right: 1;
    }
    """

    def __init__(self, signal, action_label):
        super().__init__()
        self.signal = signal or {}
        self.action_label = action_label

    def compose(self) -> ComposeResult:
        yield Container(
            Static(f"Manual Trade: {self.action_label}"),
            Static(f"Signal ID: {self.signal.get('signal_id', '-')}") ,
            Input(placeholder="Exit Price", id="exit-price"),
            Horizontal(
                Button("CONFIRM", id="confirm", variant="success"),
                Button("CANCEL", id="cancel", variant="default"),
                id="exit-trade-actions",
            ),
            id="exit-trade-dialog",
        )

    def on_mount(self):
        self.query_one("#exit-price", Input).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        exit_price = self._num(self.query_one("#exit-price", Input).value)
        self.dismiss({"exit_price": exit_price})

    @staticmethod
    def _num(value):
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None


class AtlasTUIApp(App):
    CSS = """
    Screen {
        background: $panel;
        color: $text;
    }

    #page-nav {
        height: 3;
        margin: 0 1;
    }

    #page-nav Button {
        width: 1fr;
        margin-right: 1;
    }

    .page {
        display: none;
        height: 1fr;
        margin: 0 1;
    }

    #dashboard-page {
        display: block;
    }

    .panel {
        border: round #3a5f8a;
        padding: 0 1;
        margin: 0 1 1 0;
        height: 1fr;
    }

    .table-panel {
        border: round #3a5f8a;
        height: 1fr;
        width: 1fr;
    }

    #dashboard-main-row {
        height: 12;
    }

    #dashboard-manual {
        height: 8;
    }

    #dashboard-manual-buttons {
        height: 3;
        margin-top: 1;
    }

    #dashboard-manual-buttons Button {
        width: 1fr;
        margin-right: 1;
    }

    #dashboard-learning {
        height: 4;
    }

    #dashboard-chat {
        height: 1fr;
    }

    #chat-log {
        border: round #4e6988;
        height: 1fr;
        margin-bottom: 1;
    }

    #chat-input-row {
        height: 3;
    }

    #chat-input {
        width: 1fr;
    }

    #chat-send {
        width: 12;
    }

    #dashboard-recent {
        height: 6;
    }

    #signals-layout,
    #journal-layout {
        height: 1fr;
    }

    #signals-details,
    #journal-filter,
    #learning-view,
    #telegram-view {
        border: round #3a5f8a;
        padding: 0 1;
        width: 1fr;
    }

    #signals-details,
    #learning-view,
    #telegram-view {
        overflow-y: auto;
    }

    #journal-filter {
        height: 3;
        margin: 0 0 1 0;
    }

    #logs-view {
        border: round #3a5f8a;
        height: 1fr;
    }

    #message-bar {
        height: 2;
        content-align: left middle;
        padding: 0 1;
        background: #1f2c3a;
        color: #e6edf5;
    }

    #shortcut-footer {
        height: 2;
        content-align: left middle;
        padding: 0 1;
        background: #223247;
        color: #dce7f4;
    }
    """

    BINDINGS = [
        Binding("1", "go_dashboard", "Dashboard"),
        Binding("2", "go_signals", "Signals"),
        Binding("3", "go_learning", "Learning"),
        Binding("4", "go_journal", "Journal"),
        Binding("5", "go_telegram", "Telegram"),
        Binding("6", "go_logs", "Logs"),
        Binding("l", "go_logs", "Logs"),
        Binding("g", "mark_entered", "Girdim"),
        Binding("n", "mark_not_traded", "Girmedim"),
        Binding("t", "mark_tp", "TP"),
        Binding("x", "mark_sl", "SL"),
        Binding("e", "mark_early", "Erken"),
        Binding("f", "cycle_journal_filter", "Filter"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("escape", "go_back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, runtime, initial_symbol=None):
        super().__init__()
        self.runtime = runtime
        self.assistant = AtlasAssistant(runtime)
        self.initial_symbol = initial_symbol
        self.current_page = "dashboard"
        self._message = "Atlas TUI ready"
        self._journal_filter = "ALL"
        self._journal_filter_order = ["ALL", "WIN", "LOSS", "EARLY_EXIT", "NOT_TRADED"]
        self._signal_rows = []
        self._journal_rows = []
        self._signal_map = {}
        self._manual_map = {}
        self._log_count = 0
        self._chat_lines = []
        self._pending_chat_action = None
        self._chat_busy = False


    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        yield Horizontal(
            Button("1 Dashboard", id="nav-dashboard"),
            Button("2 Signals", id="nav-signals"),
            Button("3 Learning", id="nav-learning"),
            Button("4 Journal", id="nav-journal"),
            Button("5 Telegram", id="nav-telegram"),
            Button("6 Logs", id="nav-logs"),
            id="page-nav",
        )

        with Vertical(id="dashboard-page", classes="page"):
            with Horizontal(id="dashboard-main-row"):
                yield Static(id="dashboard-scanner", classes="panel")
                yield Static(id="dashboard-current", classes="panel")
            with Vertical(id="dashboard-manual", classes="panel"):
                yield Static(id="dashboard-manual-info")
                yield Horizontal(
                    Button("GIRDIM (G)", id="btn-entered", variant="success"),
                    Button("GIRMEDIM (N)", id="btn-not-traded", variant="warning"),
                    Button("TP (T)", id="btn-tp", variant="primary"),
                    Button("SL (X)", id="btn-sl", variant="error"),
                    Button("ERKEN (E)", id="btn-early", variant="default"),
                    id="dashboard-manual-buttons",
                )
            yield Static(id="dashboard-learning", classes="panel")
            yield Static(id="dashboard-recent", classes="panel")
            with Vertical(id="dashboard-chat", classes="panel"):
                yield Static("ATLAS CHAT")
                yield Log(id="chat-log", auto_scroll=True)
                yield Horizontal(
                    Input(placeholder="Mesajini yaz...", id="chat-input"),
                    Button("SEND", id="chat-send", variant="primary"),
                    id="chat-input-row",
                )

        with Vertical(id="signals-page", classes="page"):
            with Horizontal(id="signals-layout"):
                yield DataTable(id="signals-table", classes="table-panel")
                yield Static(id="signals-details")

        with Vertical(id="learning-page", classes="page"):
            yield Static(id="learning-view")

        with Vertical(id="journal-page", classes="page"):
            yield Static(id="journal-filter")
            with Horizontal(id="journal-layout"):
                yield DataTable(id="journal-table", classes="table-panel")

        with Vertical(id="telegram-page", classes="page"):
            yield Static(id="telegram-view")

        with Vertical(id="logs-page", classes="page"):
            yield Log(id="logs-view", auto_scroll=True)

        yield Static(id="message-bar")
        yield Static(
            "[1]Dashboard [2]Signals [3]Learning [4]Journal [5]Telegram [6/L]Logs | "
            "G=Girdim N=Girmedim T=TP X=SL E=Erken R=Refresh Esc=Back Q=Quit",
            id="shortcut-footer",
        )
        yield Footer()

    def on_mount(self):
        self.title = "ATLAS"
        self._setup_tables()
        self._show_page("dashboard")
        self.set_interval(1.2, self._refresh_views)
        self._bootstrap_session()
        self._refresh_views()
        self.query_one("#chat-input", Input).focus()

    def _setup_tables(self):
        signals = self.query_one("#signals-table", DataTable)
        signals.cursor_type = "row"
        signals.add_columns("Signal ID", "Symbol", "Dir", "Grade", "Conf", "RR", "Decision", "Manual", "Result")

        journal = self.query_one("#journal-table", DataTable)
        journal.cursor_type = "row"
        journal.add_columns("Date", "Signal ID", "Symbol", "Dir", "Setup", "Result", "R", "Entry", "Exit")

    async def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id or ""
        if bid == "nav-dashboard":
            self._show_page("dashboard")
        elif bid == "nav-signals":
            self._show_page("signals")
        elif bid == "nav-learning":
            self._show_page("learning")
        elif bid == "nav-journal":
            self._show_page("journal")
        elif bid == "nav-telegram":
            self._show_page("telegram")
        elif bid == "nav-logs":
            self._show_page("logs")
        elif bid == "btn-entered":
            await self.action_mark_entered()
        elif bid == "btn-not-traded":
            self.action_mark_not_traded()
        elif bid == "btn-tp":
            await self.action_mark_tp()
        elif bid == "btn-sl":
            await self.action_mark_sl()
        elif bid == "btn-early":
            await self.action_mark_early()
        elif bid == "chat-send":
            await self.action_send_chat()

    async def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "chat-input":
            await self.action_send_chat()

    def action_go_dashboard(self):
        self._show_page("dashboard")

    def action_go_signals(self):
        self._show_page("signals")

    def action_go_learning(self):
        self._show_page("learning")

    def action_go_journal(self):
        self._show_page("journal")

    def action_go_telegram(self):
        self._show_page("telegram")

    def action_go_logs(self):
        self._show_page("logs")

    def action_go_back(self):
        if self.current_page != "dashboard":
            self._show_page("dashboard")

    def action_refresh_now(self):
        self.runtime.refresh_learning()
        self._refresh_views()
        self._set_message("Refreshed")

    async def action_send_chat(self):
        if self._chat_busy:
            return
        input_widget = self.query_one("#chat-input", Input)
        message = str(input_widget.value or "").strip()
        if not message:
            return
        input_widget.value = ""
        self._chat_append("Sen", message)
        await self._run_chat_message(message)

    def action_cycle_journal_filter(self):
        if self.current_page != "journal":
            return
        index = self._journal_filter_order.index(self._journal_filter)
        self._journal_filter = self._journal_filter_order[(index + 1) % len(self._journal_filter_order)]
        self._refresh_journal_page()

    async def action_mark_entered(self):
        signal = self._target_signal()
        if not signal or not signal.get("signal_id"):
            self._set_message("No signal selected")
            return
        dialog = OpenTradeModal(signal)
        result = await self.push_screen_wait(dialog)
        if not result:
            return
        manual, code = self.runtime.manual_service.open_trade(
            signal_id=signal.get("signal_id"),
            actual_entry=result.get("actual_entry"),
            position_size=result.get("position_size"),
        )
        if code == "opened":
            self._set_message(f"OPEN saved: {manual.get('signal_id')}")
        elif code == "already_open":
            self._set_message("Trade already exists for signal")
        else:
            self._set_message(f"Cannot open trade: {code}")
        self._refresh_views()

    def action_mark_not_traded(self):
        signal = self._target_signal()
        if not signal or not signal.get("signal_id"):
            self._set_message("No signal selected")
            return
        _manual, code = self.runtime.manual_service.mark_not_traded(signal_id=signal.get("signal_id"))
        if code == "not_traded":
            self._set_message(f"NOT_TRADED saved: {signal.get('signal_id')}")
        elif code == "already_open":
            self._set_message("Signal already has manual record")
        else:
            self._set_message(f"Cannot set NOT_TRADED: {code}")
        self._refresh_views()

    async def action_mark_tp(self):
        await self._close_trade_flow("TP", "TP")

    async def action_mark_sl(self):
        await self._close_trade_flow("SL", "SL")

    async def action_mark_early(self):
        await self._close_trade_flow("EARLY_EXIT", "ERKEN CIKTIM")

    async def _close_trade_flow(self, result, action_label):
        signal = self._target_signal(open_required=True)
        if not signal or not signal.get("signal_id"):
            self._set_message("No OPEN manual trade selected")
            return
        dialog = ExitTradeModal(signal, action_label)
        payload = await self.push_screen_wait(dialog)
        if payload is None:
            return
        manual, code = self.runtime.manual_service.close_trade(
            signal_id=signal.get("signal_id"),
            result=result,
            actual_exit=payload.get("exit_price"),
        )
        if code == "closed":
            self._set_message(f"{manual.get('result')} saved: {manual.get('signal_id')} ({_fmt_num(manual.get('pnl_rr'))}R)")
            self._chat_append("Atlas", f"{manual.get('result')} kaydedildi: {manual.get('signal_id')} ({_fmt_num(manual.get('pnl_rr'))}R)")
        else:
            self._set_message(f"Cannot close trade: {code}")
        self._refresh_views()

    def _bootstrap_session(self):
        summary = self.runtime.boot_summary()
        self._chat_append(
            "Atlas",
            (
                "Tekrar hos geldin. "
                f"{summary.get('open_manual', 0)} acik islem ve "
                f"{summary.get('closed_manual', 0)} gecmis manuel kapanis bulundu."
            ),
        )
        if self.initial_symbol:
            self._chat_append("Atlas", f"Baslangic sembolu alindi: {self.initial_symbol}. Analiz baslatiliyor...")
            self._start_background_chat(self.initial_symbol)

    def _start_background_chat(self, symbol_text):
        thread = threading.Thread(target=self._chat_background_worker, args=(symbol_text,), daemon=True)
        thread.start()

    def _chat_background_worker(self, symbol_text):
        try:
            response = self.assistant.handle_user_message(f"{symbol_text} analiz et")
        except Exception as exc:
            response = {"responses": [f"Analiz sirasinda hata: {exc}"], "action": None}
        self.call_from_thread(self._apply_chat_response, response)

    async def _run_chat_message(self, message):
        self._chat_busy = True
        self._set_message("Atlas dusunuyor...")
        worker = threading.Thread(target=self._chat_worker_thread, args=(message,), daemon=True)
        worker.start()

    def _chat_worker_thread(self, message):
        try:
            response = self.assistant.handle_user_message(message)
        except Exception as exc:
            response = {"responses": [f"Komut islenirken hata: {exc}"], "action": None}
        self.call_from_thread(self._apply_chat_response, response)

    def _apply_chat_response(self, response):
        self._chat_busy = False
        responses = list((response or {}).get("responses") or [])
        for line in responses:
            self._chat_append("Atlas", line)
        action = (response or {}).get("action")
        if action:
            self._pending_chat_action = action
            self.run_worker(self._run_pending_chat_action(), exclusive=False)
        self._refresh_views()
        self._set_message("Ready")

    async def _run_pending_chat_action(self):
        action = self._pending_chat_action
        self._pending_chat_action = None
        if not action:
            return
        if action.get("type") == "open_trade_prompt":
            await self.action_mark_entered()
        elif action.get("type") == "mark_not_traded":
            self.action_mark_not_traded()
        elif action.get("type") == "close_trade_prompt":
            await self._close_trade_flow(action.get("result"), action.get("label") or action.get("result"))

    def _chat_append(self, role, message):
        text = str(message or "").strip()
        if not text:
            return
        lines = text.splitlines() or [text]
        for line in lines:
            self._chat_lines.append(f"{role}: {line}")
        self._chat_lines = self._chat_lines[-400:]
        try:
            widget = self.query_one("#chat-log", Log)
        except Exception:
            return
        widget.clear()
        for line in self._chat_lines[-120:]:
            widget.write_line(line)

    def _show_page(self, page):
        self.current_page = page
        pages = {
            "dashboard": "#dashboard-page",
            "signals": "#signals-page",
            "learning": "#learning-page",
            "journal": "#journal-page",
            "telegram": "#telegram-page",
            "logs": "#logs-page",
        }
        for name, selector in pages.items():
            widget = self.query_one(selector)
            widget.display = name == page
        self._set_message(f"Page: {page.title()}")
        self._refresh_views()

    def _set_message(self, message):
        self._message = message
        self.query_one("#message-bar", Static).update(f"{self._message}")

    def _refresh_views(self):
        snapshot = self.runtime.snapshot()
        outcomes = self.runtime.signal_outcomes()
        manuals = self.runtime.journal_summary()

        self._signal_map = {item.get("signal_id"): item for item in outcomes if item.get("signal_id")}
        self._manual_map = {item.get("signal_id"): item for item in manuals if item.get("signal_id")}

        self._refresh_header(snapshot)
        self._refresh_dashboard(snapshot)

        if self.current_page == "signals":
            self._refresh_signals_page()
        elif self.current_page == "learning":
            self._refresh_learning_page()
        elif self.current_page == "journal":
            self._refresh_journal_page()
        elif self.current_page == "telegram":
            self._refresh_telegram_page()
        elif self.current_page == "logs":
            self._refresh_logs_page()

    def _refresh_header(self, snapshot):
        scanner = snapshot.get("scanner") or {}
        status = scanner.get("status", "IDLE")
        mode = scanner.get("mode", "MANUAL_ANALYSIS")
        cycle = scanner.get("cycle", 0)
        processed = scanner.get("processed", 0)
        success = scanner.get("success", 0)
        failed = scanner.get("failed", 0)
        symbol = snapshot.get("current_symbol") or "-"
        self.sub_title = (
            f"{status} | mode {mode} | symbol {symbol} | "
            f"cycle {cycle} | processed {processed} | success {success} | failed {failed}"
        )

    def _refresh_dashboard(self, snapshot):
        scanner = snapshot.get("scanner") or {}
        recent = snapshot.get("recent") or []
        current = snapshot.get("current_signal") or {}
        current_symbol = snapshot.get("current_symbol") or "-"

        directions = Counter(item.get("direction") for item in recent)
        decisions = Counter(item.get("decision") for item in recent)

        scanner_text = [
            "SYSTEM STATUS",
            "",
            f"Mode: {scanner.get('mode', 'MANUAL_ANALYSIS')}",
            f"Current Symbol: {current_symbol}",
            f"Status: {scanner.get('status', 'READY')}",
            f"Scanned: {scanner.get('processed', 0)}",
            f"LONG: {directions.get('LONG', 0)}",
            f"SHORT: {directions.get('SHORT', 0)}",
            f"WAIT: {directions.get('WAIT', 0)}",
            f"EXECUTE: {decisions.get('EXECUTE', 0) + decisions.get('EXECUTE_WITH_CAUTION', 0)}",
            f"Failed: {scanner.get('failed', 0)}",
        ]
        self.query_one("#dashboard-scanner", Static).update("\n".join(scanner_text))

        current_signal_id = current.get("signal_id")
        manual = self._manual_map.get(current_signal_id)
        manual_status = (manual or {}).get("status", "-")
        manual_result = (manual or {}).get("result", "-")

        current_text = [
            "CURRENT SIGNAL",
            "",
            f"Signal ID: {current_signal_id or '-'}",
            f"Symbol: {current.get('symbol', '-')}",
            f"Direction: {current.get('direction', '-')}",
            f"Entry: {_fmt_num(current.get('entry'))}",
            f"SL: {_fmt_num(current.get('stop_loss'))}",
            f"TP1: {_fmt_num(current.get('tp1'))}",
            f"TP2: {_fmt_num(current.get('tp2'))}",
            f"TP3: {_fmt_num(current.get('tp3'))}",
            f"RR: {_fmt_num(current.get('rr'))}",
            f"Confidence: {_fmt_pct(current.get('confidence'))}",
            f"Grade: {current.get('grade', '-')}",
            f"Decision: {current.get('decision', '-')}",
            f"Manual Score: {_fmt_num(current.get('manual_score'), 2)}",
            f"Historical Edge: {_fmt_num(current.get('historical_edge'))}",
            f"Reliability: {_fmt_num(current.get('reliability'))}",
            f"Expected R: {_fmt_num(current.get('expected_r'))}",
            f"Learning Adj: {_fmt_num(current.get('learning_adjustment'), 2)}",
            f"Setup Quality: {_fmt_num(current.get('setup_quality'), 2)}",
            f"Manual Status: {manual_status}",
            f"Manual Result: {manual_result}",
        ]
        self.query_one("#dashboard-current", Static).update("\n".join(current_text))

        manual_panel = [
            "MANUAL ISLEM",
            "",
            f"Signal ID: {current_signal_id or '-'}",
            f"Status: {manual_status}",
            f"Result: {manual_result}",
            "",
            "G=GIRDIM  N=GIRMEDIM  T=TP  X=SL  E=ERKEN CIKTIM",
        ]
        open_trades = self.runtime.open_manual_trades()
        if open_trades:
            manual_panel.append("")
            manual_panel.append("OPEN TRADES:")
            for row in open_trades[:3]:
                manual_panel.append(
                    f"- {row.get('symbol', '-')} {row.get('side', '-')} entry {_fmt_num(row.get('entry'))} [{row.get('status')}]"
                )
        self.query_one("#dashboard-manual-info", Static).update("\n".join(manual_panel))

        learning = self.runtime.learning_panel()
        learning_panel = [
            "LEARNING",
            f"Closed: {learning.get('closed_manual_trades', 0)}  Wins: {learning.get('wins', 0)}  Losses: {learning.get('losses', 0)}",
            f"Win Rate: {_fmt_num(learning.get('win_rate'), 2)}%  AvgR: {_fmt_num(learning.get('average_r'))}  Exp: {_fmt_num(learning.get('expectancy'))}",
            f"PF: {_fmt_num(learning.get('profit_factor'))}  Hist Edge: {_fmt_num(learning.get('historical_edge'))}  Rel: {_fmt_num(learning.get('reliability'))}",
        ]
        self.query_one("#dashboard-learning", Static).update("\n".join(learning_panel))

        recent_lines = ["SON SINYALLER", ""]
        for row in list(recent)[-8:][::-1]:
            signal_id = row.get("signal_id")
            manual_row = self._manual_map.get(signal_id) or {}
            manual_status = manual_row.get("status", "-")
            manual_result = manual_row.get("result", "-")
            recent_lines.append(
                f"{row.get('symbol', '-')} {row.get('direction', '-')} {row.get('grade', '-')} "
                f"{_fmt_pct(row.get('confidence'))} RR {_fmt_num(row.get('rr'), 2)} "
                f"{row.get('decision', '-')} {manual_status}/{manual_result}"
            )
        self.query_one("#dashboard-recent", Static).update("\n".join(recent_lines))

    def _refresh_signals_page(self):
        table = self.query_one("#signals-table", DataTable)
        rows = self.runtime.signal_outcomes()
        rows = rows[:300]

        table.clear(columns=False)
        self._signal_rows = rows
        for row in rows:
            signal_id = row.get("signal_id") or "-"
            manual = self._manual_map.get(signal_id) or {}
            table.add_row(
                signal_id,
                row.get("symbol", "-"),
                row.get("direction", "-"),
                str(row.get("grade", "-")),
                _fmt_pct(row.get("confidence")),
                _fmt_num(row.get("rr"), 2),
                str((row.get("payload") or {}).get("decision_action") or "-"),
                str(manual.get("status") or "-"),
                str(manual.get("result") or "-"),
            )

        selected = self._selected_signal_row()
        detail = self._signal_detail_text(selected)
        self.query_one("#signals-details", Static).update(detail)

    def _signal_detail_text(self, signal):
        if not signal:
            return "SIGNAL DETAIL\n\nNo signal selected"
        signal_id = signal.get("signal_id")
        manual = self._manual_map.get(signal_id) or {}
        payload = signal.get("payload") or {}
        learning = payload.get("learning") if isinstance(payload, dict) else {}

        lines = [
            "SIGNAL DETAIL",
            "",
            f"Signal ID: {signal_id}",
            f"Symbol: {signal.get('symbol', '-')}",
            f"Direction: {signal.get('direction', '-')}",
            f"Entry: {_fmt_num(signal.get('entry'))}",
            f"SL: {_fmt_num(signal.get('stop_loss'))}",
            f"TP1: {_fmt_num(signal.get('tp1'))}",
            f"TP2: {_fmt_num(signal.get('tp2'))}",
            f"TP3: {_fmt_num(signal.get('tp3'))}",
            f"RR: {_fmt_num(signal.get('rr'), 2)}",
            f"SMC Setup: {payload.get('setup_type', '-') if isinstance(payload, dict) else '-'}",
            f"Learning Matched: {str((learning or {}).get('matched', False)) if isinstance(learning, dict) else '-'}",
            f"Historical Edge: {_fmt_num((learning or {}).get('historical_edge')) if isinstance(learning, dict) else '-'}",
            f"Reliability: {_fmt_num((learning or {}).get('reliability')) if isinstance(learning, dict) else '-'}",
            f"Expected R: {_fmt_num((learning or {}).get('expected_r')) if isinstance(learning, dict) else '-'}",
            f"Manual Status: {manual.get('status', '-')}",
            f"Manual Result: {manual.get('result', '-')}",
            f"Manual Entry: {_fmt_num(manual.get('entry'))}",
            f"Manual Exit: {_fmt_num(manual.get('actual_exit'))}",
            f"Manual R: {_fmt_num(manual.get('pnl_rr'))}",
        ]
        return "\n".join(lines)

    def _refresh_learning_page(self):
        panel = self.runtime.learning_panel()
        records = self.runtime.learning_records(source="manual")

        setup_stats = self._group_metrics(records, lambda row: row.get("setup_fingerprint") or "UNKNOWN")
        regime_stats = self._group_metrics(records, lambda row: row.get("regime") or "UNKNOWN")
        direction_stats = self._group_metrics(records, lambda row: row.get("direction") or "UNKNOWN")
        timeframe_stats = self._group_metrics(records, lambda row: row.get("timeframe") or "UNKNOWN")

        best = sorted(setup_stats.items(), key=lambda item: item[1]["expectancy"], reverse=True)[:5]
        worst = sorted(setup_stats.items(), key=lambda item: item[1]["expectancy"])[:5]

        losses = [row for row in records if row.get("r", 0) < 0]
        loss_patterns = Counter(row.get("setup_fingerprint") or "UNKNOWN" for row in losses).most_common(5)

        lines = [
            "LEARNING ANALYTICS",
            "",
            f"Source: {panel.get('source', '-')}",
            f"Closed Manual Trades: {panel.get('closed_manual_trades', 0)}",
            f"Wins: {panel.get('wins', 0)}  Losses: {panel.get('losses', 0)}  Win Rate: {_fmt_num(panel.get('win_rate'), 2)}%",
            f"Average R: {_fmt_num(panel.get('average_r'))}  Expectancy: {_fmt_num(panel.get('expectancy'))}  Profit Factor: {_fmt_num(panel.get('profit_factor'))}",
            f"Historical Edge: {_fmt_num(panel.get('historical_edge'))}  Reliability: {_fmt_num(panel.get('reliability'))}",
            f"Matched Setups: {panel.get('matched_setups', 0)}  Learning Adjustment: {_fmt_num(panel.get('learning_adjustment'))}",
            "",
            "BEST SETUPS:",
        ]
        for setup, metrics in best:
            lines.append(
                f"- {setup} | n={metrics['count']} win%={_fmt_num(metrics['win_rate'], 2)} exp={_fmt_num(metrics['expectancy'])} pf={_fmt_num(metrics['profit_factor'])}"
            )

        lines.append("")
        lines.append("WORST SETUPS:")
        for setup, metrics in worst:
            lines.append(
                f"- {setup} | n={metrics['count']} win%={_fmt_num(metrics['win_rate'], 2)} exp={_fmt_num(metrics['expectancy'])} pf={_fmt_num(metrics['profit_factor'])}"
            )

        lines.append("")
        lines.append("LOSS PATTERNS:")
        for setup, count in loss_patterns:
            lines.append(f"- {setup}: {count}")

        lines.append("")
        lines.append("MARKET REGIME PERFORMANCE:")
        for regime, metrics in regime_stats.items():
            lines.append(
                f"- {regime} | n={metrics['count']} win%={_fmt_num(metrics['win_rate'], 2)} exp={_fmt_num(metrics['expectancy'])}"
            )

        lines.append("")
        lines.append("LONG/SHORT PERFORMANCE:")
        for side, metrics in direction_stats.items():
            lines.append(
                f"- {side} | n={metrics['count']} win%={_fmt_num(metrics['win_rate'], 2)} exp={_fmt_num(metrics['expectancy'])}"
            )

        lines.append("")
        lines.append("TIMEFRAME PERFORMANCE:")
        for timeframe, metrics in timeframe_stats.items():
            lines.append(
                f"- {timeframe} | n={metrics['count']} win%={_fmt_num(metrics['win_rate'], 2)} exp={_fmt_num(metrics['expectancy'])}"
            )

        self.query_one("#learning-view", Static).update("\n".join(lines))

    def _refresh_journal_page(self):
        trades = self.runtime.journal_summary()
        table = self.query_one("#journal-table", DataTable)

        filtered = []
        for trade in trades:
            status = str(trade.get("status") or "")
            result = str(trade.get("result") or "")
            if self._journal_filter == "ALL":
                filtered.append(trade)
                continue
            if self._journal_filter == "NOT_TRADED" and status == "NOT_TRADED":
                filtered.append(trade)
                continue
            if result == self._journal_filter:
                filtered.append(trade)

        table.clear(columns=False)
        self._journal_rows = filtered
        for row in filtered[:400]:
            setup = row.get("setup_fingerprint") or row.get("original_setup_fingerprint") or "-"
            table.add_row(
                _fmt_time(row.get("opened_at")),
                row.get("signal_id") or "-",
                row.get("symbol") or "-",
                row.get("side") or "-",
                setup,
                row.get("result") or row.get("status") or "-",
                _fmt_num(row.get("pnl_rr")),
                _fmt_num(row.get("entry")),
                _fmt_num(row.get("actual_exit")),
            )

        self.query_one("#journal-filter", Static).update(
            f"Journal Filter: {self._journal_filter} (press F to cycle) | rows: {len(filtered)}"
        )

    def _refresh_telegram_page(self):
        status = self.runtime.telegram_status()
        lines = [
            "TELEGRAM",
            "",
            f"Connected: {status.get('connected')}",
            f"Bot Status: {'RUNNING' if status.get('service_running') else 'STOPPED'}",
            f"Polling Enabled: {status.get('polling_enabled')}",
            f"Webhook Enabled: {status.get('webhook_enabled')}",
            f"Last Signal: {status.get('last_signal') or '-'}",
            f"Last Message: {status.get('last_message') or '-'}",
            f"Last Error: {status.get('last_error') or '-'}",
        ]
        self.query_one("#telegram-view", Static).update("\n".join(lines))

    def _refresh_logs_page(self):
        logs = self.runtime.logs()
        widget = self.query_one("#logs-view", Log)
        if len(logs) < self._log_count:
            widget.clear()
            self._log_count = 0
        for line in logs[self._log_count:]:
            widget.write_line(line)
        self._log_count = len(logs)

    def _selected_signal_row(self):
        if not self._signal_rows:
            return None
        table = self.query_one("#signals-table", DataTable)
        row_index = table.cursor_row
        if row_index is None:
            return self._signal_rows[0]
        if row_index < 0 or row_index >= len(self._signal_rows):
            return self._signal_rows[0]
        return self._signal_rows[row_index]

    def _target_signal(self, open_required=False):
        candidate = None
        if self.current_page == "signals":
            candidate = self._selected_signal_row()
        if candidate is None:
            candidate = self.runtime.snapshot().get("current_signal") or {}

        signal_id = candidate.get("signal_id")
        if signal_id and signal_id in self._signal_map:
            signal = dict(self._signal_map.get(signal_id) or {})
            signal["signal_id"] = signal_id
        else:
            signal = dict(candidate or {})

        if open_required:
            manual = self._manual_map.get(signal.get("signal_id")) or {}
            if manual.get("status") != "OPEN":
                return None
        return signal

    def _group_metrics(self, rows, key_fn):
        buckets = defaultdict(list)
        for row in rows:
            buckets[key_fn(row)].append(row)
        metrics = {}
        for key, values in buckets.items():
            r_values = [float(item.get("r") or 0.0) for item in values]
            wins = [item for item in values if float(item.get("r") or 0.0) > 0]
            losses = [item for item in values if float(item.get("r") or 0.0) < 0]
            win_rate = (len(wins) / len(values) * 100.0) if values else 0.0
            expectancy = sum(r_values) / len(r_values) if r_values else 0.0
            total_wins = sum(v for v in r_values if v > 0)
            total_losses = abs(sum(v for v in r_values if v < 0))
            profit_factor = total_wins / total_losses if total_losses > 0 else total_wins
            metrics[key] = {
                "count": len(values),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": win_rate,
                "expectancy": expectancy,
                "profit_factor": profit_factor,
            }
        return dict(metrics)
