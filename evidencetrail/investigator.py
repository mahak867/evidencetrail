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
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import safety
from .evidence import gate
from .gemini import Gemini, GeminiUnavailable, parse_args
from .telemetry import Telemetry, Window, make_telemetry, telemetry_class

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
          {"service": SVC, "name": {"type": "string", "enum": telemetry_class().METRIC_NAMES}},
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
        down = s not in health or h.get("up", 1) == 0  # Prometheus could not scrape it; quiet traffic alone is not "down"
        # optional signals (OpenTelemetry Demo health only; absent for ShopSim, so its behaviour is unchanged):
        # one operation failing far more than before, or the container's CPU or memory jumping
        op_err = (h.get("worst_op_error_ratio") or 0) - (h.get("baseline_worst_op_error_ratio") or 0) > 0.2
        op_p95, op_b = h.get("worst_op_p95_ms") or 0, h.get("baseline_worst_op_p95_ms") or 0
        op_slow = op_p95 > max(250, 3 * (op_b or 50))
        cpu, bcpu = h.get("cpu_percent"), h.get("baseline_cpu_percent")
        cpu_up = cpu is not None and cpu >= 50 and cpu >= 3 * max(bcpu or 0, 5)
        mem, bmem = h.get("memory_mb"), h.get("baseline_memory_mb")
        mem_up = mem is not None and bmem is not None and mem >= 1.3 * bmem and mem - bmem >= 50
        return err_up or slow or down or op_err or op_slow or cpu_up or mem_up
    callees: dict[str, set] = {}
    for e in edges:
        callees.setdefault(e["caller"], set()).add(e["callee"])
    # edges seen in metrics (OpenTelemetry Demo health only): a caller of an unreachable service has
    # no trace edge to it, but its client-span metrics still show the call
    for s, h in health.items():
        for caller in h.get("called_by") or ():
            callees.setdefault(caller, set()).add(s)
    # only services a diagnosis may name; infrastructure in the call graph (load generator,
    # flag service, browser) has no health data and must not be mistaken for "down"
    all_svcs = (set(health) | {e["callee"] for e in edges} | {e["caller"] for e in edges} | set(safety.SERVICES)) & set(safety.SERVICES)
    out = []
    for s in sorted(all_svcs):
        if anomalous(s):
            bad_children = [c for c in callees.get(s, ()) if c in all_svcs and anomalous(c)]
            out.append({"service": s, "anomalous_dependencies": bad_children, "deepest": not bad_children,
                        "health": health.get(s, {"rps": 0, "note": "no metrics: service may be down"})})
    out.sort(key=lambda x: (not x["deepest"], -(x["health"].get("error_ratio") or 0)))
    return out


def entry_service(alert: str) -> str:
    """The user-facing service an alert is about (where failing requests are traced from)."""
    return next((sv for sv in ("checkout", "frontend") if sv in alert), "frontend")


@dataclass
class Investigation:
    alert: str
    window_s: int = 120
    model: str | None = None
    max_steps: int = 4
    window: Window | None = None
    engine: str = field(default_factory=lambda: os.environ.get("ENGINE", "native"))  # native | adk
    tel: Telemetry = field(init=False)
    llm: Gemini = field(init=False)
    trail: list[dict] = field(default_factory=list)
    stage: str = "queued"  # for live progress in the UI

    def __post_init__(self):
        self.tel = make_telemetry(self.window, self.window_s)
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
        top3 = [x["service"] for x in sus[:3]]
        entry = entry_service(self.alert)
        jobs = [(sv, "logs", "get_logs", {"service": sv, "level": "ERROR"}) for sv in top3] + \
               [(sv, "warnings", "get_logs", {"service": sv, "level": "WARN"}) for sv in top3] + \
               [("_entry", "error_traces", "get_error_traces", {"service": entry}), ("_changes", "changes", "get_recent_changes", {})]
        ts = time.time()
        with ThreadPoolExecutor(max_workers=8) as ex:  # independent read-only queries run in parallel
            results = list(ex.map(lambda j: (j, self._run_tool(j[2], j[3])), jobs))
        dur = round(time.time() - ts, 2)
        for (key, kind, tool, args), res in results:
            prefetched.setdefault(key, {})[kind] = res
        for sv in top3:
            self._log({"step": "tool", "tool": "get_logs", "args": {"service": sv, "level": "ERROR+WARN"}, "t": round(ts - t0, 2), "dur": dur,
                       "evidence_ids": _ids(prefetched[sv]["logs"]) + _ids(prefetched[sv]["warnings"])})
        self._log({"step": "tool", "tool": "get_error_traces", "args": {"service": entry}, "t": round(ts - t0, 2), "dur": dur,
                   "evidence_ids": _ids(prefetched["_entry"]["error_traces"])})
        changes = prefetched.pop("_changes")["changes"]
        self._log({"step": "tool", "tool": "get_recent_changes", "args": {}, "t": round(ts - t0, 2), "dur": dur, "evidence_ids": _ids(changes)})
        prefetched["error_traces_via_" + entry] = prefetched.pop("_entry")["error_traces"]

        context = {
                "alert": self.alert,
                "service_health": {"evidence_id": health_id, "services": health},
                "call_graph": {"evidence_id": graph["evidence_id"], "edges": graph["edges"]},
                "topology_suspects": sus,
                "hint": "topology_suspects lists anomalous services; 'deepest': true means none of its own dependencies look anomalous.",
                "prefetched_evidence": prefetched,
                "recent_changes": changes,
                "instructions": "Evidence for the top suspects is already fetched above. Call more tools ONLY if a hypothesis "
                                "still needs testing (e.g. heap_mb, db_pool_in_use, p95_latency_ms, slow traces); otherwise call submit_diagnosis now.",
        }
        self.stage = "gemini"
        diagnosis, error = None, None
        prompt = _fit(context, PROMPT_BUDGET)
        if self.engine == "adk":
            from .adk_agent import run_adk
            diagnosis, error = run_adk(self, json.loads(prompt))
            return self._done(diagnosis, error, sus, health, graph, t0)
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
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
                    msgs.append({"role": "tool", "tool_call_id": c.get("id", name), "name": name, "content": _fit(res, TOOL_BUDGET)})
                if diagnosis:
                    break
        except GeminiUnavailable as e:
            error = str(e)

        return self._done(diagnosis, error, sus, health, graph, t0)

    def _done(self, diagnosis, error, sus, health, graph, t0) -> dict:
        self.stage = "gate"
        out = self._finish(diagnosis, error, sus, time.time() - t0)
        out.update(health=health, edges=graph["edges"], suspects=sus, engine=self.engine)
        self.stage = "done"
        return out

    def _finish(self, d: dict | None, error: str | None, sus: list[dict], elapsed: float) -> dict:
        base = {"alert": self.alert, "model": ",".join(self.llm.used_models) or self.llm.model, "elapsed_s": round(elapsed, 1),
                "usage": self.llm.usage.as_dict(), "trail": self.trail, "topology_suspects": [s["service"] for s in sus]}
        if not d:
            return {**base, "verdict": "FAILED" if error else "INCONCLUSIVE", "error": error or "no diagnosis submitted",
                    "root_cause_service": None, "fault_type": None, "ranked_candidates": [s["service"] for s in sus][:3]}
        g = gate(d.get("claims", []), self.tel.store)
        rc = d.get("root_cause_service")
        # the named root cause must be supported by at least one claim that survived the gate
        rc_ok = bool(rc) and any(rc in c.get("text", "") or any(e.get("meta", {}).get("service") == rc or rc in e.get("ref", "") or rc in e.get("text", "")
                                                             for e in c.get("evidence", [])) for c in g.kept)
        try:
            conf = min(1.0, max(0.0, float(d.get("confidence") or 0)))
        except (TypeError, ValueError):
            conf = 0.0
        verdict = "DIAGNOSIS" if (rc_ok and conf >= 0.5) else "INCONCLUSIVE"
        action = safety.classify(d["suggested_action"]) if d.get("suggested_action") else None
        return {**base, "verdict": verdict,
                "root_cause_service": d.get("root_cause_service"), "fault_type": d.get("fault_type"),
                "ranked_candidates": d.get("ranked_candidates") or [d.get("root_cause_service")],
                "confidence": conf, "summary": d.get("summary"),
                "claims": g.kept, "dropped_claims": g.dropped, "evidence_precision": round(g.precision, 3),
                "rejected_hypotheses": d.get("rejected_hypotheses", []),
                "suggested_action": action, "evidence_items": len(self.tel.store.items)}


PROMPT_BUDGET = 30000  # characters of JSON sent to Gemini; reported per run as prompt tokens
TOOL_BUDGET = 6000


def _fit(obj, budget: int) -> str:
    """Serialise to JSON within a size budget by trimming data, never by cutting the string,
    so the model always receives valid JSON and every evidence ID it sees is complete."""
    txt = json.dumps(obj)
    if len(txt) <= budget:
        return txt
    def shrink(o, n):
        if isinstance(o, dict):
            return {k: shrink(v, n) for k, v in o.items()}
        if isinstance(o, list):
            return [shrink(v, n) for v in o[:n]]
        if isinstance(o, str) and len(o) > 400:
            return o[:400] + "…"
        return o
    for n in (12, 8, 5, 3, 2, 1):
        txt = json.dumps(shrink(obj, n))
        if len(txt) <= budget:
            return txt
    return json.dumps({"truncated": True, "note": "payload too large; call narrower tools"})


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
