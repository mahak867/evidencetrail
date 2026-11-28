"""Recovery check after an approved action (read-only).

After a human-approved fix runs, EvidenceTrail keeps reading the same health signals it used to
find the fault, and reports whether the affected services are back to their pre-incident
baseline. It never claims recovery from a single good reading: it needs two consecutive passing
checks, and gives up with "not confirmed" (listing what is still off) after a time limit.
"""
from __future__ import annotations

import time
from typing import Callable

from .telemetry import Window, make_telemetry

ERR_MARGIN = 0.02       # error ratio may be at most 2 points above its baseline
P95_FACTOR = 2.0        # p95 may be at most 2x its baseline ...
P95_FLOOR_MS = 250.0    # ... or 250 ms, whichever is higher


def assess(health: dict, services: list[str]) -> dict:
    """Pass/fail per service from one health reading; `ok` only if every service passes."""
    out = {}
    for s in services:
        h = health.get(s)
        if h is None:
            out[s] = {"ok": False, "problems": ["no health data"]}
            continue
        problems = []
        if h.get("up", 1) == 0:
            problems.append("unreachable")
        err, berr = h.get("error_ratio") or 0.0, h.get("baseline_error_ratio") or 0.0
        if err > berr + ERR_MARGIN:
            problems.append(f"error ratio {err:.3f} vs baseline {berr:.3f}")
        p95, bp95 = h.get("p95_ms"), h.get("baseline_p95_ms")
        limit = max(P95_FLOOR_MS, P95_FACTOR * (bp95 or 0))
        if p95 is not None and p95 > limit:
            problems.append(f"p95 {p95:.0f} ms vs limit {limit:.0f} ms")
        op, bop = h.get("worst_op_error_ratio"), h.get("baseline_worst_op_error_ratio")
        if op is not None and op > (bop or 0.0) + 0.2:
            problems.append(f"operation {h.get('worst_error_operation')} error ratio {op:.2f}")
        out[s] = {"ok": not problems, "problems": problems}
    return {"ok": all(v["ok"] for v in out.values()) and bool(out), "services": out}


def verify(services: list[str], baseline_start: float, timeout_s: float = 240, interval_s: float = 15,
           min_wait_s: float = 60, telemetry_factory: Callable = make_telemetry,
           sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time,
           on_check: Callable[[dict], None] | None = None) -> dict:
    """Poll health until two consecutive checks pass (after `min_wait_s`, so 1-minute rates no
    longer include the incident) or `timeout_s` passes. Health is compared with the baseline at
    `baseline_start`, the start of the incident window (before the fault)."""
    t0 = clock()
    checks, passes = [], 0
    while True:
        now = clock()
        health = telemetry_factory(Window(baseline_start, now)).service_health()
        a = assess(health, services)
        check = {"t": round(now - t0, 1), "ok": a["ok"], "services": a["services"]}
        checks.append(check)
        if on_check:
            on_check(check)
        passes = passes + 1 if (a["ok"] and now - t0 >= min_wait_s) else 0
        if passes >= 2:
            return {"status": "recovered", "after_s": round(now - t0, 1), "checks": checks}
        if now - t0 >= timeout_s:
            still = {s: v["problems"] for s, v in a["services"].items() if not v["ok"]}
            return {"status": "not_confirmed", "after_s": round(now - t0, 1), "still_off": still, "checks": checks}
        sleep(interval_s)
