"""HTTP client for local Ollama (optional; analysis model from environment)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import requests


def ollama_host() -> str:
    return (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")


def analysis_model_name() -> str:
    """
    Model tag for JSON tasks (why / summarize). Must be a model you have pulled in Ollama.

    Set ``ARROW_ANALYSIS_MODEL`` or legacy ``ARROW_OLLAMA_MODEL``. If unset, returns ``""``
    (callers should use deterministic-only paths or prompt to configure).
    """
    for key in ("ARROW_ANALYSIS_MODEL", "ARROW_OLLAMA_MODEL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return ""


def optional_rank_chat_model_name() -> str:
    """Optional separate tag for future chat-style features; same env pattern as analysis."""
    return (os.environ.get("ARROW_CHAT_MODEL") or "").strip()


def ollama_tags(host: Optional[str] = None, timeout: float = 10.0) -> Dict[str, Any]:
    h = host or ollama_host()
    r = requests.get(f"{h}/api/tags", timeout=timeout)
    r.raise_for_status()
    return r.json()


def ollama_chat(
    *,
    model: str,
    user: str,
    system: Optional[str] = None,
    format_json: bool = True,
    host: Optional[str] = None,
    timeout: float = 180.0,
) -> str:
    h = host or ollama_host()
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if format_json:
        payload["format"] = "json"
    r = requests.post(f"{h}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    msg = data.get("message") or {}
    return str(msg.get("content") or "")


def extract_json_object(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        if "```" in t:
            t = t[: t.rindex("```")]
    return t.strip()
