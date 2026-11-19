"""Baselines evaluated on the same faults, telemetry and window as EvidenceTrail.

B0  single-prompt Gemini: the alert plus a tail of raw logs from every service, one call,
    no tools, no topology. This is "paste logs into a chat model".
B1  dashboard rule: blame the service whose error ratio rose most; if no error change,
    the service whose p95 latency rose most. This is what a dashboard-driven triage does.
"""
from __future__ import annotations

import json
import re
import time

from .gemini import Gemini, GeminiUnavailable
from .investigator import FAULT_TYPES
from .telemetry import Telemetry, Window


def b1_dashboard_rule(window_s: int = 120) -> dict:
    t0 = time.time()
    tel = Telemetry(window=Window.last(window_s))
    h = tel.service_health()

    def err_jump(s):
        return h[s]["error_ratio"] - h[s]["baseline_error_ratio"]

    def lat_jump(s):
        p, b = h[s].get("p95_ms") or 0, h[s].get("baseline_p95_ms") or 1
        return p / max(b, 1)

    ranked = sorted(h, key=lambda s: (-round(err_jump(s), 2), -lat_jump(s)))
    if not any(err_jump(s) > 0.05 for s in h):
        ranked = sorted(h, key=lambda s: -lat_jump(s))
    return {"method": "B1_dashboard_rule", "root_cause_service": ranked[0] if ranked else None, "fault_type": None,
            "ranked_candidates": ranked[:3], "verdict": "DIAGNOSIS", "elapsed_s": round(time.time() - t0, 1),
            "usage": {"total_tokens": 0, "calls": 0}}


B0_PROMPT = """You are helping an on-call engineer. An alert fired: {alert}
Below are recent log lines from all services of a microservices shop.
Identify the root-cause service and the fault type (one of: {types}).
Reply ONLY with JSON: {{"root_cause_service": str, "fault_type": str, "ranked_candidates": [3 services], "summary": str}}

LOGS:
{logs}"""


def b0_single_prompt(alert: str, window_s: int = 120, max_lines: int = 400) -> dict:
    t0 = time.time()
    tel = Telemetry(window=Window.last(window_s))
    llm = Gemini()
    prompt = B0_PROMPT.format(alert=alert, types=", ".join(FAULT_TYPES), logs=tel.all_log_lines(max_lines))
    try:
        m = llm.chat([{"role": "user", "content": prompt}])
        txt = m.get("content") or ""
        js = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        verdict = "DIAGNOSIS"
    except GeminiUnavailable as e:
        js, verdict = {"error": str(e)}, "FAILED"
    except (AttributeError, json.JSONDecodeError):
        js, verdict = {"error": "unparseable model output"}, "FAILED"
    return {"method": "B0_single_prompt", "root_cause_service": js.get("root_cause_service"),
            "fault_type": js.get("fault_type"), "ranked_candidates": js.get("ranked_candidates") or [],
            "summary": js.get("summary"), "verdict": verdict, "elapsed_s": round(time.time() - t0, 1),
            "usage": llm.usage.as_dict(), "model": ",".join(llm.used_models), "prompt_chars": len(prompt),
            "error": js.get("error")}
