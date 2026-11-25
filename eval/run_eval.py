"""Repeatable evaluation: inject each scenario, let it run, investigate with every
method on the same window, score against the known cause, and write a report.

  python -m eval.run_eval                 # all scenarios
  python -m eval.run_eval --only S01,S05  # subset
  python -m eval.run_eval --report-only   # rebuild report from saved runs

Every scenario is reported, including misses and failures.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import time

import yaml

from evidencetrail import faults
from evidencetrail.baselines import b0_single_prompt, b1_dashboard_rule
from evidencetrail.investigator import investigate
from evidencetrail.telemetry import Window

HERE = os.path.dirname(__file__)
RUNS = os.path.join(HERE, "..", "results", "runs")
SET = "standard"
WARMUP_S, SOAK_S, WINDOW_S = 75, 60, 120


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def score(res: dict, truth_svc: str, truth_type: str) -> dict:
    ranked = [s for s in (res.get("ranked_candidates") or []) if s]
    top1 = res.get("root_cause_service") == truth_svc and res.get("verdict") == "DIAGNOSIS"
    return {"top1": top1, "top3": truth_svc in ranked[:3] or top1,
            # methods that name a fault type are scored on it; a failed or empty answer counts as a miss
            "type_ok": (res.get("fault_type") == truth_type) if res.get("method") != "B1_dashboard_rule" else None,
            "inconclusive": res.get("verdict") == "INCONCLUSIVE", "failed": res.get("verdict") == "FAILED"}


def run_one(sc: dict) -> dict:
    faults.clear_all()
    time.sleep(WARMUP_S)
    for ex in sc.get("noise") or []:  # red herrings present before and during the incident
        faults.inject(ex, "noise")
    if sc.get("noise"):
        time.sleep(30)
    faults.inject(sc["service"], sc["kind"], **{k: str(v) for k, v in (sc.get("params") or {}).items()})
    injected_at = time.time()
    time.sleep(SOAK_S)
    truth_type = faults.KINDS[sc["kind"]]
    out = {"scenario": sc, "truth": {"service": sc["service"], "fault_type": truth_type}, "injected_at": injected_at, "methods": {}}
    win = Window.last(WINDOW_S)  # frozen: every method sees exactly the same telemetry window
    out["window"] = [win.start, win.end]
    for name, fn in (("B1_dashboard_rule", lambda: b1_dashboard_rule(window=win)),
                     ("B0_single_prompt", lambda: b0_single_prompt(sc["alert"], window=win)),
                     ("EvidenceTrail", lambda: investigate(sc["alert"], window=win)),
                     ("EvidenceTrail_ADK", lambda: investigate(sc["alert"], window=win, engine="adk"))):
        try:
            r = fn()
        except Exception as e:  # recorded, never hidden
            r = {"verdict": "FAILED", "error": f"{type(e).__name__}: {e}"}
        r["score"] = score(r, sc["service"], truth_type)
        out["methods"][name] = r
        print(f"  {sc['id']} {name:18s} -> {r.get('root_cause_service')}/{r.get('fault_type')} "
              f"[{r.get('verdict')}] top1={r['score']['top1']} ({r.get('elapsed_s')}s)", flush=True)
    faults.clear_all()
    return out


def report(runs: list[dict]) -> str:
    methods = ["B1_dashboard_rule", "B0_single_prompt", "EvidenceTrail", "EvidenceTrail_ADK"]
    n = len(runs)
    lines = [f"# EvidenceTrail evaluation scorecard ({SET} set)", "",
             f"- Scenarios: **{n}** injected faults across **{len({r['truth']['fault_type'] for r in runs})}** fault types "
             f"and **{len({r['truth']['service'] for r in runs})}** services (see `eval/scenarios.yaml`).",
             f"- Each method investigates the same {WINDOW_S}s telemetry window, {SOAK_S}s after injection.",
             "- 95% Wilson confidence intervals in brackets. Small n: treat as indicative, not definitive.", "",
             "| Method | Top-1 service | Top-3 service | Fault type correct | Inconclusive | Failed | Median time (s) | Median tokens |",
             "|---|---|---|---|---|---|---|---|"]
    for m in methods:
        rs = [r["methods"].get(m, {}) for r in runs]
        sc = [x.get("score", {}) for x in rs]
        k1, k3 = sum(bool(s.get("top1")) for s in sc), sum(bool(s.get("top3")) for s in sc)
        typed = [s for s in sc if s.get("type_ok") is not None]
        kt = sum(bool(s["type_ok"]) for s in typed)
        inc, fail = sum(bool(s.get("inconclusive")) for s in sc), sum(bool(s.get("failed")) for s in sc)
        times = sorted(x.get("elapsed_s") or 0 for x in rs)
        toks = sorted((x.get("usage") or {}).get("total_tokens", 0) for x in rs)
        ci = lambda k, nn: f"{k}/{nn} = {k/nn:.0%} [{wilson(k, nn)[0]:.0%}–{wilson(k, nn)[1]:.0%}]" if nn else "n/a"
        lines.append(f"| {m} | {ci(k1, n)} | {ci(k3, n)} | {ci(kt, len(typed)) if m != 'B1_dashboard_rule' else 'n/a (no type)'} "
                     f"| {inc} | {fail} | {times[len(times)//2] if times else '-'} | {toks[len(toks)//2] if toks else '-'} |")
    et = [r["methods"].get("EvidenceTrail", {}) for r in runs]
    precs = [x["evidence_precision"] for x in et if x.get("evidence_precision") is not None]
    kept = sum(len(x.get("claims") or []) for x in et)
    dropped = sum(len(x.get("dropped_claims") or []) for x in et)
    lines += ["", "## EvidenceTrail evidence gate", "",
              f"- Claims kept: **{kept}**, dropped by the gate: **{dropped}** (cited evidence never fetched, or quote not found).",
              f"- Mean evidence precision per investigation: **{sum(precs)/len(precs):.0%}**" if precs else "- Evidence precision: n/a",
              f"- Every suggested action labelled by policy; none executed during evaluation.", "",
              "## Every scenario (misses included)", "",
              "| ID | Truth | B1 | B0 | EvidenceTrail | ET verdict | ET conf | ET time (s) |", "|---|---|---|---|---|---|---|---|"]
    for r in runs:
        t = r["truth"]
        cell = lambda m: ("✅ " if r["methods"].get(m, {}).get("score", {}).get("top1") else "❌ ") + \
            f"{r['methods'].get(m, {}).get('root_cause_service')}/{r['methods'].get(m, {}).get('fault_type') or '-'}"
        e = r["methods"].get("EvidenceTrail", {})
        lines.append(f"| {r['scenario']['id']} | {t['service']}/{t['fault_type']} | {cell('B1_dashboard_rule')} | {cell('B0_single_prompt')} "
                     f"| {cell('EvidenceTrail')} | {e.get('verdict')} | {e.get('confidence', '-')} | {e.get('elapsed_s')} |")
    usage = [x.get("usage") or {} for x in et]
    tot = sum(u.get("total_tokens", 0) for u in usage)
    lines += ["", "## Cost and reliability", "",
              f"- EvidenceTrail total tokens: {tot:,} over {n} investigations (~{tot//max(n,1):,} per incident).",
              f"- Gemini retries (429/5xx with backoff): {sum(u.get('retries', 0) for u in usage)}; "
              f"hard failures: {sum(u.get('failures', 0) for u in usage)}. Models used: "
              f"{sorted({m for x in et for m in (x.get('model') or '').split(',') if m})}.",
              "- Free-tier Gemini latency varies a lot with demand; elapsed time includes retry back-off.",
              (f"- Median EvidenceTrail time excluding provider back-off/overload waits: "
               f"{sorted(max(0, (x.get('elapsed_s') or 0) - (x.get('usage') or {}).get('wait_s', 0)) for x in et)[len(et)//2]:.1f}s"
               if any("wait_s" in (x.get("usage") or {}) for x in et) else "- (back-off time not separately recorded in this run)"), "",
              "## Known limitations", "",
              "- Injected faults are single-cause and cleaner than real incidents.",
              "- Small scenario set (n per method is small); intervals are wide.",
              "- The shop is a simplified 9-service app; telemetry volume is far below production."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--set", default="standard", choices=["standard", "hard"])
    a = ap.parse_args()
    global RUNS, SET
    SET = a.set
    if a.set == "hard":
        RUNS = os.path.join(HERE, "..", "results", "runs_hard")
    os.makedirs(RUNS, exist_ok=True)
    if not a.report_only:
        scs = yaml.safe_load(open(os.path.join(HERE, "scenarios.yaml" if SET == "standard" else "scenarios_hard.yaml")))
        if a.only:
            scs = [s for s in scs if s["id"] in a.only.split(",")]
        for sc in scs:
            print(f"== {sc['id']}: {sc['kind']} on {sc['service']}", flush=True)
            res = run_one(sc)
            json.dump(res, open(os.path.join(RUNS, f"{sc['id']}.json"), "w"), indent=1, default=str)
    runs = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(RUNS, "*.json")))]
    md = report(runs)
    open(os.path.join(HERE, "..", "results", "SCORECARD.md" if SET == "standard" else "SCORECARD_HARD.md"), "w").write(md)
    print(md)


if __name__ == "__main__":
    main()
