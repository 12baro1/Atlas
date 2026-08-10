"""LLM-backed Atlas chat agent with safe runtime tool access."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from config import Config
from ai.openai_compat import OpenAICompatClient, OpenAICompatConfig


SYSTEM_PROMPT = (
    "Sen Atlas adli kisisel trading assistant'sin. "
    "Kullaniciyla dogal Turkce konusursun. "
    "Veri uydurmazsin; sadece araclardan gelen gercek veriyi yorumlarsin. "
    "Kullanici emir isterse otomatik emir gondermedigini acikla. "
    "Kisa soru kisa cevap, detay talebi detayli cevap ver. "
    "Manual trade islemleri icin gerekiyorsa önce uygun araclari cagir. "
    "Fiyat gerektiren kapanis/giris islemlerinde prepare_ui_action aracini kullanarak "
    "TUI popup aksiyonu iste."
)

DIRECT_CHAT_SYSTEM_PROMPT = (
    "Sen Atlas'sin. "
    "Turkce cevap ver. "
    "Basit soruya tek kisa cumleyle cevap ver. "
    "Gereksiz reasoning/thinking kullanma."
)


@dataclass
class AgentResult:
    text: str
    action: dict | None = None


class AtlasChatAgent:
    """General-purpose conversational agent over Atlas runtime tools."""

    def __init__(self, runtime):
        self.runtime = runtime
        self._provider = "openai_compat"
        self._last_local_status = {}
        self._client = self._build_client_from_env()
        self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    @property
    def enabled(self):
        return self._client is not None

    def handle(self, user_text, on_text_delta=None):
        text = str(user_text or "").strip()
        if not text:
            return AgentResult(text="Mesaji goremedim, tekrar yazabilir misin?")

        if self._provider == "local":
            state = self._safe_ai_status()
            self._last_local_status = state
            # state boşsa (gerçek runtime yok / test ortami) gate'i atla;
            # gerçek runtime'da local ise ailine gore yonlendir.
            if state and str(state.get("status") or "").upper() != "ONLINE":
                return AgentResult(text=self._local_unavailable_message(state))

        self._messages.append({"role": "user", "content": text})
        if not self.enabled:
            return AgentResult(text=self._fallback_disabled_message())

        mode = self._request_mode(text)
        if mode != "tool":
            return self._handle_direct_response(mode=mode, on_text_delta=on_text_delta)

        tools = self._tool_specs()
        pending_action = None
        history_limit = self._history_limit("tool")
        max_tokens = self._max_tokens("tool")
        for _ in range(6):
            response = self._client_create_completion(
                messages=self._request_messages(mode="tool", limit=history_limit, include_tools=True),
                tools=tools,
                tool_choice="auto",
                max_tokens=max_tokens,
            )
            message = response.get("message") or {}
            tool_calls = list(message.get("tool_calls") or [])

            if tool_calls:
                self._messages.append(self._assistant_message_for_tools(message, tool_calls))
                for tool_call in tool_calls:
                    name = ((tool_call.get("function") or {}).get("name") or "").strip()
                    arguments = ((tool_call.get("function") or {}).get("arguments") or "{}").strip()
                    payload = self._safe_json_loads(arguments)
                    result = self._dispatch_tool(name, payload)
                    if isinstance(result, dict) and isinstance(result.get("ui_action"), dict):
                        pending_action = result.get("ui_action")
                    self._messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id"),
                            "name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                continue

            content = self._extract_text(message)
            if not content:
                content = "Su an anlamli bir cevap uretemedim."
            action = self._extract_structured_action(content)
            if action is not None:
                content = action.get("message") or ""
            self._messages.append({"role": "assistant", "content": content})
            final_action = pending_action
            if action is not None and isinstance(action.get("action"), dict):
                final_action = action.get("action")
            return AgentResult(text=content, action=final_action)

        return AgentResult(text="AI arac zincirini tamamlayamadi, lutfen tekrar dene.")

    def _build_client_from_env(self):
        Config.refresh_from_env()
        provider = str(getattr(Config, "AI_PROVIDER", "openai_compat") or "openai_compat").strip().lower()
        self._provider = provider

        timeout_seconds = float(getattr(Config, "AI_TIMEOUT_SECONDS", 180) or 180)
        temperature = float(getattr(Config, "AI_TEMPERATURE", 0.2) or 0.2)

        if provider == "local":
            status = self._safe_ai_status()
            base_url = str(status.get("base_url") or "").strip()
            if not base_url:
                host = str(getattr(Config, "AI_LOCAL_HOST", "127.0.0.1") or "127.0.0.1").strip()
                port = int(getattr(Config, "AI_LOCAL_PORT", 8080) or 8080)
                base_url = f"http://{host}:{port}/v1"
            model = self._resolve_local_model_id(base_url=base_url, status=status)
            cfg = OpenAICompatConfig(
                api_key=str(getattr(Config, "AI_API_KEY", "") or "").strip(),
                base_url=base_url,
                model=model,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
            )
            return OpenAICompatClient(cfg)

        api_key = str(getattr(Config, "AI_API_KEY", "") or "").strip()
        base_url = str(getattr(Config, "AI_BASE_URL", "https://api.openai.com") or "").strip()
        model = str(getattr(Config, "AI_MODEL", "gpt-4o-mini") or "").strip()
        if not api_key:
            return None
        cfg = OpenAICompatConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
        )
        return OpenAICompatClient(cfg)

    def _fallback_disabled_message(self):
        if self._provider == "local":
            return self._local_unavailable_message(self._safe_ai_status())
        return (
            "AI sohbet saglayicisi henuz bagli degil. "
            "ATLAS_AI_API_KEY (ve gerekirse ATLAS_AI_BASE_URL, ATLAS_AI_MODEL) tanimla; "
            "sonra Atlas'i yeniden ac."
        )

    def _local_unavailable_message(self, state):
        detail = str((state or {}).get("detail") or "offline")
        detail_map = {
            "model_not_found": "Local model dosyasi bulunamadi.",
            "llama_server_not_found": "llama-server binary bulunamadi.",
            "auto_start_disabled": "Local AI auto-start kapali.",
            "startup_timeout": "Local AI acilisi zaman asimina ugradi.",
            "offline": "Local AI offline.",
            "none": "Local AI offline.",
        }
        note = detail_map.get(detail, f"Local AI hazir degil ({detail}).")
        return (
            f"{note} "
            "ATLAS_AI_LOCAL_MODEL_FILE / llama-server yolunu kontrol et; "
            "gerekirse Atlas'i yeniden baslat."
        )

    def _safe_ai_status(self):
        try:
            if self.runtime is not None and hasattr(self.runtime, "ai_status"):
                state = self.runtime.ai_status()
                if isinstance(state, dict):
                    return state
        except Exception:
            pass
        return {}

    def _resolve_local_model_id(self, *, base_url, status):
        """Local server'in gercek model id'sini /v1/models'ten alir.

        - Online ise sunucunun bildirdigi model id kullanilir (Qwen3-4B-Q4_K_M.gguf).
        - Degilse ATLAS_AI_MODEL'in gercek degeri, o da yoksa GGUF dosya adina
          duser. OpenAI default'una ('gpt-4o-mini') ASLA dusmez.
        """
        if status and str(status.get("status") or "").upper() == "ONLINE":
            try:
                import requests

                response = requests.get(f"{base_url}/models", timeout=3.0)
                if response.status_code == 200:
                    payload = response.json()
                    models = payload.get("data") or []
                    if models and isinstance(models[0], dict):
                        model_id = str(models[0].get("id") or "").strip()
                        if model_id:
                            return model_id
            except Exception:
                pass

        configured = str(getattr(Config, "AI_MODEL", "") or "").strip()
        if configured and configured != "gpt-4o-mini":
            return configured
        model_file = str(getattr(Config, "AI_LOCAL_MODEL_FILE", "") or "").strip()
        basename = model_file.rsplit("/", 1)[-1]
        if basename and basename != model_file:
            return basename
        return "Qwen3-4B-Q4_K_M.gguf"

    def _tool_specs(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "analyze_symbol",
                    "description": "Belirli sembol icin AtlasEngine analizini calistirir ve sonucu doner.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                        },
                        "required": ["symbol"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_signal",
                    "description": "Son aktif/current sinyali getirir.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_learning_panel",
                    "description": "Learning panel ozetini getirir.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_manual_trades",
                    "description": "Manuel trade listesi getirir.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer"},
                            "status": {"type": "string"},
                            "symbol": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_signal_outcomes",
                    "description": "Signal outcome listesi getirir.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer"},
                            "status": {"type": "string"},
                            "symbol": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_learning_records",
                    "description": "Learning kayitlarini getirir.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "symbol": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_setup_statistics",
                    "description": "Setup bazli performans ozetini getirir.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "open_manual_trade",
                    "description": "Bir sinyal icin manuel OPEN kaydi acar.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "signal_id": {"type": "string"},
                            "actual_entry": {"type": "number"},
                            "position_size": {"type": "number"},
                        },
                        "required": ["signal_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_open_manual_trades",
                    "description": "Acik manuel trade listesini getirir.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mark_not_traded",
                    "description": "Sinyali NOT_TRADED olarak isaretler.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "signal_id": {"type": "string"},
                        },
                        "required": ["signal_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "close_manual_trade",
                    "description": "Acilmis manuel trade'i kapatir (TP/SL/EARLY_EXIT).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "signal_id": {"type": "string"},
                            "result": {"type": "string"},
                            "actual_exit": {"type": "number"},
                        },
                        "required": ["signal_id", "result"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "prepare_ui_action",
                    "description": "TUI'nin popup acmasi icin structured action doner.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action_type": {"type": "string"},
                            "result": {"type": "string"},
                            "message": {"type": "string"},
                        },
                        "required": ["action_type", "message"],
                    },
                },
            },
        ]

    def _dispatch_tool(self, name, payload):
        if name == "analyze_symbol":
            return self._tool_analyze_symbol(payload)
        if name == "get_current_signal":
            return self.runtime.current_signal() or {}
        if name == "get_learning_panel":
            return self.runtime.learning_panel() or {}
        if name == "get_manual_trades":
            limit = int(payload.get("limit") or 30)
            status = payload.get("status")
            symbol = payload.get("symbol")
            return self.runtime.manual_trades(limit=limit, status=status, symbol=symbol)
        if name == "get_signal_outcomes":
            limit = int(payload.get("limit") or 30)
            status = payload.get("status")
            symbol = payload.get("symbol")
            return self.runtime.signal_outcomes(limit=limit, status=status, symbol=symbol)
        if name == "get_learning_records":
            source = str(payload.get("source") or "manual")
            symbol = payload.get("symbol")
            limit = int(payload.get("limit") or 100)
            rows = self.runtime.learning_records(source=source, symbol=symbol)
            return rows[:limit]
        if name == "get_setup_statistics":
            return self.runtime.setup_statistics()
        if name == "open_manual_trade":
            signal_id = payload.get("signal_id") or self._default_signal_id()
            actual_entry = payload.get("actual_entry")
            position_size = payload.get("position_size")
            if actual_entry is None:
                return {
                    "code": "missing_actual_entry",
                    "message": "Gercek giris fiyati gerekli. UI popup icin prepare_ui_action kullan.",
                }
            trade, code = self.runtime.manual_service.open_trade(
                signal_id=signal_id,
                actual_entry=actual_entry,
                position_size=position_size,
            )
            return {"code": code, "trade": trade}
        if name == "get_open_manual_trades":
            symbol = payload.get("symbol")
            return list(self.runtime.open_manual_trades(symbol=symbol))
        if name == "mark_not_traded":
            signal_id = payload.get("signal_id") or self._default_signal_id()
            trade, code = self.runtime.manual_service.mark_not_traded(signal_id=signal_id)
            return {"code": code, "trade": trade}
        if name == "close_manual_trade":
            signal_id = payload.get("signal_id") or self._default_open_signal_id()
            result = payload.get("result")
            actual_exit = payload.get("actual_exit")
            if actual_exit is None:
                return {
                    "code": "missing_actual_exit",
                    "message": "Cikis fiyati gerekli. UI popup icin prepare_ui_action kullan.",
                }
            trade, code = self.runtime.manual_service.close_trade(
                signal_id=signal_id,
                result=result,
                actual_exit=actual_exit,
            )
            return {"code": code, "trade": trade}
        if name == "prepare_ui_action":
            return {
                "ui_action": {
                    "type": payload.get("action_type"),
                    "result": payload.get("result"),
                    "label": payload.get("result") or payload.get("action_type") or "",
                },
                "message": payload.get("message") or "",
            }
        return {"error": f"unknown_tool:{name}"}

    def _default_signal_id(self):
        current = self.runtime.current_signal() or {}
        signal_id = current.get("signal_id")
        if signal_id:
            return signal_id
        return None

    def _default_open_signal_id(self):
        open_rows = self.runtime.open_manual_trades() or []
        if open_rows:
            return open_rows[0].get("signal_id")
        return self._default_signal_id()

    def _tool_analyze_symbol(self, payload):
        symbol = payload.get("symbol")
        analyzed = self.runtime.analyze_symbol(symbol, force_refresh=True)
        if not analyzed.get("ok"):
            return analyzed
        result = analyzed.get("result") or {}
        signal = result.get("signal") or {}
        risk = result.get("risk") or {}
        analysis = result.get("analysis") or {}
        decision = result.get("decision") or {}
        setup_quality = analysis.get("setup_quality") or {}
        return {
            "ok": True,
            "symbol": analyzed.get("symbol"),
            "signal": {
                "signal": signal.get("signal"),
                "confidence": signal.get("confidence"),
                "grade": signal.get("grade"),
                "reason": signal.get("signal_reason") or signal.get("wait_reason"),
            },
            "risk": {
                "entry": risk.get("entry"),
                "stop_loss": risk.get("stop_loss"),
                "tp1": risk.get("tp1"),
                "tp2": risk.get("tp2"),
                "tp3": risk.get("tp3"),
                "rr": risk.get("selected_rr") if risk.get("selected_rr") is not None else risk.get("rr"),
            },
            "market_phase": analysis.get("market_phase") or {},
            "confluence": analysis.get("confluence") or {},
            "setup_quality": {
                "score": setup_quality.get("score"),
                "setup_fingerprint": setup_quality.get("setup_fingerprint"),
                "learning": setup_quality.get("learning") or {},
            },
            "decision": decision,
            "signal_id": self._resolve_signal_id(analyzed.get("symbol"), signal.get("signal")),
        }

    def _resolve_signal_id(self, symbol, direction):
        try:
            return self.runtime.manual_service.resolve_signal_id(symbol=symbol, direction=direction)
        except Exception:
            return None

    def _assistant_message_for_tools(self, message, tool_calls):
        out = {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": [],
        }
        for item in tool_calls:
            out["tool_calls"].append(
                {
                    "id": item.get("id"),
                    "type": "function",
                    "function": {
                        "name": ((item.get("function") or {}).get("name") or ""),
                        "arguments": ((item.get("function") or {}).get("arguments") or "{}"),
                    },
                }
            )
        return out

    def _extract_text(self, message):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            return "\n".join(part.strip() for part in parts if part.strip())
        return ""

    def _handle_direct_response(self, *, mode, on_text_delta=None):
        messages = self._request_messages(mode=mode, limit=self._history_limit(mode), include_tools=False)
        max_tokens = self._max_tokens(mode)
        text_parts = []
        streamed = False

        stream = self._client_stream_completion(messages=messages, max_tokens=max_tokens)
        if stream is not None:
            for event in stream:
                chunk = self._extract_stream_text(event)
                if not chunk:
                    continue
                streamed = True
                text_parts.append(chunk)
                if callable(on_text_delta):
                    on_text_delta(chunk)

        if not text_parts:
            response = self._client_create_completion(messages=messages, max_tokens=max_tokens)
            message = response.get("message") or {}
            content = self._extract_text(message)
            if content:
                text_parts.append(content)
                if callable(on_text_delta) and not streamed:
                    on_text_delta(content)

        content = "".join(text_parts).strip()
        if not content:
            content = "Su an anlamli bir cevap uretemedim."
        self._messages.append({"role": "assistant", "content": content})
        return AgentResult(text=content)

    def _request_mode(self, text):
        lowered = str(text or "").strip().lower()
        if self._needs_tooling(lowered):
            return "tool"
        word_count = len(re.findall(r"\S+", lowered))
        if len(lowered) <= 80 and word_count <= 12:
            return "simple"
        return "chat"

    def _needs_tooling(self, lowered):
        markers = (
            "analiz",
            "incele",
            "sinyal",
            "trade",
            "islem",
            "işlem",
            "emir",
            "girdim",
            "girmedim",
            "manual",
            "learning",
            "istatistik",
            "setup",
            "panel",
            "journal",
            "kaybediyor",
            "pozisyon",
            "kapat",
            "close",
            "open",
            "goster",
            "göster",
        )
        if any(marker in lowered for marker in markers):
            return True
        return re.search(r"\b(tp|sl|rr)\b", lowered) is not None

    def _request_messages(self, *, mode, limit, include_tools):
        history = []
        for item in self._messages[1:]:
            role = item.get("role")
            if not include_tools:
                if role == "tool":
                    continue
                if role == "assistant" and item.get("tool_calls"):
                    continue
            history.append(item)
        if limit > 0:
            history = history[-limit:]
        system_prompt = SYSTEM_PROMPT if mode == "tool" else DIRECT_CHAT_SYSTEM_PROMPT
        return [{"role": "system", "content": system_prompt}, *history]

    def _history_limit(self, mode):
        if mode == "tool":
            return max(2, int(getattr(Config, "AI_CHAT_TOOL_HISTORY_MESSAGES", 8) or 8))
        if mode == "simple":
            return max(1, int(getattr(Config, "AI_CHAT_SIMPLE_HISTORY_MESSAGES", 1) or 1))
        return max(2, int(getattr(Config, "AI_CHAT_DEFAULT_HISTORY_MESSAGES", 4) or 4))

    def _max_tokens(self, mode):
        if mode == "tool":
            return max(32, int(getattr(Config, "AI_CHAT_TOOL_MAX_TOKENS", 160) or 160))
        if mode == "simple":
            return max(16, int(getattr(Config, "AI_CHAT_SIMPLE_MAX_TOKENS", 32) or 32))
        return max(32, int(getattr(Config, "AI_CHAT_DEFAULT_MAX_TOKENS", 128) or 128))

    def _client_create_completion(self, *, messages, tools=None, tool_choice="auto", max_tokens=None):
        kwargs = {
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        try:
            return self._client.create_completion(**kwargs)
        except TypeError:
            kwargs.pop("max_tokens", None)
            return self._client.create_completion(**kwargs)

    def _client_stream_completion(self, *, messages, max_tokens=None):
        streamer = getattr(self._client, "stream_completion", None)
        if streamer is None:
            return None
        kwargs = {"messages": messages}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        try:
            return streamer(**kwargs)
        except TypeError:
            kwargs.pop("max_tokens", None)
            return streamer(**kwargs)

    def _extract_stream_text(self, event):
        if not isinstance(event, dict):
            return ""
        choices = event.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or choices[0].get("message") or {}
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            return "".join(parts)
        return ""

    def _safe_json_loads(self, text):
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _extract_structured_action(self, content):
        text = str(content or "").strip()
        if not text.startswith("{"):
            return None
        parsed = self._safe_json_loads(text)
        if not parsed:
            return None
        if "message" in parsed and "action" in parsed:
            return parsed
        return None
