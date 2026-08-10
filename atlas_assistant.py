"""Conversational layer for Atlas terminal assistant.

This module only reads real runtime/engine/journal state and triggers safe actions.
It never sends exchange orders.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ai.atlas_chat_agent import AtlasChatAgent


class _RuleBasedAtlasAssistant:
    """Natural-language assistant over Atlas runtime tools."""

    _STOPWORDS = {
        "ANALIZ",
        "ANALIZET",
        "BAK",
        "BAKAR",
        "BAKARMISIN",
        "NEDEN",
        "NIYE",
        "NASIL",
        "NE",
        "DURUM",
        "DURUMDA",
        "SON",
        "SINYAL",
        "ISLEM",
        "TRADE",
        "SETUP",
        "GECMISTE",
        "KAC",
        "KERE",
        "RR",
        "STOP",
        "SL",
        "TP",
        "TP1",
        "TP2",
        "TP3",
        "LEARNING",
        "JOURNAL",
        "GIRDIM",
        "GIRMEDIM",
        "ERKEN",
        "CIKTIM",
        "OLDUM",
        "BEN",
        "SEN",
        "VE",
        "ILE",
        "BIR",
        "BU",
        "SU",
        "O",
    }

    def __init__(self, runtime):
        self.runtime = runtime
        self.conversation = []
        self.last_symbol = None
        self.last_analysis = None
        self.last_topic = None

    @staticmethod
    def _fold_text(value):
        text = str(value or "")
        translation = str.maketrans(
            {
                "c": "c",
                "g": "g",
                "i": "i",
                "o": "o",
                "s": "s",
                "u": "u",
                "C": "C",
                "G": "G",
                "I": "I",
                "O": "O",
                "S": "S",
                "U": "U",
                "ç": "c",
                "ğ": "g",
                "ı": "i",
                "ö": "o",
                "ş": "s",
                "ü": "u",
                "Ç": "C",
                "Ğ": "G",
                "İ": "I",
                "Ö": "O",
                "Ş": "S",
                "Ü": "U",
            }
        )
        return text.translate(translation).lower()

    # ------------------------------------------------------------------
    # Public tool-style API
    # ------------------------------------------------------------------
    def analyze_symbol(self, symbol):
        return self.runtime.analyze_symbol(symbol, force_refresh=True)

    def get_current_signal(self):
        return self.runtime.current_signal()

    def get_learning_stats(self):
        return self.runtime.learning_panel()

    def get_trade_history(self):
        return self.runtime.journal_summary()

    def get_signal_history(self):
        return self.runtime.signal_outcomes()

    def get_journal_stats(self):
        return {
            "manual": self.runtime.manual_performance(),
            "signal": self.runtime.signal_performance(),
        }

    def get_open_trades(self):
        return self.runtime.open_manual_trades()

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------
    def handle_user_message(self, message):
        text = str(message or "").strip()
        lower = text.lower()
        folded = self._fold_text(text)
        self.conversation.append({"role": "user", "text": text})

        if not text:
            return self._reply("Mesaji goremedim. Lutfen tekrar yaz.")

        if self._is_order_request(folded):
            return self._reply("Ben otomatik emir gondermiyorum. Manuel islem modundayim.")

        manual_action = self._detect_manual_action(folded)
        if manual_action is not None:
            return self._reply(manual_action["message"], action=manual_action["action"])

        symbol = self._extract_symbol(text)
        if self._is_analysis_intent(folded, symbol):
            return self._handle_analysis(symbol)

        if self._is_why_query(folded):
            return self._handle_why(symbol=symbol)

        if "son sinyal" in folded:
            return self._handle_last_signal()

        if "historical edge" in folded or "edge" in folded:
            return self._handle_edge(symbol)

        if folded.startswith("rr") or " rr " in f" {folded} " or "rr kac" in folded or "rr kac?" in folded:
            return self._handle_level_query("rr", symbol)
        if "stop" in folded or "sl nerede" in folded:
            return self._handle_level_query("sl", symbol)
        if "tp1" in folded:
            return self._handle_level_query("tp1", symbol)
        if "tp2" in folded:
            return self._handle_level_query("tp2", symbol)
        if "tp3" in folded:
            return self._handle_level_query("tp3", symbol)

        if "bu setup" in folded or "setup gecmiste" in folded:
            if "sl" in folded and "kac" in folded:
                return self._handle_setup_history(only_losses=True)
            return self._handle_setup_history(only_losses=False)

        if "son 20" in folded and ("islem" in folded or "trade" in folded):
            return self._handle_last_n_trades(20)

        if "en iyi setup" in folded:
            return self._handle_setup_rank(best=True)
        if "en kotu setup" in folded:
            return self._handle_setup_rank(best=False)

        if "learning ne ogrendi" in folded:
            return self._handle_learning_summary()

        if symbol and ("ne durumda" in folded or "durumu" in folded):
            return self._handle_analysis(symbol)

        if symbol and ("neden" in folded or "niye" in folded):
            return self._handle_why(symbol=symbol)

        return self._reply("Bunu mevcut verilerden dogrulayamiyorum.")

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------
    def _handle_analysis(self, symbol):
        if not symbol:
            symbol = self.last_symbol
        if not symbol:
            return self._reply("Hangi sembolu analiz etmemi istedigini anlayamadim.")

        start = f"Tabii. {symbol} analizine basliyorum."
        analyzed = self.analyze_symbol(symbol)
        if not analyzed.get("ok"):
            code = analyzed.get("error")
            if code == "symbol_not_found":
                return self._reply(f"{symbol} sembolunu borsada dogrulayamadim.", preface=start)
            if code == "no_result":
                return self._reply(f"{symbol} icin analiz tamamlandi ama sinyal uretilemedi.", preface=start)
            return self._reply(f"{symbol} analizinde hata aldim: {code}", preface=start)

        result = analyzed.get("result") or {}
        self.last_symbol = symbol
        self.last_analysis = result
        self.last_topic = "analysis"

        signal = result.get("signal") or {}
        decision = result.get("decision") or {}
        analysis = result.get("analysis") or {}
        setup_quality = analysis.get("setup_quality") or {}
        learning = setup_quality.get("learning") or signal.get("learning") or {}

        lines = [
            "Analiz tamamlandi.",
            "",
            f"4H yapi: {self._dir_label((analysis.get('mtf') or {}).get('h4'))}",
            f"15M yapi: {self._dir_label((analysis.get('mtf') or {}).get('entry'))}",
            f"Liquidity Sweep: {'Var' if bool((analysis.get('liquidity_sweep') or {}).get('is_sweep')) else 'Yok'}",
            f"FVG: {'Var' if bool(analysis.get('fvg')) else 'Yok'}",
            f"Historical Edge: {self._fmt_signed_r(learning.get('historical_edge'))}",
            f"Reliability: {self._fmt_pct(learning.get('reliability'), scale=100)}",
            f"Final Quality: {self._fmt_num(setup_quality.get('score'), digits=0)}",
            f"Decision: {decision.get('action', '-')}",
        ]
        return self._reply("\n".join(lines), preface=start)

    def _handle_why(self, symbol=None):
        result = self._resolve_analysis(symbol=symbol)
        if result is None:
            return self._reply("Once ilgili sembolu analiz etmeliyim.")

        signal = result.get("signal") or {}
        decision = result.get("decision") or {}
        analysis = result.get("analysis") or {}
        confluence = analysis.get("confluence") or {}
        setup_quality = analysis.get("setup_quality") or {}

        direction = signal.get("signal", "WAIT")
        reason = signal.get("signal_reason") or signal.get("wait_reason") or decision.get("reason") or "-"
        blockers = list(decision.get("critical_blockers") or []) + list(setup_quality.get("blockers") or [])
        checks = list(confluence.get("checks") or [])

        lines = [
            f"Az onceki {result.get('symbol', self.last_symbol)} analizine gore yon: {direction}.",
            f"Ana gerekce: {reason}",
        ]
        if decision.get("action"):
            lines.append(f"Decision: {decision.get('action')}")
        if blockers:
            lines.append(f"Bloklayicilar: {'; '.join(str(item) for item in blockers[:4])}")
        if checks:
            lines.append("Confluence: " + ", ".join(str(item) for item in checks[:4]))

        self.last_topic = "why"
        return self._reply("\n".join(lines))

    def _handle_last_signal(self):
        signal = self.get_current_signal() or {}
        if not signal:
            return self._reply("Henuz aktif bir sinyal yok.")
        lines = [
            "Son sinyal:",
            f"Signal ID: {signal.get('signal_id') or '-'}",
            f"Symbol: {signal.get('symbol') or '-'}",
            f"Direction: {signal.get('direction') or '-'}",
            f"Decision: {signal.get('decision') or '-'}",
            f"RR: {self._fmt_num(signal.get('rr'), digits=2)}",
            f"Confidence: {self._fmt_pct(signal.get('confidence'))}",
            f"Manual: {signal.get('manual_status') or '-'} / {signal.get('manual_result') or '-'}",
        ]
        return self._reply("\n".join(lines))

    def _handle_edge(self, symbol=None):
        signal = self._resolve_current_signal(symbol=symbol)
        if not signal:
            panel = self.get_learning_stats() or {}
            value = panel.get("historical_edge")
            if value is None:
                return self._reply("Bunu mevcut verilerden dogrulayamiyorum.")
            return self._reply(f"Genel historical edge: {self._fmt_signed_r(value)}")
        return self._reply(
            f"{signal.get('symbol')} historical edge: {self._fmt_signed_r(signal.get('historical_edge'))}"
        )

    def _handle_level_query(self, key, symbol=None):
        signal = self._resolve_current_signal(symbol=symbol)
        if not signal:
            return self._reply("Once sembol analizi gerekli.")

        mapping = {
            "rr": ("RR", signal.get("rr")),
            "sl": ("Stop Loss", signal.get("stop_loss")),
            "tp1": ("TP1", signal.get("tp1")),
            "tp2": ("TP2", signal.get("tp2")),
            "tp3": ("TP3", signal.get("tp3")),
        }
        label, value = mapping[key]
        digits = 2 if key == "rr" else 4
        return self._reply(f"{signal.get('symbol')} {label}: {self._fmt_num(value, digits=digits)}")

    def _handle_setup_history(self, only_losses=False):
        result = self._resolve_analysis(symbol=None)
        if result is None:
            return self._reply("Once ilgili setup icin bir analiz gerekli.")

        setup_fingerprint = ((result.get("analysis") or {}).get("setup_quality") or {}).get("setup_fingerprint")
        if not setup_fingerprint:
            return self._reply("Bu setup icin fingerprint bilgisi yok.")

        records = self.get_learning_records_manual()
        matched = [row for row in records if row.get("setup_fingerprint") == setup_fingerprint]
        if not matched:
            return self._reply("Bu setup icin gecmis manuel kayit bulamadim.")

        losses = [row for row in matched if str(row.get("result") or "").upper() == "LOSS"]
        wins = [row for row in matched if str(row.get("result") or "").upper() == "WIN"]
        expectancy = sum(float(row.get("r") or 0.0) for row in matched) / max(len(matched), 1)

        if only_losses:
            return self._reply(
                f"Ayni setup gecmiste {len(losses)} kez SL olmus (toplam {len(matched)} manuel kapanis)."
            )

        return self._reply(
            "\n".join(
                [
                    f"Setup gecmisi (fingerprint): {setup_fingerprint}",
                    f"Toplam kapanis: {len(matched)}",
                    f"WIN: {len(wins)}  LOSS: {len(losses)}",
                    f"Expectancy: {self._fmt_signed_r(expectancy)}",
                ]
            )
        )

    def _handle_last_n_trades(self, limit):
        trades = self.get_trade_history() or []
        closed = [row for row in trades if str(row.get("status") or "") == "CLOSED"]
        sample = closed[:limit]
        if not sample:
            return self._reply("Son islemler icin kapanmis manuel trade bulunamadi.")

        wins = sum(1 for row in sample if str(row.get("result") or "") == "WIN")
        losses = sum(1 for row in sample if str(row.get("result") or "") == "LOSS")
        avg_r = sum(float(row.get("pnl_rr") or 0.0) for row in sample) / max(len(sample), 1)
        win_rate = wins / max(len(sample), 1) * 100.0
        lines = [
            f"Son {len(sample)} manuel kapanis:",
            f"WIN: {wins}  LOSS: {losses}",
            f"Win Rate: {self._fmt_num(win_rate, digits=2)}%",
            f"Average R: {self._fmt_signed_r(avg_r)}",
        ]
        return self._reply("\n".join(lines))

    def _handle_setup_rank(self, best=True):
        records = self.get_learning_records_manual()
        if not records:
            return self._reply("Setup karsilastirmasi icin manuel ogrenme kaydi yok.")

        grouped = defaultdict(list)
        for row in records:
            grouped[row.get("setup_fingerprint") or "UNKNOWN"].append(row)

        metrics = []
        for key, values in grouped.items():
            if len(values) < 3:
                continue
            expectancy = sum(float(item.get("r") or 0.0) for item in values) / max(len(values), 1)
            win_rate = sum(1 for item in values if bool(item.get("win"))) / max(len(values), 1) * 100.0
            metrics.append((key, len(values), expectancy, win_rate))

        if not metrics:
            return self._reply("Yeterli orneklem yok (en az 3 kapanis setup basina).")

        metrics.sort(key=lambda item: item[2], reverse=best)
        key, count, expectancy, win_rate = metrics[0]
        prefix = "En iyi setup" if best else "En kotu setup"
        return self._reply(
            f"{prefix}: {key} | n={count} | exp={self._fmt_signed_r(expectancy)} | win%={self._fmt_num(win_rate, digits=2)}"
        )

    def _handle_learning_summary(self):
        panel = self.get_learning_stats() or {}
        if not panel:
            return self._reply("Learning verisini su an okuyamiyorum.")

        lines = [
            "Learning ozeti:",
            f"Closed Manual Trades: {panel.get('closed_manual_trades', 0)}",
            f"Wins: {panel.get('wins', 0)}  Losses: {panel.get('losses', 0)}",
            f"Win Rate: {self._fmt_num(panel.get('win_rate'), 2)}%",
            f"Average R: {self._fmt_num(panel.get('average_r'))}",
            f"Expectancy: {self._fmt_num(panel.get('expectancy'))}",
            f"Profit Factor: {self._fmt_num(panel.get('profit_factor'))}",
            f"Historical Edge: {self._fmt_signed_r(panel.get('historical_edge'))}",
            f"Reliability: {self._fmt_pct(panel.get('reliability'), scale=100)}",
            f"Matched Setups: {panel.get('matched_setups', 0)}",
            f"Learning Adjustment: {self._fmt_num(panel.get('learning_adjustment'), 2)}",
        ]
        return self._reply("\n".join(lines))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def get_learning_records_manual(self):
        return list(self.runtime.learning_records(source="manual") or [])

    def _resolve_analysis(self, symbol=None):
        if symbol:
            normalized = self.runtime.normalize_symbol(symbol)
            cached = self.runtime.latest_analysis(normalized)
            if cached is not None:
                self.last_symbol = normalized
                self.last_analysis = cached
                return cached
            analyzed = self.analyze_symbol(normalized)
            if analyzed.get("ok"):
                self.last_symbol = normalized
                self.last_analysis = analyzed.get("result")
                return analyzed.get("result")
            return None

        if self.last_analysis is not None:
            return self.last_analysis
        cached = self.runtime.latest_analysis()
        if cached is not None:
            self.last_analysis = cached
            self.last_symbol = cached.get("symbol")
        return cached

    def _resolve_current_signal(self, symbol=None):
        target = self.runtime.normalize_symbol(symbol) if symbol else None
        signal = self.runtime.current_signal()
        if signal and (target is None or signal.get("symbol") == target):
            return signal
        history = self.get_signal_history() or []
        if target:
            for item in history:
                if item.get("symbol") == target:
                    return item
        return history[0] if history else None

    def _extract_symbol(self, text):
        direct = re.search(r"\b([A-Za-z0-9]{2,15}/USDT:USDT)\b", text, re.IGNORECASE)
        if direct:
            return self.runtime.normalize_symbol(direct.group(1))

        slash = re.search(r"\b([A-Za-z0-9]{2,15}/USDT)\b", text, re.IGNORECASE)
        if slash:
            return self.runtime.normalize_symbol(slash.group(1))

        tokens = re.findall(r"[A-Za-z]{2,15}", text)
        for token in tokens:
            upper = token.upper()
            if upper in self._STOPWORDS:
                continue
            candidate = self.runtime.normalize_symbol(upper)
            if candidate and self.runtime.symbol_exists(candidate):
                return candidate
        return None

    def _is_analysis_intent(self, lower, symbol):
        if symbol and lower.strip() in {symbol.lower(), symbol.split("/")[0].lower()}:
            return True
        triggers = ["analiz", "bak", "incele", "ne durumda", "durumu"]
        return bool(symbol and any(item in lower for item in triggers))

    def _is_why_query(self, lower):
        return "neden" in lower or "niye" in lower

    def _is_order_request(self, lower):
        patterns = ["emir gonder", "bybit", "pozisyon ac", "islem ac"]
        return any(item in lower for item in patterns)

    def _detect_manual_action(self, lower):
        if "girmedim" in lower:
            return {
                "message": "Tamam. Bu sinyali NOT_TRADED olarak kaydediyorum.",
                "action": {"type": "mark_not_traded"},
            }
        if "girdim" in lower:
            return {
                "message": "Tamam. Gercek girisi almak icin GIRDIM penceresini aciyorum.",
                "action": {"type": "open_trade_prompt"},
            }
        if "sl oldum" in lower or lower.strip() == "sl":
            return {
                "message": "Anladim. SL kaydi icin cikis fiyatini soracagim.",
                "action": {"type": "close_trade_prompt", "result": "SL", "label": "SL"},
            }
        if "tp oldum" in lower or lower.strip() == "tp":
            return {
                "message": "Anladim. TP kaydi icin cikis fiyatini soracagim.",
                "action": {"type": "close_trade_prompt", "result": "TP", "label": "TP"},
            }
        if "erken cikt" in lower:
            return {
                "message": "Tamam. Erken cikis kaydi icin cikis fiyatini soracagim.",
                "action": {"type": "close_trade_prompt", "result": "EARLY_EXIT", "label": "ERKEN CIKTIM"},
            }
        return None

    def _reply(self, text, preface=None, action=None):
        lines = []
        if preface:
            lines.append(preface)
        lines.append(text)
        payload = {
            "responses": lines,
            "action": action,
        }
        self.conversation.append({"role": "assistant", "text": "\n".join(lines)})
        return payload

    @staticmethod
    def _fmt_num(value, digits=4):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "-"
        text = f"{number:.{digits}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    @staticmethod
    def _fmt_pct(value, scale=1):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "-"
        if scale != 1:
            number *= scale
        return f"{number:.0f}%"

    def _fmt_signed_r(self, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "-"
        sign = "+" if number > 0 else ""
        return f"{sign}{self._fmt_num(number)}R"

    @staticmethod
    def _dir_label(value):
        text = str(value or "-").upper()
        mapping = {
            "BULLISH": "Bullish",
            "BEARISH": "Bearish",
            "LONG": "Bullish",
            "SHORT": "Bearish",
            "WAIT": "Wait",
        }
        return mapping.get(text, str(value or "-"))


class AtlasAssistant:
    """Primary assistant wrapper.

    - Uses real LLM + tool-calling when provider env is configured.
    - Falls back to local parser when provider is unavailable.
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self._llm_agent = AtlasChatAgent(runtime)
        self._fallback = _RuleBasedAtlasAssistant(runtime)

    def handle_user_message(self, message):
        if self._llm_agent.enabled:
            try:
                result = self._llm_agent.handle(message)
                text = str(result.text or "").strip() or "Su an anlamli bir cevap uretemedim."
                return {
                    "responses": [text],
                    "action": result.action,
                }
            except Exception as exc:
                fallback = self._fallback.handle_user_message(message)
                responses = list(fallback.get("responses") or [])
                responses.append(f"(AI katmani gecici hata verdi: {exc})")
                return {
                    "responses": responses,
                    "action": fallback.get("action"),
                }
        return self._fallback.handle_user_message(message)
