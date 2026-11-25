"""Minimal Gemini client (OpenAI-compatible endpoint of the Gemini API).

Handles HTTP 429 / 5xx with bounded exponential backoff and records token usage.
The key is read from GEMINI_API_KEY and kept server-side.
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field

import httpx

BASE = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
# Tried in order when the primary model is overloaded (HTTP 503) or retired (404).
# Lower reasoning effort cuts latency a lot on thinking models; "none" disables the parameter.
REASONING = os.environ.get("GEMINI_REASONING", "none")
FALLBACKS = [m for m in os.environ.get("GEMINI_FALLBACKS", "gemini-3-flash-preview,gemini-3.5-flash,gemini-flash-latest,gemini-flash-lite-latest").split(",") if m]


PASSES = max(1, int(os.environ.get("GEMINI_PASSES", "2")))
PASS_WAIT_S = float(os.environ.get("GEMINI_PASS_WAIT_S", "30"))


class GeminiUnavailable(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    failures: int = 0
    wait_s: float = 0.0  # time lost to back-off and failed/overloaded calls (provider-side)

    def as_dict(self):
        return dict(vars(self), wait_s=round(self.wait_s, 1), total_tokens=self.prompt_tokens + self.completion_tokens)


@dataclass
class Gemini:
    model: str = MODEL
    usage: Usage = field(default_factory=Usage)
    max_retries: int = 3
    used_models: list = field(default_factory=list)

    def chat(self, messages, tools=None, tool_choice=None, temperature: float = 0.1) -> dict:
        last = None
        for attempt in range(PASSES):
            if attempt:
                # Every model was overloaded: wait, then try the whole chain once more.
                self.usage.retries += 1
                self.usage.wait_s += PASS_WAIT_S
                time.sleep(PASS_WAIT_S)
            for m in [self.model] + [f for f in FALLBACKS if f != self.model]:
                try:
                    out = self._chat(m, messages, tools, tool_choice, temperature)
                    if m not in self.used_models:
                        self.used_models.append(m)
                    return out
                except GeminiUnavailable as e:
                    last = e
                    if "HTTP 4" in str(e) and "429" not in str(e):
                        break  # a request error will not fix itself by retrying
        raise last

    def _chat(self, model: str, messages: list[dict], tools: list[dict] | None = None, tool_choice=None, temperature: float = 0.1) -> dict:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise GeminiUnavailable("GEMINI_API_KEY is not set")
        body = {"model": model, "messages": messages, "temperature": temperature}
        if REASONING != "none":
            body["reasoning_effort"] = REASONING
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        delay = 2.0
        tries = 0
        for attempt in range(self.max_retries + 1):
            tries += 1
            t_call = time.time()
            try:
                r = httpx.post(f"{BASE}/chat/completions", json=body, timeout=120,
                               headers={"Authorization": f"Bearer {key}"})
            except httpx.HTTPError as e:
                status, err = None, str(e)
                self.usage.wait_s += time.time() - t_call
            else:
                if r.status_code == 200:
                    data = r.json()
                    u = data.get("usage") or {}
                    self.usage.calls += 1
                    self.usage.prompt_tokens += u.get("prompt_tokens", 0)
                    self.usage.completion_tokens += u.get("completion_tokens", 0)
                    return data["choices"][0]["message"]
                status, err = r.status_code, r.text[:300]
                self.usage.wait_s += time.time() - t_call
                if (status == 503 and "high demand" in err) or (status == 429 and "per day" in r.text):
                    break  # overloaded: move to the next model now
                if status not in (429, 500, 502, 503, 504):
                    self.usage.failures += 1
                    raise GeminiUnavailable(f"Gemini HTTP {status}: {err}")
            if attempt == self.max_retries:
                break
            self.usage.retries += 1
            pause = delay + random.uniform(0, 1)
            self.usage.wait_s += pause
            time.sleep(pause)
            delay = min(delay * 2, 40)
        self.usage.failures += 1
        raise GeminiUnavailable(f"Gemini {model} unavailable after {tries} attempt(s) (last: {status} {err})")


def parse_args(call: dict) -> dict:
    try:
        return json.loads(call["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        return {}
