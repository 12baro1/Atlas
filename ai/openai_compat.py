"""OpenAI-compatible chat client with tool-calling support."""

from __future__ import annotations

import json
from dataclasses import dataclass

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

    def create_completion(self, *, messages, tools=None, tool_choice="auto"):
        url = self._endpoint("/chat/completions")
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        headers = {
            "Content-Type": "application/json",
        }
        if str(self.config.api_key or "").strip():
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload),
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

    def _endpoint(self, suffix):
        base = (self.config.base_url or "").rstrip("/")
        if base.endswith("/v1"):
            return f"{base}{suffix}"
        return f"{base}/v1{suffix}"
