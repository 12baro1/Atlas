"""OpenAI-compatible chat client with tool-calling support."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator

import requests


@dataclass
class OpenAICompatConfig:
    base_url: str
    model: str
    api_key: str = ""
    timeout_seconds: float = 30.0
    temperature: float = 0.2


class OpenAICompatClient:
    """Minimal chat completions client for OpenAI-compatible providers."""

    def __init__(self, config: OpenAICompatConfig):
        self.config = config

    def create_completion(self, *, messages, tools=None, tool_choice="auto", max_tokens=None):
        url = self._endpoint("/chat/completions")
        payload = self._payload(messages=messages, tools=tools, tool_choice=tool_choice, max_tokens=max_tokens)
        response = requests.post(
            url,
            headers=self._headers(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("AI provider returned no choices")
        message = choices[0].get("message") or {}
        return {
            "message": message,
            "usage": data.get("usage") or {},
            "raw": data,
        }

    def stream_completion(self, *, messages, tools=None, tool_choice="auto", max_tokens=None) -> Iterator[dict]:
        url = self._endpoint("/chat/completions")
        payload = self._payload(messages=messages, tools=tools, tool_choice=tool_choice, max_tokens=max_tokens)
        payload["stream"] = True

        with requests.post(
            url,
            headers=self._headers(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=self.config.timeout_seconds,
            stream=True,
        ) as response:
            response.encoding = "utf-8"
            response.raise_for_status()
            for raw in response.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data: "):
                    continue
                data = raw[6:]
                if data == "[DONE]":
                    break
                yield json.loads(data)

    def _payload(self, *, messages, tools=None, tool_choice="auto", max_tokens=None):
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if max_tokens is not None and int(max_tokens) > 0:
            payload["max_tokens"] = int(max_tokens)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        return payload

    def _headers(self):
        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }
        if str(self.config.api_key or "").strip():
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _endpoint(self, suffix):
        base = (self.config.base_url or "").rstrip("/")
        if base.endswith("/v1"):
            return f"{base}{suffix}"
        return f"{base}/v1{suffix}"
