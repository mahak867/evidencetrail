"""Re-score the deterministic B1 dashboard-rule baseline on the exact telemetry window each
scenario saved (results/*/S*.json -> "window"). B1 makes no model calls, so this reproduces
what B1 would have answered with the current rule, from the same Prometheus data.

  python -m eval.rescore_b1 [--set standard|hard]
"""
import argparse
import glob
import json
import os

from evidencetrail.baselines import b1_dashboard_rule
from evidencetrail.telemetry import Window

from .run_eval import score

ap = argparse.ArgumentParser(); ap.add_argument("--set", default="standard", choices=["standard", "hard"]); a = ap.parse_args()
folder = os.path.join(os.path.dirname(__file__), "..", "results", "runs" if a.set == "standard" else "runs_hard")
for p in sorted(glob.glob(os.path.join(folder, "*.json"))):
    r = json.load(open(p))
    w = Window(*r["window"])
    old = r["methods"]["B1_dashboard_rule"].get("root_cause_service")
    new = b1_dashboard_rule(window=w)
    new["score"] = score(new, r["truth"]["service"], r["truth"]["fault_type"])
    new["rescored"] = "re-scored on the saved window with the up-metric rule (B1 is deterministic; no model calls)"
    r["methods"]["B1_dashboard_rule"] = new
    json.dump(r, open(p, "w"), indent=1, default=str)
    print(f"{r['scenario']['id']}: {old} -> {new['root_cause_service']} (truth {r['truth']['service']})")
