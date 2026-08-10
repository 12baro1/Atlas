import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.atlas_chat_agent import AtlasChatAgent, DIRECT_CHAT_SYSTEM_PROMPT


class _DummyManualService:
    def __init__(self):
        self.actions = []

    def open_trade(self, **kwargs):
        self.actions.append(("open", kwargs))
        return ({"signal_id": kwargs.get("signal_id")}, "opened")

    def mark_not_traded(self, **kwargs):
        self.actions.append(("not_traded", kwargs))
        return ({"signal_id": kwargs.get("signal_id")}, "not_traded")

    def close_trade(self, **kwargs):
        self.actions.append(("close", kwargs))
        return ({"signal_id": kwargs.get("signal_id"), "result": kwargs.get("result")}, "closed")

    def resolve_signal_id(self, **kwargs):
        return "ATL-20260810-000001"


class _DummyRuntime:
    def __init__(self):
        self.calls = []
        self.manual_service = _DummyManualService()

    def normalize_symbol(self, raw):
        text = str(raw or "").strip().upper()
        if not text:
            return None
        if "/" in text and ":" in text:
            return text
        return f"{text}/USDT:USDT"

    def analyze_symbol(self, symbol, force_refresh=False):
        self.calls.append(("analyze_symbol", symbol, force_refresh))
        normalized = self.normalize_symbol(symbol)
        return {
            "ok": True,
            "symbol": normalized,
            "result": {
                "symbol": normalized,
                "signal": {"signal": "LONG", "confidence": 92, "grade": "A+", "signal_reason": "ok"},
                "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "tp2": 102.0, "tp3": 103.0, "rr": 3.0},
                "analysis": {
                    "market_phase": {"phase": "Expansion"},
                    "confluence": {"score": 88, "checks": ["mtf", "fvg", "sweep"]},
                    "setup_quality": {
                        "score": 91,
                        "setup_fingerprint": "fvg|liquidity_sweep",
                        "learning": {"historical_edge": 0.42, "reliability": 0.81, "expected_r": 0.61},
                    },
                },
                "decision": {"action": "EXECUTE", "reason": "quality high"},
            },
        }

    def current_signal(self):
        self.calls.append(("current_signal",))
        return {
            "signal_id": "ATL-20260810-000001",
            "symbol": "BTC/USDT:USDT",
            "direction": "LONG",
            "rr": 3.0,
            "entry": 100.0,
            "stop_loss": 99.0,
            "tp1": 101.0,
            "tp2": 102.0,
            "tp3": 103.0,
            "decision": "EXECUTE",
            "manual_status": "OPEN",
            "manual_result": None,
        }

    def learning_panel(self):
        self.calls.append(("learning_panel",))
        return {"wins": 12, "losses": 8, "expectancy": 0.2}

    def manual_trades(self, limit=200, status=None, symbol=None):
        self.calls.append(("manual_trades", limit, status, symbol))
        return [
            {"status": "CLOSED", "result": "LOSS", "pnl_rr": -1.0, "manual_exit_reason": "stop_loss_hit", "setup_fingerprint": "fvg|a"},
            {"status": "CLOSED", "result": "LOSS", "pnl_rr": -0.8, "manual_exit_reason": "tight_stop", "setup_fingerprint": "fvg|a"},
            {"status": "CLOSED", "result": "WIN", "pnl_rr": 1.6, "manual_exit_reason": "tp", "setup_fingerprint": "fvg|b"},
        ]

    def signal_outcomes(self, limit=400, status=None, symbol=None):
        self.calls.append(("signal_outcomes", limit, status, symbol))
        return []

    def learning_records(self, source="manual", symbol=None, as_of_ms=None):
        self.calls.append(("learning_records", source, symbol, as_of_ms))
        return [
            {"setup_fingerprint": "fvg|a", "result": "LOSS", "r": -1.0, "win": False},
            {"setup_fingerprint": "fvg|a", "result": "WIN", "r": 1.2, "win": True},
            {"setup_fingerprint": "fvg|a", "result": "LOSS", "r": -0.6, "win": False},
        ]

    def setup_statistics(self):
        self.calls.append(("setup_statistics",))
        return {"EXECUTE": {"count": 10, "winrate": 55.0}}

    def open_manual_trades(self, symbol=None):
        self.calls.append(("open_manual_trades", symbol))
        return [{"signal_id": "ATL-20260810-000001", "symbol": "BTC/USDT:USDT", "status": "OPEN"}]


class _FakeClient:
    def create_completion(self, *, messages, tools=None, tool_choice="auto"):
        last = messages[-1]
        if last["role"] == "user":
            text = str(last["content"] or "").lower()
            if "hey atlas" in text:
                return {"message": {"content": "Iyiyim, buradayim. Sana nasil yardim edeyim?"}}
            if "sen kimsin" in text:
                return {"message": {"content": "Ben Atlas'im; SMC analiz, journal ve learning verilerinle calisan asistanim."}}
            if "btc'yi incele" in text or "btcyi incele" in text or "btcyi incele" in text:
                return {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-1",
                                "type": "function",
                                "function": {"name": "analyze_symbol", "arguments": json.dumps({"symbol": "BTC"})},
                            }
                        ],
                    }
                }
            if "son islemlerim neden kaybediyor" in text:
                return {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-2",
                                "type": "function",
                                "function": {"name": "get_manual_trades", "arguments": json.dumps({"status": "CLOSED", "limit": 30})},
                            }
                        ],
                    }
                }
            if "benzer gecmis islemlerimi goster" in text:
                return {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-3",
                                "type": "function",
                                "function": {"name": "get_learning_records", "arguments": json.dumps({"source": "manual", "limit": 50})},
                            }
                        ],
                    }
                }
            if "ben girdim" in text:
                return {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-4",
                                "type": "function",
                                "function": {
                                    "name": "prepare_ui_action",
                                    "arguments": json.dumps({"action_type": "open_trade_prompt", "message": "Tamam, gercek girisi alalim."}),
                                },
                            }
                        ],
                    }
                }
            if "tp oldu" in text:
                return {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-5",
                                "type": "function",
                                "function": {
                                    "name": "prepare_ui_action",
                                    "arguments": json.dumps(
                                        {
                                            "action_type": "close_trade_prompt",
                                            "result": "TP",
                                            "message": "Super. Cikis fiyatini alip TP kaydedecegim.",
                                        }
                                    ),
                                },
                            }
                        ],
                    }
                }
            if "az onceki" in text:
                return {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-6",
                                "type": "function",
                                "function": {"name": "get_current_signal", "arguments": "{}"},
                            }
                        ],
                    }
                }
            return {"message": {"content": "Anladim."}}

        if last["role"] == "tool":
            name = last.get("name")
            payload = json.loads(last.get("content") or "{}")
            if name == "analyze_symbol":
                return {"message": {"content": "BTC analizi tamamlandi: LONG, RR 3.0, karar EXECUTE."}}
            if name == "get_manual_trades":
                losses = sum(1 for row in payload if str(row.get("result")) == "LOSS")
                return {"message": {"content": f"Kapanan islemlerde {losses} loss var; stop tarafinda sikisma gorunuyor."}}
            if name == "get_learning_records":
                return {"message": {"content": f"Benzer kayitlardan {len(payload)} ornek buldum; loss agirligi dikkat cekiyor."}}
            if name == "prepare_ui_action":
                return {"message": {"content": payload.get("message") or "Hazir."}}
            if name == "get_current_signal":
                return {"message": {"content": f"Az onceki sinyal RR {payload.get('rr')} ve yon {payload.get('direction')} idi."}}
            return {"message": {"content": "Arac sonucu alindi."}}

        return {"message": {"content": "Devam edelim."}}


class _StreamingClient:
    def __init__(self):
        self.calls = []

    def stream_completion(self, *, messages, max_tokens=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        yield {"choices": [{"delta": {"content": "Merhaba"}}]}
        yield {"choices": [{"delta": {"content": "."}}]}


def test_ai_chat_agent_natural_conversation_flow():
    runtime = _DummyRuntime()
    agent = AtlasChatAgent(runtime)
    agent._client = _FakeClient()

    r1 = agent.handle("Hey Atlas")
    assert "Iyiyim" in r1.text

    r2 = agent.handle("Sen kimsin?")
    assert "Atlas" in r2.text

    r3 = agent.handle("BTC'yi incele")
    assert "LONG" in r3.text
    assert any(call[0] == "analyze_symbol" for call in runtime.calls)

    r4 = agent.handle("Son islemlerim neden kaybediyor?")
    assert "loss" in r4.text.lower()
    assert any(call[0] == "manual_trades" for call in runtime.calls)

    r5 = agent.handle("Benzer gecmis islemlerimi goster")
    assert "ornek" in r5.text.lower()
    assert any(call[0] == "learning_records" for call in runtime.calls)

    r6 = agent.handle("Ben girdim")
    assert r6.action is not None
    assert r6.action.get("type") == "open_trade_prompt"

    r7 = agent.handle("TP oldu")
    assert r7.action is not None
    assert r7.action.get("type") == "close_trade_prompt"
    assert r7.action.get("result") == "TP"

    r8 = agent.handle("Az onceki islemin RR degeri neydi?")
    assert "RR" in r8.text or "rr" in r8.text
    assert any(call[0] == "current_signal" for call in runtime.calls)


def test_ai_chat_agent_streams_simple_chat_without_tools():
    runtime = _DummyRuntime()
    agent = AtlasChatAgent(runtime)
    client = _StreamingClient()
    agent._client = client

    chunks = []
    result = agent.handle("Hey Atlas", on_text_delta=chunks.append)

    assert result.text == "Merhaba."
    assert chunks == ["Merhaba", "."]
    assert len(client.calls) == 1
    assert client.calls[0]["max_tokens"] == agent._max_tokens("simple")
    assert client.calls[0]["messages"][0]["content"] == DIRECT_CHAT_SYSTEM_PROMPT
    assert len(client.calls[0]["messages"]) == 2
