"""
LLMClient — transport port for performer-name extraction.

Thin adapter: owns only HTTP transport + model config. Prompt
strategy (two-prompt fallback, hinted extraction) stays in the
caller (see resolve_nonames_cli.py). Two impls justify the seam:

  - UniInferLLMClient  production, hits the UniInfer proxy
  - FakeLLMClient       tests, returns canned completions

The proxy is HTTPS behind nginx with a self-signed cert, so transport
uses verify=False (equivalent to the old ssl context hack).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

try:
    import requests
    import urllib3
    urllib3.disable_warnings()
    _HAVE_REQUESTS = True
except ImportError:  # pragma: no cover
    _HAVE_REQUESTS = False


DEFAULT_API_URL = "https://amd1.mooo.com:8123/v1/chat/completions"
DEFAULT_API_KEY = "test23@test34"
DEFAULT_MODEL = "opencode@deepseek-v4-flash-free"


class LLMClient(ABC):
    """Interface for one-shot chat completion."""

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 32,
        think: bool = False,
    ) -> str:
        """
        Send messages, return the assistant's text content (stripped).

        Returns "" on transport failure (never raises).
        """


class UniInferLLMClient(LLMClient):
    """Production client for the UniInfer proxy."""

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        api_key: str = DEFAULT_API_KEY,
        model: str = DEFAULT_MODEL,
    ):
        if not _HAVE_REQUESTS:  # pragma: no cover
            raise RuntimeError("requests is required for UniInferLLMClient")
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 32,
        think: bool = False,
    ) -> str:
        payload = json.dumps({
            "model": model or self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "think": think,
        }).encode()

        try:
            resp = requests.post(
                self.api_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                verify=False,
                timeout=60,
            )
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "") or ""
            return content.strip()
        except Exception:
            return ""


class FakeLLMClient(LLMClient):
    """Test double. Returns queued responses, or a fixed string."""

    def __init__(self, responses: Optional[List[str]] = None, fixed: str = ""):
        self._queue: List[str] = list(responses or [])
        self.fixed = fixed
        self.calls: List[Dict] = []

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 32,
        think: bool = False,
    ) -> str:
        self.calls.append({
            "messages": messages,
            "model": model,
            "max_tokens": max_tokens,
            "think": think,
        })
        if self._queue:
            return self._queue.pop(0).strip()
        return self.fixed.strip()
