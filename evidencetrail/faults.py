"""Reproducible fault injection into the team's own Compose test environment."""
from __future__ import annotations

import subprocess

import httpx

from .safety import PORTS

KINDS = {
    # scenario kind -> (ground-truth fault_type, how to inject)
    "crash": "crash_or_unreachable",
    "latency": "latency",
    "memory_leak": "resource_exhaustion",
    "pool_exhaustion": "resource_exhaustion",
    "bad_config": "bad_config",
    "bad_deploy": "bad_deploy",
    "error": "code_error",
}


def inject(service: str, kind: str, **params) -> None:
    if kind == "noise":
        httpx.post(f"http://localhost:{PORTS[service]}/admin/noise", json=params or {"rate": 0.6}, timeout=10,
                   trust_env=False).raise_for_status()
        return
    if kind == "crash":
        subprocess.run(["docker", "compose", "stop", service], check=True, capture_output=True)
        return
    body = {"kind": kind, **params}
    httpx.post(f"http://localhost:{PORTS[service]}/admin/fault", json=body, timeout=10, trust_env=False).raise_for_status()


def clear_all() -> None:
    subprocess.run(["docker", "compose", "start"] + list(PORTS), check=True, capture_output=True)
    for svc, port in PORTS.items():
        try:
            httpx.delete(f"http://localhost:{port}/admin/fault", timeout=5, trust_env=False)
        except httpx.HTTPError:
            pass
