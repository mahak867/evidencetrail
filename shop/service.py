"""ShopSim: one generic microservice used for every service in the demo shop.

Each container runs this file with SERVICE_NAME set. Services call each other
over HTTP, so a fault in one service propagates upstream as real errors and
latency, the same way it does in a production microservices system.

Telemetry produced:
  * traces  -> OTLP/HTTP -> Jaeger
  * metrics -> /metrics (Prometheus scrape)
  * logs    -> JSON lines in /logs/<service>.log (with trace_id / span_id)

Fault injection (own test environment only):
  POST   /admin/fault  {"kind": "...", ...}
  DELETE /admin/fault
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

SERVICE = os.environ.get("SERVICE_NAME", "unknown")
LOG_DIR = os.environ.get("LOG_DIR", "/logs")
OTLP = os.environ.get("OTLP_ENDPOINT", "http://jaeger:4318/v1/traces")

# Call graph of the shop. Keys call every service in their list.
TOPOLOGY: dict[str, list[str]] = {
    "frontend": ["catalog", "cart", "checkout", "recommendation"],
    "checkout": ["cart", "catalog", "payment", "shipping", "currency"],
    "catalog": ["inventory", "currency"],
    "recommendation": ["catalog"],
    "cart": [],
    "payment": [],
    "shipping": ["currency"],
    "currency": [],
    "inventory": [],
}
PORT = 8000

# --------------------------------------------------------------------------- tracing
provider = TracerProvider(resource=Resource.create({"service.name": SERVICE}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP), schedule_delay_millis=1000))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SERVICE)
HTTPXClientInstrumentor().instrument()

# --------------------------------------------------------------------------- metrics
REQS = Counter("shop_requests_total", "Requests handled", ["service", "route", "status"])
LAT = Histogram(
    "shop_request_duration_seconds", "Request latency", ["service", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
DEP_ERR = Counter("shop_dependency_errors_total", "Failed calls to a dependency", ["service", "dependency"])
MEM = Gauge("shop_heap_bytes", "Approximate bytes held by the service heap", ["service"])
POOL = Gauge("shop_db_pool_in_use", "Connections in use from the pool", ["service"])
CFG = Gauge("shop_config_version", "Loaded configuration version", ["service"])

# --------------------------------------------------------------------------- logging
os.makedirs(LOG_DIR, exist_ok=True)
_log_lock = threading.Lock()
_log_path = os.path.join(LOG_DIR, f"{SERVICE}.log")


def log(level: str, msg: str, **fields) -> None:
    span = trace.get_current_span().get_span_context()
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "service": SERVICE,
        "level": level,
        "msg": msg,
        "trace_id": format(span.trace_id, "032x") if span.trace_id else None,
        "span_id": format(span.span_id, "016x") if span.span_id else None,
        **fields,
    }
    with _log_lock, open(_log_path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def event(kind: str, **fields) -> None:
    """Deployment / config change events, like Kubernetes events or a deploy log."""
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "service": SERVICE, "kind": kind, **fields}
    with _log_lock, open(os.path.join(LOG_DIR, "events.log"), "a") as f:
        f.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------- fault state
FAULT: dict = {}
NOISE: dict = {}  # benign but alarming-looking log noise (red herrings), independent of FAULT
_leak: list[bytes] = []
CONFIG = {"version": 41, "FX_RATE_SOURCE": "ecb", "DB_POOL_SIZE": 20}
CFG.labels(SERVICE).set(CONFIG["version"])
_pool_in_use = 0

app = FastAPI(title=f"shopsim-{SERVICE}")
FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics,admin/.*,healthz")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": SERVICE}


@app.get("/metrics")
async def metrics():
    MEM.labels(SERVICE).set(sum(len(b) for b in _leak) + 30_000_000)
    POOL.labels(SERVICE).set(_pool_in_use)
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/admin/fault")
async def set_fault(req: Request):
    global FAULT
    body = await req.json()
    FAULT = body
    if body.get("kind") == "bad_config":
        # Simulates a bad config rollout: a new version with an invalid value.
        CONFIG.update(version=CONFIG["version"] + 1, FX_RATE_SOURCE="", **body.get("set", {}))
        CFG.labels(SERVICE).set(CONFIG["version"])
        event("ConfigUpdated", version=CONFIG["version"], changed={"FX_RATE_SOURCE": ""}, author="deploy-bot")
    if body.get("kind") == "bad_deploy":
        event("DeploymentRolledOut", image=f"shopsim/{SERVICE}:v2.7.0-rc1", previous=f"shopsim/{SERVICE}:v2.6.3", author="ci-pipeline")
    return {"ok": True, "fault": FAULT}


@app.post("/admin/noise")
async def set_noise(req: Request):
    global NOISE
    NOISE = await req.json() or {"rate": 0.6}
    return {"ok": True, "noise": NOISE}


NOISE_MSGS = [
    ("ERROR", "client closed connection before response was sent (499)"),
    ("ERROR", "cache: redis GET timeout after 50ms, served from fallback"),
    ("ERROR", "retrying request to analytics-collector (attempt 2/3): 503 Service Unavailable"),
    ("WARN", "slow query: SELECT * FROM sessions took 812ms"),
    ("ERROR", "failed to refresh feature flags; using cached values"),
]


@app.delete("/admin/fault")
async def clear_fault():
    global FAULT, _pool_in_use, NOISE
    NOISE = {}
    FAULT = {}
    _leak.clear()
    _pool_in_use = 0
    CONFIG.update(version=41, FX_RATE_SOURCE="ecb", DB_POOL_SIZE=20)
    CFG.labels(SERVICE).set(41)
    return {"ok": True}


# --------------------------------------------------------------------------- fault behaviour
class Injected(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


async def apply_fault(route: str) -> None:
    global _pool_in_use
    k = FAULT.get("kind")
    if not k:
        return
    rate = float(FAULT.get("rate", 1.0))
    if k == "error" and random.random() < rate:
        msg = FAULT.get("message", "internal error")
        log("ERROR", msg, route=route, error_type=FAULT.get("error_type", "RuntimeError"))
        raise Injected(500, msg)
    if k == "latency":
        delay = float(FAULT.get("ms", 1500)) / 1000 * random.uniform(0.8, 1.2)
        if delay > 1.0 and not FAULT.get("silent"):
            log("WARN", f"slow operation: {route} took {int(delay*1000)}ms", route=route, duration_ms=int(delay * 1000))
        await asyncio.sleep(delay)
    if k == "memory_leak":
        if sum(len(b) for b in _leak) < 300_000_000:  # cap the simulated leak so the host never runs out of memory
            _leak.append(bytes(int(FAULT.get("bytes_per_req", 2_000_000))))
        held = sum(len(b) for b in _leak)
        if held > 150_000_000:
            log("WARN", f"GC pause 1.{random.randint(1,9)}s, heap {held//1_000_000}MB of 256MB limit", route=route, heap_mb=held // 1_000_000)
            await asyncio.sleep(0.8 + held / 600_000_000)
        if held > 240_000_000 and random.random() < 0.5:
            log("ERROR", "java.lang.OutOfMemoryError: Java heap space (simulated)", route=route, error_type="OutOfMemoryError")
            raise Injected(500, "out of memory")
    if k == "pool_exhaustion":
        _pool_in_use = min(_pool_in_use + 1, CONFIG["DB_POOL_SIZE"])
        if _pool_in_use >= CONFIG["DB_POOL_SIZE"]:
            log("ERROR", f"timeout acquiring DB connection after 2000ms (pool {_pool_in_use}/{CONFIG['DB_POOL_SIZE']} in use)",
                route=route, error_type="PoolTimeout")
            await asyncio.sleep(2.0)
            raise Injected(503, "db pool exhausted")
    if k == "bad_config":
        if not CONFIG["FX_RATE_SOURCE"]:
            log("ERROR", "config error: FX_RATE_SOURCE is empty; cannot load exchange rates", route=route,
                error_type="ConfigError", config_version=CONFIG["version"])
            raise Injected(500, "config error")
    if k == "bad_deploy" and random.random() < rate:
        log("ERROR", "TypeError: cannot read property 'amount' of undefined (v2.7.0-rc1)", route=route, error_type="TypeError")
        raise Injected(500, "TypeError")


async def call(dep: str, path: str = "/work") -> dict:
    url = f"http://{dep}:{PORT}{path}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(url)
        if r.status_code >= 500:
            DEP_ERR.labels(SERVICE, dep).inc()
            log("ERROR", f"upstream call to {dep} failed with HTTP {r.status_code}", dependency=dep, status=r.status_code)
            raise Injected(502, f"dependency {dep} failed")
        return r.json()
    except httpx.TimeoutException:
        DEP_ERR.labels(SERVICE, dep).inc()
        log("ERROR", f"timeout calling {dep} after 3000ms", dependency=dep, error_type="Timeout")
        raise Injected(504, f"dependency {dep} timeout")
    except httpx.ConnectError:
        DEP_ERR.labels(SERVICE, dep).inc()
        log("ERROR", f"connection refused: {dep}:{PORT} (dial tcp: connect: connection refused)", dependency=dep, error_type="ConnectError")
        raise Injected(503, f"dependency {dep} unreachable")


@app.get("/work")
async def work(request: Request):
    route = "/work"
    start = time.perf_counter()
    status = 200
    try:
        if NOISE and random.random() < float(NOISE.get("rate", 0.6)):
            lvl, m = random.choice(NOISE_MSGS)
            log(lvl, m, route=route)
        await apply_fault(route)
        await asyncio.sleep(random.uniform(0.003, 0.02))
        deps = TOPOLOGY.get(SERVICE, [])
        if SERVICE == "frontend":
            # A page view touches a subset of backends; 1 in 4 is a checkout.
            deps = ["catalog", "recommendation", "cart"] + (["checkout"] if random.random() < 0.25 else [])
        for d in deps:
            await call(d)
        if SERVICE == "payment":
            log("INFO", "charged card ****4242 via gateway (api_key=FAKE-DEMO-KEY-51HxD9f3k2)", amount_inr=random.randint(199, 4999))
        elif random.random() < 0.05:
            log("INFO", f"{route} ok", route=route)
        return {"service": SERVICE, "ok": True}
    except Injected as e:
        status = e.status
        return JSONResponse({"service": SERVICE, "error": e.detail}, status_code=e.status)
    finally:
        REQS.labels(SERVICE, route, str(status)).inc()
        LAT.labels(SERVICE, route).observe(time.perf_counter() - start)
