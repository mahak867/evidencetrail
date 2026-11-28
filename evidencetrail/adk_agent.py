"""EvidenceTrail on Google's Agent Development Kit (ADK).

The same investigation as investigator.py, but the agent loop is run by ADK: an
LlmAgent backed by Gemini (via ADK's LiteLlm connector to the Gemini API's
OpenAI-compatible endpoint) with EvidenceTrail's read-only telemetry tools and a
`submit_diagnosis` tool. The evidence gate and the safety policy are unchanged:
ADK proposes, EvidenceTrail verifies.

Select it with ENGINE=adk (or Investigation(engine="adk")).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from .gemini import BASE, FALLBACKS, MODEL, PASS_WAIT_S

# ADK logs a cancellation when we stop the run right after submit_diagnosis; that is expected.
for _name in ("google_adk", "google.adk", "LiteLLM", "litellm"):
    logging.getLogger(_name).setLevel(logging.ERROR)

INSTRUCTION = None  # filled from investigator.SYSTEM at runtime to keep one source of truth


def run_adk(inv, context: dict) -> tuple[dict | None, str | None]:
    """Runs the ADK agent for an Investigation `inv`. Returns (diagnosis, error)."""
    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from .investigator import FAULT_TYPES, SYSTEM

    result: dict = {}

    def _tool(name: str, args: dict) -> dict:
        res = inv._run_tool(name, args)
        from .investigator import _ids
        inv._log({"step": "tool", "tool": name, "args": args, "evidence_ids": _ids(res), "engine": "adk"})
        return res

    # Read-only tools exposed to the ADK agent. Docstrings become the tool descriptions.
    def get_logs(service: str, level: str = "ERROR", contains: str = "") -> dict:
        """Grouped log lines for a service in the incident window. level is ERROR, WARN or INFO."""
        return _tool("get_logs", {"service": service, "level": level, "contains": contains or None})

    def get_metric(service: str, name: str) -> dict:
        """Time series for one metric of a service: error_ratio, p95_latency_ms, request_rate, heap_mb,
        db_pool_in_use, config_version, dependency_errors or up."""
        return _tool("get_metric", {"service": service, "name": name})
    # ADK builds the tool description from the docstring: list the metrics of the configured target
    get_metric.__doc__ = "Time series for one metric of a service: " + ", ".join(inv.tel.METRIC_NAMES) + "."

    def get_error_traces(service: str) -> dict:
        """Failing traces through a service, reduced to the chain of failing spans."""
        return _tool("get_error_traces", {"service": service})

    def get_slow_traces(service: str) -> dict:
        """Slowest traces through a service with self-time per service."""
        return _tool("get_slow_traces", {"service": service})

    def get_recent_changes() -> dict:
        """Deployments and configuration changes in the last 15 minutes."""
        return _tool("get_recent_changes", {})

    def submit_diagnosis(root_cause_service: str, fault_type: str, summary: str, confidence: float,
                         claims: list[dict], ranked_candidates: list[str],
                         rejected_hypotheses: list[dict] | None = None, suggested_action: dict | None = None) -> dict:
        """Submit the final diagnosis. claims: [{text, evidence_ids:[...], quote, is_root_cause_claim}].
        fault_type is one of the allowed types. suggested_action: {action, service, why}."""
        result.update(root_cause_service=root_cause_service, fault_type=fault_type, summary=summary,
                      confidence=confidence, claims=claims, ranked_candidates=ranked_candidates,
                      rejected_hypotheses=rejected_hypotheses or [], suggested_action=suggested_action)
        return {"status": "received; the evidence gate will now verify every claim"}

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, "GEMINI_API_KEY is not set"
    chain = [inv.llm.model or MODEL] + [m for m in FALLBACKS if m != (inv.llm.model or MODEL)]
    # same policy as the native client: try every model, then wait and try the whole chain once more
    models = chain + chain
    last_err = None
    for i, model in enumerate(models):
        if i == len(chain):
            inv.llm.usage.retries += 1
            inv.llm.usage.wait_s += PASS_WAIT_S
            time.sleep(PASS_WAIT_S)
        result.clear()
        agent = LlmAgent(
            name="evidencetrail_investigator",
            model=LiteLlm(model=f"openai/{model}", api_base=BASE, api_key=key),
            instruction=SYSTEM + f"\nAllowed fault types: {', '.join(FAULT_TYPES)}. Finish by calling submit_diagnosis exactly once.",
            tools=[get_logs, get_metric, get_error_traces, get_slow_traces, get_recent_changes, submit_diagnosis],
        )

        async def go():
            ss = InMemorySessionService()
            sid = uuid.uuid4().hex
            await ss.create_session(app_name="evidencetrail", user_id="oncall", session_id=sid)
            runner = Runner(agent=agent, app_name="evidencetrail", session_service=ss)
            msg = types.Content(role="user", parts=[types.Part(text=json.dumps(context))])
            async for ev in runner.run_async(user_id="oncall", session_id=sid, new_message=msg):
                um = getattr(ev, "usage_metadata", None)
                if um:
                    inv.llm.usage.calls += 1
                    inv.llm.usage.prompt_tokens += um.prompt_token_count or 0
                    inv.llm.usage.completion_tokens += um.candidates_token_count or 0
                    inv.trail.append({"step": "llm", "t": round(time.time() - inv._t0, 2), "dur": 0, "engine": "adk",
                                      "tokens": (um.prompt_token_count or 0) + (um.candidates_token_count or 0), "model": model,
                                      "requested": [p.function_call.name for p in (ev.content.parts if ev.content else []) or [] if p.function_call]})
                if result:
                    break

        try:
            asyncio.run(go())
            if model not in inv.llm.used_models:
                inv.llm.used_models.append(model)
            if result:
                return dict(result), None
            last_err = f"ADK agent on {model} finished without submit_diagnosis"
        except Exception as e:  # overload / quota errors from the provider: try the next model
            last_err = f"{type(e).__name__}: {str(e)[:300]}"
            inv.llm.usage.failures += 1
            if not any(x in str(e) for x in ("503", "429", "high demand", "quota", "RateLimit", "ServiceUnavailable")):
                break
    return None, last_err
