"""EvidenceTrail web app: start an investigation, watch it, inspect cited evidence,
confirm/correct/reject the diagnosis, and approve or block the suggested action.

  GEMINI_API_KEY=... uvicorn evidencetrail.server:app --port 8080
"""
from __future__ import annotations

import glob
import json
import math
import os
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import faults, safety
from .gemini import FALLBACKS, MODEL
from .investigator import Investigation
from .telemetry import Telemetry, Window

ROOT = os.path.join(os.path.dirname(__file__), "..")
app = FastAPI(title="EvidenceTrail")
JOBS: dict[str, dict] = {}
INVS: dict[str, Investigation] = {}
AUDIT = os.path.join(ROOT, "results", "audit.log")


def audit(event: str, **kw):
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    with open(AUDIT, "a") as f:
        f.write(json.dumps({"ts": time.time(), "event": event, **kw}, default=str) + "\n")


class InvReq(BaseModel):
    alert: str
    window_s: int = 120


class Feedback(BaseModel):
    decision: str  # confirm | correct | reject
    corrected_service: str | None = None
    note: str | None = None


class Approval(BaseModel):
    approved_by: str
    approve: bool = True


class FaultReq(BaseModel):
    service: str
    kind: str


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "ui", "index.html"))


@app.get("/api/meta")
def meta():
    return {"model": MODEL, "fallbacks": FALLBACKS, "services": sorted(safety.SERVICES),
            "fault_kinds": list(faults.KINDS), "policy": {k: v[0] for k, v in safety.POLICY.items()}}


@app.post("/api/investigate")
def start(req: InvReq):
    jid = uuid.uuid4().hex[:8]
    inv = Investigation(req.alert, window_s=req.window_s)
    INVS[jid] = inv
    JOBS[jid] = {"id": jid, "status": "running", "alert": req.alert, "started": time.time()}

    def work():
        try:
            JOBS[jid].update(status="done", result=inv.run())
        except Exception as e:
            JOBS[jid].update(status="error", error=f"{type(e).__name__}: {e}")
    threading.Thread(target=work, daemon=True).start()
    audit("investigation_started", id=jid, alert=req.alert)
    return {"id": jid}


@app.get("/api/investigations/{jid}")
def get(jid: str):
    if jid not in JOBS:
        raise HTTPException(404)
    inv = INVS.get(jid)
    out = dict(JOBS[jid])
    if inv:
        out["stage"] = inv.stage
        out["elapsed_s"] = round(time.time() - out["started"], 1)
        if out["status"] == "running":
            out["live_trail"] = [t for t in inv.trail if t.get("step") == "tool"]
    return out


@app.post("/api/investigations/{jid}/feedback")
def feedback(jid: str, fb: Feedback):
    if jid not in JOBS:
        raise HTTPException(404)
    JOBS[jid]["feedback"] = fb.model_dump()
    audit("diagnosis_feedback", id=jid, **fb.model_dump())
    return {"ok": True}


@app.post("/api/investigations/{jid}/action")
def action(jid: str, ap: Approval):
    job = JOBS.get(jid)
    if not job or not (job.get("result") or {}).get("suggested_action"):
        raise HTTPException(404, "no suggested action")
    act = job["result"]["suggested_action"]
    if not ap.approve:
        audit("action_blocked_by_human", id=jid, action=act, by=ap.approved_by)
        return {"executed": False, "reason": f"blocked by {ap.approved_by}"}
    res = safety.execute(act, approved_by=ap.approved_by)
    audit("action_executed" if res.get("executed") else "action_not_executed", id=jid, action=act, result=res)
    job["action_result"] = res
    return res


@app.get("/api/health")
def health(window_s: int = 120):
    """Live service health and call graph for the service map."""
    tel = Telemetry(window=Window.last(window_s))
    try:
        h = tel.service_health()
        edges = tel.dependency_graph()["edges"]
    except Exception as e:
        raise HTTPException(503, f"telemetry unavailable: {e}")
    return {"ts": time.time(), "services": h, "edges": edges, "expected": sorted(safety.SERVICES)}


@app.get("/api/series")
def series(minutes: int = 10):
    """Per-service error ratio, p95 latency and request rate over the last N minutes (Prometheus)."""
    import httpx
    from .telemetry import PROM
    end = time.time(); start = end - minutes * 60; step = max(10, minutes * 60 // 48)
    qs = {"error_ratio": 'sum by (service) (rate(shop_requests_total{status=~"5.."}[1m])) / sum by (service) (rate(shop_requests_total[1m]))',
          "p95_ms": '1000 * histogram_quantile(0.95, sum by (service, le) (rate(shop_request_duration_seconds_bucket[1m])))',
          "rps": 'sum by (service) (rate(shop_requests_total[1m]))'}
    out: dict = {"start": start, "end": end, "step": step, "services": {}}
    with httpx.Client(timeout=10, trust_env=False) as c:
        for name, q in qs.items():
            try:
                r = c.get(f"{PROM}/api/v1/query_range", params={"query": q, "start": start, "end": end, "step": step})
                r.raise_for_status()
            except Exception as e:
                raise HTTPException(503, f"prometheus unavailable: {e}")
            for res in r.json()["data"]["result"]:
                svc = res["metric"].get("service")
                pts = [[int(float(t)), None if v in ("NaN", "+Inf", "-Inf") else round(float(v), 4)] for t, v in res["values"]]
                out["services"].setdefault(svc, {})[name] = pts
    return out


# --- demo-environment helpers (own Compose test environment only) ---
@app.post("/api/faults")
def inject(fr: FaultReq):
    if (fr.kind not in faults.KINDS and fr.kind != "noise") or fr.service not in safety.SERVICES:
        raise HTTPException(400, "unknown service or fault kind")
    faults.inject(fr.service, fr.kind)
    audit("fault_injected", service=fr.service, kind=fr.kind)
    return {"ok": True}


@app.delete("/api/faults")
def clear():
    faults.clear_all()
    audit("faults_cleared")
    return {"ok": True}


def _load_runs(folder: str) -> list[dict]:
    return [json.load(open(p)) for p in sorted(glob.glob(os.path.join(ROOT, "results", folder, "*.json")))]


@app.get("/api/recorded")
def recorded():
    """Saved evaluation runs, for replaying a labelled recorded run offline."""
    out = []
    for folder, label in (("runs", "standard"), ("runs_hard", "hard")):
        for r in _load_runs(folder):
            out.append({"id": r["scenario"]["id"], "set": label, "truth": r["truth"], "alert": r["scenario"]["alert"],
                        "result": r["methods"].get("EvidenceTrail")})
    return out


def _wilson(k: int, n: int, z: float = 1.96):
    if not n:
        return [0, 0]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


@app.get("/api/scorecard.json")
def scorecard_json():
    methods = ["B1_dashboard_rule", "B0_single_prompt", "EvidenceTrail"]
    sets = {}
    for folder, label in (("runs", "standard"), ("runs_hard", "hard")):
        runs = _load_runs(folder)
        if not runs:
            continue
        st = {"n": len(runs), "methods": {}, "scenarios": []}
        for m in methods:
            rs = [r["methods"].get(m, {}) for r in runs]
            sc = [x.get("score", {}) for x in rs]
            k1 = sum(bool(s.get("top1")) for s in sc)
            typed = [s for s in sc if s.get("type_ok") is not None]
            times = sorted(x.get("elapsed_s") or 0 for x in rs)
            st["methods"][m] = {"top1": k1, "top3": sum(bool(s.get("top3")) for s in sc), "ci": _wilson(k1, len(runs)),
                                "type_ok": sum(bool(s["type_ok"]) for s in typed), "typed": len(typed),
                                "inconclusive": sum(bool(s.get("inconclusive")) for s in sc),
                                "failed": sum(bool(s.get("failed")) for s in sc),
                                "median_s": times[len(times) // 2] if times else None,
                                "median_tokens": sorted((x.get("usage") or {}).get("total_tokens", 0) for x in rs)[len(rs) // 2]}
        et = [r["methods"].get("EvidenceTrail", {}) for r in runs]
        st["claims_kept"] = sum(len(x.get("claims") or []) for x in et)
        st["claims_dropped"] = sum(len(x.get("dropped_claims") or []) for x in et)
        for r in runs:
            st["scenarios"].append({"id": r["scenario"]["id"], "truth": r["truth"],
                                    "methods": {m: {"svc": r["methods"].get(m, {}).get("root_cause_service"),
                                                    "type": r["methods"].get(m, {}).get("fault_type"),
                                                    "top1": r["methods"].get(m, {}).get("score", {}).get("top1"),
                                                    "verdict": r["methods"].get(m, {}).get("verdict"),
                                                    "s": r["methods"].get(m, {}).get("elapsed_s")} for m in methods}})
        sets[label] = st
    return sets


@app.get("/api/audit")
def audit_log(limit: int = 100):
    if not os.path.exists(AUDIT):
        return []
    lines = open(AUDIT).read().splitlines()[-limit:]
    return [json.loads(x) for x in reversed(lines)]


@app.get("/api/scorecard", response_class=PlainTextResponse)
def scorecard():
    p = os.path.join(ROOT, "results", "SCORECARD.md")
    return open(p).read() if os.path.exists(p) else "No evaluation yet. Run: python -m eval.run_eval"
