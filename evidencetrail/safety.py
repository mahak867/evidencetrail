"""Guarded actions. The model may *suggest* an action, but the risk label comes from
this policy, not from the model, and nothing runs without explicit human approval.
Actions only ever target this project's own Docker Compose test environment.
"""
from __future__ import annotations

import subprocess

import httpx

SERVICES = {"frontend", "checkout", "catalog", "recommendation", "cart", "payment", "shipping", "currency", "inventory"}
PORTS = {s: 8100 + i for i, s in enumerate(["frontend", "checkout", "catalog", "recommendation", "cart",
                                              "payment", "shipping", "currency", "inventory"])}

POLICY = {
    # action: (risk, description)
    "collect_diagnostics": ("safe", "Read-only: snapshot logs, metrics and traces for the service"),
    "restart_service": ("risky", "Restarts the service container; in-flight requests fail"),
    "start_service": ("risky", "Starts a stopped service container"),
    "rollback_deploy": ("risky", "Rolls the service back to its previous image"),
    "rollback_config": ("risky", "Restores the previous configuration version"),
    "scale_up": ("risky", "Not supported in the Compose test environment; always blocked"),
}


def classify(action: dict) -> dict:
    name = action.get("action")
    svc = action.get("service")
    if name not in POLICY:
        return {**action, "risk": "blocked", "reason": f"unknown action '{name}' is not in the allow-list"}
    if svc not in SERVICES:
        return {**action, "risk": "blocked", "reason": f"unknown service '{svc}'"}
    risk, desc = POLICY[name]
    if name == "scale_up":
        risk = "blocked"
    return {**action, "risk": risk, "description": desc, "dry_run": dry_run(name, svc)}


def dry_run(name: str, svc: str) -> str:
    return {
        "collect_diagnostics": f"GET /metrics, tail logs/{svc}.log, query Jaeger for service={svc}",
        "restart_service": f"docker compose restart {svc}",
        "start_service": f"docker compose start {svc}",
        "rollback_deploy": f"DELETE http://localhost:{PORTS[svc]}/admin/fault  (test env: roll back to v2.6.3)",
        "rollback_config": f"DELETE http://localhost:{PORTS[svc]}/admin/fault  (test env: restore config v41)",
        "scale_up": "(blocked)",
    }.get(name, "(none)")


def execute(action: dict, approved_by: str | None) -> dict:
    """Runs an action only if a human approved it. Returns what happened."""
    a = classify(action)
    if a["risk"] == "blocked":
        return {"executed": False, "reason": a["reason"] if "reason" in a else "blocked by policy"}
    if a["risk"] == "risky" and not approved_by:
        return {"executed": False, "reason": "risky action requires human approval"}
    name, svc = a["action"], a["service"]
    if name in ("restart_service", "start_service"):
        cmd = ["docker", "compose", "restart" if name == "restart_service" else "start", svc]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return {"executed": p.returncode == 0, "command": " ".join(cmd), "output": (p.stdout + p.stderr)[-500:], "approved_by": approved_by}
    if name in ("rollback_deploy", "rollback_config"):
        r = httpx.delete(f"http://localhost:{PORTS[svc]}/admin/fault", timeout=10, trust_env=False)
        return {"executed": r.status_code == 200, "command": a["dry_run"], "approved_by": approved_by}
    return {"executed": True, "command": a["dry_run"], "note": "read-only"}
