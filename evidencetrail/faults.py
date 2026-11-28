"""Reproducible fault injection into the team's own test environments.

ShopSim (default): admin endpoints on our own services, or stopping a container.
OpenTelemetry Demo (TARGET=oteldemo): the demo's own flagd feature flags, set by editing the
flag file that flagd watches (path from FLAGD_FILE, or OTEL_DEMO_DIR/src/flagd/demo.flagd.json).
"""
from __future__ import annotations

import json
import os
import subprocess

import httpx

from .safety import PORTS
from .target import OTEL

# OpenTelemetry Demo flags we inject: flag -> (root-cause service, fault type, variant to set).
# Ground truth follows each flag's implementation in the demo source:
#   paymentFailure      payment service returns errors on Charge (src/payment)
#   paymentUnreachable  checkout calls payment at a bad address, so payment is never reached (src/checkout)
#   cartFailure         cart service fails a share of requests (src/cart)
#   productCatalogFailure  product catalog fails GetProduct for one product (targeting rule)
#   adFailure           ad service throws on GetAds (src/ad)
#   adHighCpu           ad service burns CPU (src/ad)
#   recommendationCacheFailure  recommendation's cache grows without bound: memory leak (src/recommendation)
#   intlShippingSlowdown  shipping delays non-US quotes by N seconds (src/shipping)
OTEL_FLAGS = {
    "paymentFailure": ("payment", "code_error", "50%"),
    "paymentUnreachable": ("payment", "crash_or_unreachable", "on"),
    "cartFailure": ("cart", "code_error", "50%"),
    "productCatalogFailure": ("product-catalog", "code_error", "on"),
    "adFailure": ("ad", "code_error", "on"),
    "adHighCpu": ("ad", "resource_exhaustion", "on"),
    "recommendationCacheFailure": ("recommendation", "resource_exhaustion", "on"),
    "intlShippingSlowdown": ("shipping", "latency", "5sec"),
}


# Effects that outlive their flag (leaked memory stays allocated): restart the service when clearing,
# so the next scenario starts from a clean state.
RESTART_AFTER = {"recommendationCacheFailure"}


def _load_flags() -> dict:
    with open(_flag_file()) as fh:
        return json.load(fh)


def active_flags() -> list[str]:
    """Injectable flags currently on. Flags this demo version does not define are skipped."""
    flags = _load_flags()["flags"]
    on = []
    for name in OTEL_FLAGS:
        f = flags.get(name)
        if f is None:
            continue
        rule = (f.get("targeting") or {}).get("if")
        variant = rule[1] if isinstance(rule, list) and len(rule) == 3 else f["defaultVariant"]
        if variant != "off":
            on.append(name)
    return on


def _flag_file() -> str:
    return os.environ.get("FLAGD_FILE") or os.path.join(os.environ.get("OTEL_DEMO_DIR", "opentelemetry-demo"),
                                                         "src", "flagd", "demo.flagd.json")


def set_flag(flag: str, variant: str) -> None:
    """Set one flagd flag. Flags with a targeting rule (productCatalogFailure) are switched through
    the rule's 'then' branch, as the demo's own tests do; all others through defaultVariant."""
    path = _flag_file()
    doc = _load_flags()
    f = doc["flags"].get(flag)
    if f is None:
        raise ValueError(f"flag {flag!r} is not defined in {path}; is this the demo version EvidenceTrail was tested with?")
    if variant not in f["variants"]:
        raise ValueError(f"{flag} has no variant {variant!r}; choose from {sorted(f['variants'])}")
    rule = (f.get("targeting") or {}).get("if")
    if isinstance(rule, list) and len(rule) == 3:
        rule[1] = variant
    else:
        f["defaultVariant"] = variant
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # atomic, so flagd never reads a half-written file


def clear_flags_for(service: str | None = None) -> list[str]:
    """Turn off every injectable flag (or only those whose root cause is `service`)."""
    cleared = []
    defined = _load_flags()["flags"]
    for flag, (svc, _, _) in OTEL_FLAGS.items():
        if flag in defined and (service is None or svc == service):
            set_flag(flag, "off")
            cleared.append(flag)
    return cleared


SHOPSIM_KINDS = {
    # scenario kind -> (ground-truth fault_type, how to inject)
    "crash": "crash_or_unreachable",
    "latency": "latency",
    "memory_leak": "resource_exhaustion",
    "pool_exhaustion": "resource_exhaustion",
    "bad_config": "bad_config",
    "bad_deploy": "bad_deploy",
    "error": "code_error",
}
# scenario kind -> ground-truth fault type, for the configured target
KINDS = {flag: ftype for flag, (_, ftype, _) in OTEL_FLAGS.items()} if OTEL else SHOPSIM_KINDS


def inject(service: str, kind: str, **params) -> None:
    if OTEL:
        if kind not in OTEL_FLAGS:
            raise ValueError(f"unknown OpenTelemetry Demo fault {kind!r}; choose from {sorted(OTEL_FLAGS)}")
        if OTEL_FLAGS[kind][0] != service:
            raise ValueError(f"{kind} is a fault in {OTEL_FLAGS[kind][0]}, not {service}")
        set_flag(kind, params.get("variant") or OTEL_FLAGS[kind][2])
        return
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
    if OTEL:
        to_restart = sorted({OTEL_FLAGS[f][0] for f in active_flags() if f in RESTART_AFTER})
        clear_flags_for(None)
        for svc in to_restart:  # container names equal service names in the demo
            subprocess.run(["docker", "restart", svc], check=True, capture_output=True, timeout=120)
        return
    subprocess.run(["docker", "compose", "start"] + list(PORTS), check=True, capture_output=True)
    # reset the deploy/config event log so one scenario's change can't leak into the next
    ev = os.path.join(os.path.dirname(__file__), "..", "logs", "events.log")
    if os.path.exists(ev):
        open(ev, "w").close()
    for svc, port in PORTS.items():
        try:
            httpx.delete(f"http://localhost:{port}/admin/fault", timeout=5, trust_env=False)
        except httpx.HTTPError:
            pass
