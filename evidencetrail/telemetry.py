"""Read-only telemetry access: Prometheus metrics, Jaeger traces, JSON log files,
and the change/event log. Every item returned is registered in the EvidenceStore
under a stable ID, so the investigator can only cite things it really fetched.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from .evidence import EvidenceStore
from .redact import redact

PROM = os.environ.get("PROM_URL", "http://localhost:9090")
JAEGER = os.environ.get("JAEGER_URL", "http://localhost:16686")
LOG_DIR = os.environ.get("LOG_DIR", os.path.join(os.path.dirname(__file__), "..", "logs"))


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


@dataclass
class Window:
    start: float
    end: float

    @classmethod
    def last(cls, seconds: float) -> "Window":
        now = time.time()
        return cls(now - seconds, now)


@dataclass
class Telemetry:
    store: EvidenceStore = field(default_factory=EvidenceStore)
    window: Window = field(default_factory=lambda: Window.last(120))
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=15, trust_env=False))

    # per-service time series for the UI charts (/api/series), grouped by SERIES_LABEL
    SERIES_LABEL = "service"
    SERIES_QUERIES = {
        "error_ratio": 'sum by (service) (rate(shop_requests_total{status=~"5.."}[1m])) / sum by (service) (rate(shop_requests_total[1m]))',
        "p95_ms": '1000 * histogram_quantile(0.95, sum by (service, le) (rate(shop_request_duration_seconds_bucket[1m])))',
        "rps": 'sum by (service) (rate(shop_requests_total[1m]))'}

    # ------------------------------------------------------------------ metrics
    def _prom(self, query: str, at: float | None = None) -> list[dict]:
        r = self.client.get(f"{PROM}/api/v1/query", params={"query": query, "time": at or self.window.end})
        r.raise_for_status()
        return r.json()["data"]["result"]

    def service_health(self, rng: str = "1m") -> dict[str, dict]:
        """Per-service request rate, error ratio and p95 latency at the end of the window,
        plus the same numbers from a baseline window before the incident."""
        out: dict[str, dict] = defaultdict(dict)
        base_at = self.window.start
        for label, at in (("now", self.window.end), ("baseline", base_at)):
            rate = self._prom(f"sum by (service) (rate(shop_requests_total[{rng}]))", at)
            err = self._prom(f'sum by (service) (rate(shop_requests_total{{status=~"5.."}}[{rng}]))', at)
            p95 = self._prom(f"histogram_quantile(0.95, sum by (service, le) (rate(shop_request_duration_seconds_bucket[{rng}])))", at)
            for r in rate:
                out[r["metric"]["service"]][f"{label}_rps"] = float(r["value"][1])
            for r in err:
                out[r["metric"]["service"]][f"{label}_err_rps"] = float(r["value"][1])
            for r in p95:
                v = float(r["value"][1])
                out[r["metric"]["service"]][f"{label}_p95_ms"] = None if v != v else round(v * 1000, 1)
        # Prometheus' own scrape status: up == 0 means the service could not be reached (container down)
        up = {r["metric"].get("instance_service"): float(r["value"][1]) for r in self._prom("up", self.window.end)}
        res = {}
        for svc, d in out.items():
            rps, err = d.get("now_rps", 0.0), d.get("now_err_rps", 0.0)
            brps, berr = d.get("baseline_rps", 0.0), d.get("baseline_err_rps", 0.0)
            res[svc] = {
                "rps": round(rps, 2),
                "error_ratio": round(err / rps, 3) if rps else (1.0 if err else 0.0),
                "baseline_error_ratio": round(berr / brps, 3) if brps else 0.0,
                "p95_ms": d.get("now_p95_ms"),
                "baseline_p95_ms": d.get("baseline_p95_ms"),
                "up": up.get(svc, 0.0),
            }
        return res

    METRIC_NAMES = ["error_ratio", "p95_latency_ms", "request_rate", "heap_mb", "db_pool_in_use", "config_version",
                    "dependency_errors", "up"]

    def _metric_queries(self, service: str) -> dict[str, str]:
        return {
            "error_ratio": f'sum(rate(shop_requests_total{{service="{service}",status=~"5.."}}[1m])) / sum(rate(shop_requests_total{{service="{service}"}}[1m]))',
            "p95_latency_ms": f'1000 * histogram_quantile(0.95, sum by (le) (rate(shop_request_duration_seconds_bucket{{service="{service}"}}[1m])))',
            "request_rate": f'sum(rate(shop_requests_total{{service="{service}"}}[1m]))',
            "heap_mb": f'shop_heap_bytes{{service="{service}"}} / 1e6',
            "db_pool_in_use": f'shop_db_pool_in_use{{service="{service}"}}',
            "config_version": f'shop_config_version{{service="{service}"}}',
            "dependency_errors": f'sum by (dependency) (rate(shop_dependency_errors_total{{service="{service}"}}[1m]))',
            "up": f'up{{instance_service="{service}"}}',
        }

    def metric(self, service: str, name: str) -> dict:
        """A small named set of metrics an SRE would look at, sampled across the window."""
        queries = self._metric_queries(service)
        if name not in queries:
            return {"error": f"unknown metric '{name}'. Choose one of {sorted(queries)}"}
        q = queries[name]
        r = self.client.get(f"{PROM}/api/v1/query_range", params={
            "query": q, "start": self.window.start, "end": self.window.end, "step": max(5, int((self.window.end - self.window.start) / 12))})
        r.raise_for_status()
        series = []
        for s in r.json()["data"]["result"]:
            pts = [(int(float(t)), None if v in ("NaN", "+Inf") else round(float(v), 3)) for t, v in s["values"]]
            series.append({"labels": {k: v for k, v in s["metric"].items() if k not in ("__name__", "job", "instance")}, "points": pts})
        text = json.dumps(series)[:1500]
        eid = self.store.add("metric", f"{service}.{name}", text,
                             meta={"service": service, "metric": name, "query": q,
                                   "window": [int(self.window.start), int(self.window.end)]})
        return {"evidence_id": eid, "service": service, "metric": name, "series": series}

    # ------------------------------------------------------------------ logs
    def _read_logs(self, service: str, level: str | None = None) -> list[tuple[int, dict]]:
        # `level` lets a subclass filter at the source; logs() filters again either way
        path = os.path.join(LOG_DIR, f"{service}.log")
        rows = []
        if not os.path.exists(path):
            return rows
        with open(path) as f:
            for i, line in enumerate(f, 1):
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = _ts(rec["ts"])
                if self.window.start <= t <= self.window.end:
                    rows.append((i, rec))
        return rows

    def logs(self, service: str, level: str | None = None, contains: str | None = None, limit: int = 15) -> dict:
        """Returns grouped log lines (by message pattern) so a few lines summarise thousands."""
        rows = self._read_logs(service, level)
        if level:
            rows = [(i, r) for i, r in rows if r.get("level") == level.upper()]
        if contains:
            rows = [(i, r) for i, r in rows if contains.lower() in r.get("msg", "").lower()]
        groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
        for i, r in rows:
            key = "".join("#" if ch.isdigit() else ch for ch in r.get("msg", ""))[:120]
            groups[key].append((i, r))
        out = []
        for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:limit]:
            i, r = items[-1]
            msg = redact(r.get("msg", ""))
            eid = self.store.add("log", self._log_ref(service, i), msg,
                                 meta={"service": service, "line": i, "ts": r["ts"], "level": r.get("level"),
                                       "trace_id": r.get("trace_id"), "count_in_window": len(items)})
            out.append({"evidence_id": eid, "level": r.get("level"), "msg": msg, "count": len(items),
                        "first_ts": items[0][1]["ts"], "last_ts": r["ts"], "trace_id": r.get("trace_id")})
        return {"service": service, "total_matching": len(rows), "groups": out}

    def _log_ref(self, service: str, ref) -> str:
        return f"{service}.log:{ref}"

    def all_log_lines(self, max_lines: int = 400) -> str:
        """Raw tail of every service's logs (used only by the single-prompt baseline)."""
        lines = []
        for fn in sorted(os.listdir(LOG_DIR)):
            if fn.endswith(".log") and fn != "events.log":
                for _, r in self._read_logs(fn[:-4])[-max_lines // 9:]:
                    lines.append(f'{r["ts"]} {r["service"]} {r["level"]} {redact(r["msg"])}')
        return "\n".join(sorted(lines)[-max_lines:])

    # ------------------------------------------------------------------ changes
    def changes(self, lookback_s: float = 900) -> dict:
        path = os.path.join(LOG_DIR, "events.log")
        out = []
        if os.path.exists(path):
            with open(path) as f:
                for i, line in enumerate(f, 1):
                    rec = json.loads(line)
                    if self.window.end - lookback_s <= _ts(rec["ts"]) <= self.window.end:
                        text = json.dumps(rec)
                        eid = self.store.add("change", f"events.log:{i}", text, meta=rec)
                        out.append({"evidence_id": eid, **rec})
        return {"changes": out[-10:], "note": "deployments and config changes in the last 15 minutes"}

    # ------------------------------------------------------------------ traces
    def _traces(self, service: str, limit: int = 40, errors_only: bool = False) -> list[dict]:
        params = {"service": service, "limit": limit, "start": int(self.window.start * 1e6), "end": int(self.window.end * 1e6)}
        if errors_only:
            params["tags"] = json.dumps({"error": "true"})
        r = self.client.get(f"{JAEGER}/api/traces", params=params)
        r.raise_for_status()
        return r.json().get("data") or []

    def dependency_graph(self) -> dict:
        """Service call graph observed in recent traces (caller -> callee, with call counts)."""
        edges: Counter = Counter()
        for t in self._traces("frontend", limit=60) + self._traces("checkout", limit=40):
            procs = {pid: p["serviceName"] for pid, p in t["processes"].items()}
            spans = {s["spanID"]: s for s in t["spans"]}
            for s in t["spans"]:
                for ref in s.get("references", []):
                    parent = spans.get(ref.get("spanID"))
                    if parent:
                        a, b = procs[parent["processID"]], procs[s["processID"]]
                        if a != b:
                            edges[(a, b)] += 1
        graph = [{"caller": a, "callee": b, "calls": n} for (a, b), n in sorted(edges.items())]
        eid = self.store.add("trace", "dependency_graph", json.dumps(graph), meta={"edges": len(graph)})
        return {"evidence_id": eid, "edges": graph}

    def error_traces(self, service: str, limit: int = 5) -> dict:
        """Recent failing traces through a service, reduced to the chain of failing spans.
        The deepest failing span is usually closest to the origin of the fault."""
        out = []
        for t in self._traces(service, limit=limit * 4, errors_only=True)[:limit]:
            procs = {pid: p["serviceName"] for pid, p in t["processes"].items()}
            failing = []
            for s in t["spans"]:
                tags = {tg["key"]: tg["value"] for tg in s.get("tags", [])}
                if tags.get("error") is True or str(tags.get("otel.status_code")) == "ERROR" or int(tags.get("http.status_code", tags.get("http.response.status_code", 0)) or 0) >= 500:
                    if tags.get("span.kind") == "server":
                        failing.append({"service": procs[s["processID"]], "op": s["operationName"],
                                        "duration_ms": round(s["duration"] / 1000, 1),
                                        "status": tags.get("http.status_code") or tags.get("http.response.status_code"),
                                        "span_id": s["spanID"], "start": s["startTime"]})
            failing.sort(key=lambda x: x["start"])
            chain = [f'{f["service"]}({f["status"]}, {f["duration_ms"]}ms)' for f in failing]
            deepest = failing[-1]["service"] if failing else None
            text = f"trace {t['traceID']}: failing server spans in call order: {' -> '.join(chain)}; deepest failing service: {deepest}"
            eid = self.store.add("trace", f"trace:{t['traceID'][:16]}", text, meta={"trace_id": t["traceID"], "deepest": deepest})
            out.append({"evidence_id": eid, "summary": text})
        return {"service": service, "traces": out}

    def slow_traces(self, service: str, limit: int = 5) -> dict:
        """Slowest recent traces through a service with per-service self time."""
        traces = sorted(self._traces(service, limit=60), key=lambda t: -max(s["duration"] for s in t["spans"]))[:limit]
        out = []
        for t in traces:
            procs = {pid: p["serviceName"] for pid, p in t["processes"].items()}
            child_time: Counter = Counter()
            spans = {s["spanID"]: s for s in t["spans"]}
            for s in t["spans"]:
                for ref in s.get("references", []):
                    if ref.get("spanID") in spans:
                        child_time[ref["spanID"]] += s["duration"]
            self_time: Counter = Counter()
            for s in t["spans"]:
                tags = {tg["key"]: tg["value"] for tg in s.get("tags", [])}
                if tags.get("span.kind") == "server":
                    self_time[procs[s["processID"]]] += max(0, s["duration"] - child_time[s["spanID"]])
            top = [(svc, round(us / 1000, 1)) for svc, us in self_time.most_common(3)]
            text = f"trace {t['traceID']}: largest self-time (ms) by service: {top}"
            eid = self.store.add("trace", f"trace:{t['traceID'][:16]}", text, meta={"trace_id": t["traceID"]})
            out.append({"evidence_id": eid, "summary": text})
        return {"service": service, "traces": out}


def telemetry_class() -> type[Telemetry]:
    """The telemetry reader for the configured TARGET (see evidencetrail/target.py)."""
    from .target import OTEL
    if OTEL:
        from .otel_demo import OtelDemoTelemetry
        return OtelDemoTelemetry
    return Telemetry


def make_telemetry(window: Window | None = None, window_s: float = 120) -> Telemetry:
    return telemetry_class()(window=window or Window.last(window_s))
