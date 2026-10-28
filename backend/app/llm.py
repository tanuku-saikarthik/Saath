"""Minimal OpenAI-compatible chat client.

Sarvam's docs show the key passed as `api_subscription_key` in their SDK and don't name the HTTP
header for chat, so we send both `Authorization: Bearer` and `api-subscription-key`. Any other
OpenAI-compatible provider ignores the extra header.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import settings


class LLMError(RuntimeError):
    pass


def chat(messages: list[dict[str, str]], *, max_tokens: int = 6000, temperature: float = 0.2, json_mode: bool = False) -> str:
    if not settings.llm_enabled:
        raise LLMError("No LLM configured: set LLM_API_KEY (or SARVAM_API_KEY), or point LLM_BASE_URL at a local server")
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
        if "sarvam" in settings.LLM_BASE_URL:
            headers["api-subscription-key"] = settings.LLM_API_KEY
    body: dict[str, Any] = {"model": settings.LLM_MODEL, "messages": messages}
    if "api.openai.com" in settings.LLM_BASE_URL:
        # OpenAI's reasoning models (GPT-5.x) take max_completion_tokens and only the default temperature.
        body["max_completion_tokens"] = max_tokens
    else:
        body["max_tokens"] = max_tokens
        body["temperature"] = temperature
    if json_mode and settings.LLM_JSON_MODE:
        body["response_format"] = {"type": "json_object"}  # OpenAI, Groq, Ollama support this
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        return _post(url, headers, body)
    except httpx.HTTPError as exc:  # network down, timeout: keep the call, fall back upstream
        raise LLMError(f"LLM unreachable: {exc}") from exc


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> str:
    with httpx.Client(timeout=180) as client:
        resp = client.post(url, headers=headers, json=body)
        # A provider that rejects one of these fields names one per error: adapt and retry, up to 3 times.
        for _ in range(3):
            if resp.status_code != 400:
                break
            err = resp.text.lower()
            changed = False
            if "max_tokens" in err and "max_tokens" in body:
                body["max_completion_tokens"] = body.pop("max_tokens")
                changed = True
            if "temperature" in err and "temperature" in body:
                body.pop("temperature")
                changed = True
            if "response_format" in err and "response_format" in body:
                body.pop("response_format")
                changed = True
            if not changed:
                break
            resp = client.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected LLM response: {str(data)[:500]}") from exc


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (handles code fences and stray prose)."""
    text = text.strip()
    # Drop any <think>...</think> reasoning a model may emit.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise LLMError("No JSON object in reply")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise LLMError("Unterminated JSON object in reply")


def chat_json(messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
    """Ask for JSON; on a parse failure, retry once with the bad reply and a correction."""
    kwargs.setdefault("json_mode", True)
    reply = chat(messages, **kwargs)
    try:
        return extract_json(reply)
    except (LLMError, json.JSONDecodeError) as first_err:
        retry = messages + [
            {"role": "assistant", "content": reply[:6000]},
            {
                "role": "user",
                "content": f"That was not valid JSON ({first_err}). Reply again with ONLY the JSON object, no prose.",
            },
        ]
        return extract_json(chat(retry, **kwargs))
