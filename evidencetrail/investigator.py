"""EvidenceTrail investigator: topology-guided, hypothesis-testing Gemini agent
whose conclusions must pass the evidence gate.

Pipeline
  1. Health scan (Prometheus): which services are anomalous vs a baseline window.
  2. Dependency graph (Jaeger): walk upstream-to-downstream to find the deepest
     anomalous services. Those are the suspects; their callers are mostly victims.
  3. Gemini agent loop: propose hypotheses, call read-only tools to confirm or
     reject each one, then submit a structured diagnosis citing evidence IDs.
  4. Evidence gate: drop claims citing evidence that was never fetched or quotes
     that are not in the evidence. If the root-cause claim does not survive, or
     confidence is low, the verdict is INCONCLUSIVE instead of a guess.
  5. Suggested action labelled by policy (safe / risky / blocked); dry run only.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from . import safety
from .evidence import gate
from .gemini import Gemini, GeminiUnavailable, parse_args
from .telemetry import Telemetry, Window

FAULT_TYPES = ["crash_or_unreachable", "latency", "resource_exhaustion", "bad_config", "bad_deploy", "code_error"]

SYSTEM = f"""You are EvidenceTrail, an incident investigator helping an on-call SRE.
A microservices shop is having an incident. Find the ROOT-CAUSE service and fault type.

Rules:
- Errors propagate UPSTREAM: callers of a failing service also show errors. The root cause is
  usually the deepest anomalous service in the call graph whose own dependencies are healthy.
- Work by hypotheses: state 2-3 candidate causes, then call tools to confirm or reject each.
  Check recent changes (deploys/config) before concluding.
- Every claim must cite evidence_ids returned by tools in THIS investigation, and include a short
  exact quote copied from that evidence. Never invent IDs. If evidence is insufficient, lower
  confidence; the system will report INCONCLUSIVE rather than guess.
- fault_type must be one of: {", ".join(FAULT_TYPES)}.
  crash_or_unreachable = service down / connection refused; resource_exhaustion = memory leak,
  GC pressure, connection-pool or CPU exhaustion; bad_config = invalid config change;
  bad_deploy = errors that start right after a new deployment; code_error = application exceptions
  with no related change; latency = slowness without resource exhaustion.
- You may suggest ONE remediation; a human must approve it. Allowed actions:
  {", ".join(safety.POLICY)}.
- Be efficient: request several tools in ONE turn if needed; at most 2 turns before submit_diagnosis."""


def _tool(name, desc, props, required=()):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": list(required)}}}


SVC = {"type": "string", "description": "service name"}
TOOLS = [
    _tool("get_logs", "Grouped log lines for a service in the incident window (most frequent first).",
          {"service": SVC, "level": {"type": "string", "enum": ["ERROR", "WARN", "INFO"]},
           "contains": {"type": "string"}}, ["service"]),
    _tool("get_metric", "Time series for one metric of a service across the incident window.",
          {"service": SVC, "name": {"type": "string", "enum": ["error_ratio", "p95_latency_ms", "request_rate", "heap_mb",
                                                               "db_pool_in_use", "config_version", "dependency_errors", "up"]}},
          ["service", "name"]),
    _tool("get_error_traces", "Failing traces through a service, reduced to the chain of failing spans.", {"service": SVC}, ["service"]),
    _tool("get_slow_traces", "Slowest traces through a service with self-time per service.", {"service": SVC}, ["service"]),
    _tool("get_recent_changes", "Deployments and configuration changes in the last 15 minutes.", {}),
    _tool("submit_diagnosis", "Submit the final diagnosis.", {
        "root_cause_service": SVC,
        "fault_type": {"type": "string", "enum": FAULT_TYPES},
        "summary": {"type": "string", "description": "2-3 sentence plain-language explanation for the on-call engineer"},
        "confidence": {"type": "number", "description": "0..1"},
        "ranked_candidates": {"type": "array", "items": {"type": "string"}, "description": "top 3 services, most likely first"},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "quote": {"type": "string"}, "is_root_cause_claim": {"type": "boolean"}},
            "required": ["text", "evidence_ids"]}},
        "rejected_hypotheses": {"type": "array", "items": {"type": "object", "properties": {
            "hypothesis": {"type": "string"}, "why_rejected": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}}}}},
        "suggested_action": {"type": "object", "properties": {
            "action": {"type": "string", "enum": list(safety.POLICY)}, "service": SVC, "why": {"type": "string"}}},
    }, ["root_cause_service", "fault_type", "summary", "confidence", "claims", "ranked_candidates"]),
]


def suspects(health: dict, edges: list[dict]) -> list[dict]:
    """Deepest-anomaly heuristic over the observed call graph."""
    def anomalous(s):
        h = health.get(s, {})
        err_up = h.get("error_ratio", 0) - h.get("baseline_error_ratio", 0) > 0.05
        p95, b = h.get("p95_ms") or 0, h.get("baseline_p95_ms") or 0
        slow = p95 > max(250, 3 * (b or 50))
        down = s not in health or h.get("rps", 0) == 0
        return err_up or slow or down
    callees: dict[str, set] = {}
    for e in edges:
        callees.setdefault(e["caller"], set()).add(e["callee"])
    all_svcs = set(health) | {e["callee"] for e in edges} | {e["caller"] for e in edges}
    out = []
    for s in sorted(all_svcs):
        if anomalous(s):
            bad_children = [c for c in callees.get(s, ()) if anomalous(c)]
            out.append({"service": s, "anomalous_dependencies": bad_children, "deepest": not bad_children,
                        "health": health.get(s, {"rps": 0, "note": "no metrics: service may be down"})})
    out.sort(key=lambda x: (not x["deepest"], -(x["health"].get("error_ratio") or 0)))
    return out


@dataclass
class Investigation:
    alert: str
    window_s: int = 120
    model: str | None = None
    max_steps: int = 4
    tel: Telemetry = field(init=False)
    llm: Gemini = field(init=False)
    trail: list[dict] = field(default_factory=list)
    stage: str = "queued"  # for live progress in the UI

    def __post_init__(self):
        self.tel = Telemetry(window=Window.last(self.window_s))
        self.llm = Gemini(model=self.model) if self.model else Gemini()

    def _log(self, entry: dict) -> None:
        if "t" not in entry:
            start = getattr(self, "_last_tool_t", time.time())
            entry["t"] = round(start - getattr(self, "_t0", start), 2)
            entry["dur"] = round(time.time() - start, 2)
        self.trail.append(entry)

    def _run_tool(self, name: str, args: dict) -> dict:
        self._last_tool_t = time.time()
        t = self.tel
        try:
            if name == "get_logs":
                return t.logs(args["service"], args.get("level"), args.get("contains"))
            if name == "get_metric":
                return t.metric(args["service"], args["name"])
            if name == "get_error_traces":
                return t.error_traces(args["service"])
            if name == "get_slow_traces":
                return t.slow_traces(args["service"])
            if name == "get_recent_changes":
                return t.changes()
        except Exception as e:  # tool errors are shown to the model, not hidden
            return {"error": f"{type(e).__name__}: {e}"}
        return {"error": f"unknown tool {name}"}

    def run(self) -> dict:
        t0 = time.time()
        self._t0 = t0
        self.stage = "scan"
        health = self.tel.service_health()
        health_id = self.tel.store.add("metric", "service_health_scan", json.dumps(health), meta={"source": "prometheus"})
        self.stage = "graph"
        graph = self.tel.dependency_graph()
        sus = suspects(health, graph["edges"])
        self._log({"step": "scan", "t": 0, "dur": round(time.time() - t0, 2), "health_evidence_id": health_id, "graph_evidence_id": graph["evidence_id"], "suspects": sus})

        # Prefetch the evidence an SRE would open first for the top suspects, so Gemini
        # can usually decide in one or two calls (free-tier friendly, and faster).
        self.stage = "prefetch"
        prefetched = {}
        for sv in [x["service"] for x in sus[:3]]:
            ts = time.time()
            prefetched[sv] = {"logs": self._run_tool("get_logs", {"service": sv, "level": "ERROR"}),
                              "warnings": self._run_tool("get_logs", {"service": sv, "level": "WARN"})}
            self._log({"step": "tool", "tool": "get_logs", "args": {"service": sv, "level": "ERROR+WARN"},
                       "t": round(ts - t0, 2), "dur": round(time.time() - ts, 2),
                               "evidence_ids": _ids(prefetched[sv]["logs"]) + _ids(prefetched[sv]["warnings"])})
        if sus:
            top = sus[0]["service"]
            prefetched[top]["error_traces"] = self._run_tool("get_error_traces", {"service": sus[1]["service"] if len(sus) > 1 else top})
            self._log({"step": "tool", "tool": "get_error_traces", "args": {"service": sus[1]["service"] if len(sus) > 1 else top},
                               "evidence_ids": _ids(prefetched[top]["error_traces"])})
        changes = self._run_tool("get_recent_changes", {})
        self._log({"step": "tool", "tool": "get_recent_changes", "args": {}, "evidence_ids": _ids(changes)})

        msgs = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({
                "alert": self.alert,
                "service_health": {"evidence_id": health_id, "services": health},
                "call_graph": {"evidence_id": graph["evidence_id"], "edges": graph["edges"]},
                "topology_suspects": sus,
                "hint": "topology_suspects lists anomalous services; 'deepest': true means none of its own dependencies look anomalous.",
                "prefetched_evidence": prefetched,
                "recent_changes": changes,
                "instructions": "Evidence for the top suspects is already fetched above. Call more tools ONLY if a hypothesis "
                                "still needs testing (e.g. heap_mb, db_pool_in_use, p95_latency_ms, slow traces); otherwise call submit_diagnosis now.",
            })[:30000]},
        ]
        self.stage = "gemini"
        diagnosis, error = None, None
        try:
            for step in range(self.max_steps):
                force = step == self.max_steps - 1
                c0, tok0 = time.time(), self.llm.usage.prompt_tokens + self.llm.usage.completion_tokens
                m = self.llm.chat(msgs, TOOLS, tool_choice={"type": "function", "function": {"name": "submit_diagnosis"}} if force else "auto")
                self.trail.append({"step": "llm", "t": round(c0 - t0, 2), "dur": round(time.time() - c0, 2),
                                   "tokens": self.llm.usage.prompt_tokens + self.llm.usage.completion_tokens - tok0,
                                   "model": self.llm.used_models[-1] if self.llm.used_models else self.llm.model,
                                   "requested": [c["function"]["name"] for c in (m.get("tool_calls") or [])]})
                calls = m.get("tool_calls") or []
                msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls} if calls else
                            {"role": "assistant", "content": m.get("content") or ""})
                if not calls:
                    msgs.append({"role": "user", "content": "Continue: call tools or submit_diagnosis."})
                    continue
                for c in calls:
                    name, args = c["function"]["name"], parse_args(c)
                    if name == "submit_diagnosis":
                        diagnosis = args
                        break
                    res = self._run_tool(name, args)
                    self._log({"step": "tool", "tool": name, "args": args,
                                       "evidence_ids": _ids(res)})
                    msgs.append({"role": "tool", "tool_call_id": c.get("id", name), "name": name, "content": json.dumps(res)[:6000]})
                if diagnosis:
                    break
        except GeminiUnavailable as e:
            error = str(e)

        self.stage = "gate"
        out = self._finish(diagnosis, error, sus, time.time() - t0)
        out["health"] = health
        out["edges"] = graph["edges"]
        out["suspects"] = sus
        self.stage = "done"
        return out

    def _finish(self, d: dict | None, error: str | None, sus: list[dict], elapsed: float) -> dict:
        base = {"alert": self.alert, "model": ",".join(self.llm.used_models) or self.llm.model, "elapsed_s": round(elapsed, 1),
                "usage": self.llm.usage.as_dict(), "trail": self.trail, "topology_suspects": [s["service"] for s in sus]}
        if not d:
            return {**base, "verdict": "FAILED" if error else "INCONCLUSIVE", "error": error or "no diagnosis submitted",
                    "root_cause_service": None, "fault_type": None, "ranked_candidates": [s["service"] for s in sus][:3]}
        g = gate(d.get("claims", []), self.tel.store)
        rc_ok = any(c.get("is_root_cause_claim") for c in g.kept) or (
            g.kept and not any(c.get("is_root_cause_claim") for c in d.get("claims", [])))
        conf = float(d.get("confidence", 0))
        verdict = "DIAGNOSIS" if (rc_ok and conf >= 0.5) else "INCONCLUSIVE"
        action = safety.classify(d["suggested_action"]) if d.get("suggested_action") else None
        return {**base, "verdict": verdict,
                "root_cause_service": d.get("root_cause_service"), "fault_type": d.get("fault_type"),
                "ranked_candidates": d.get("ranked_candidates") or [d.get("root_cause_service")],
                "confidence": conf, "summary": d.get("summary"),
                "claims": g.kept, "dropped_claims": g.dropped, "evidence_precision": round(g.precision, 3),
                "rejected_hypotheses": d.get("rejected_hypotheses", []),
                "suggested_action": action, "evidence_items": len(self.tel.store.items)}


def _ids(res):
    out = []
    if isinstance(res, dict):
        if "evidence_id" in res:
            out.append(res["evidence_id"])
        for v in res.values():
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, dict) and "evidence_id" in x:
                        out.append(x["evidence_id"])
    return out


def investigate(alert: str, **kw) -> dict:
    return Investigation(alert, **kw).run()
