"""Read-only telemetry for the OpenTelemetry Demo (Astronomy Shop), used when TARGET=oteldemo.

The demo itself is a separate Apache-2.0 project that we run unmodified; this module only reads
its telemetry:
  metrics  Prometheus span metrics (traces_span_metrics_*) and docker_stats container metrics
  traces   Jaeger 2.x query API v3 (OTLP JSON), converted to the v1 shape the base class uses
  logs     OpenSearch index otel-logs-*

Everything returned is registered in the EvidenceStore exactly like the ShopSim telemetry, so the
evidence gate works unchanged.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from .redact import redact
from .safety import SERVICES
from .telemetry import Telemetry

JAEGER_V3 = os.environ.get("JAEGER_URL", "http://localhost:16686/jaeger/ui").rstrip("/")
OPENSEARCH = os.environ.get("OPENSEARCH_URL", "http://localhost:9200").rstrip("/")

MIN_OP_RPS = 0.02  # an operation needs about one call a minute before its error ratio or p95 is used
CALLS = "traces_span_metrics_calls_total"
DUR = "traces_span_metrics_duration_milliseconds_bucket"
SERVER = 'span_kind="SPAN_KIND_SERVER"'
CLIENT = 'span_kind="SPAN_KIND_CLIENT"'
ERR = 'status_code="STATUS_CODE_ERROR"'

# gRPC client span names ("oteldemo.PaymentService/Charge") name the service being called.
GRPC_CALLEE = {
    "oteldemo.AdService": "ad", "oteldemo.CartService": "cart", "oteldemo.CheckoutService": "checkout",
    "oteldemo.CurrencyService": "currency", "oteldemo.EmailService": "email", "oteldemo.PaymentService": "payment",
    "oteldemo.ProductCatalogService": "product-catalog", "oteldemo.RecommendationService": "recommendation",
    "oteldemo.ShippingService": "shipping",
}
SPAN_KIND = {1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer",
             "SPAN_KIND_INTERNAL": "internal", "SPAN_KIND_SERVER": "server", "SPAN_KIND_CLIENT": "client",
             "SPAN_KIND_PRODUCER": "producer", "SPAN_KIND_CONSUMER": "consumer"}


def callee_of(span_name: str) -> str | None:
    return GRPC_CALLEE.get(span_name.split("/")[0])


SEVERITY_RANGE = {"ERROR": (17, 24), "WARN": (13, 16), "INFO": (9, 12)}


def level_of(severity_number) -> str:
    """OpenTelemetry severity numbers: 9-12 INFO, 13-16 WARN, 17+ ERROR (severity text varies by SDK)."""
    n = int(severity_number or 0)
    return "ERROR" if n >= 17 else "WARN" if n >= 13 else "INFO" if n >= 9 else "DEBUG"


def _r1(v):
    return None if v is None or v != v else round(v, 1)


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _otlp_value(v: dict):
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in v:
            return v[k]
    if "intValue" in v:
        return int(v["intValue"])
    return json.dumps(v)[:200]


def _json_stream(text: str) -> list[dict]:
    """The v3 API may return several JSON objects back to back; parse them all."""
    dec, i, out = json.JSONDecoder(), 0, []
    text = text.strip()
    while i < len(text):
        obj, j = dec.raw_decode(text, i)
        out.append(obj)
        i = j
        while i < len(text) and text[i].isspace():
            i += 1
    return out


def v3_to_v1(payloads: list[dict]) -> list[dict]:
    """Convert Jaeger v3 (OTLP JSON) results into Jaeger v1-style traces:
    {traceID, spans: [{spanID, operationName, references, processID, startTime, duration, tags}], processes}."""
    traces: dict[str, dict] = {}
    for p in payloads:
        for rs in (p.get("result") or {}).get("resourceSpans", []):
            res_attrs = {a["key"]: _otlp_value(a["value"]) for a in rs.get("resource", {}).get("attributes", [])}
            svc = str(res_attrs.get("service.name", "unknown"))
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    tid = sp["traceId"]
                    t = traces.setdefault(tid, {"traceID": tid, "spans": [], "processes": {}})
                    pid = f"p-{svc}"
                    t["processes"][pid] = {"serviceName": svc}
                    tags = [{"key": a["key"], "value": _otlp_value(a["value"])} for a in sp.get("attributes", [])]
                    kind = SPAN_KIND.get(sp.get("kind"), "unspecified")
                    status = sp.get("status") or {}
                    code = status.get("code")
                    is_err = code in (2, "STATUS_CODE_ERROR")
                    tags += [{"key": "span.kind", "value": kind},
                             {"key": "otel.status_code", "value": "ERROR" if is_err else ("OK" if code in (1, "STATUS_CODE_OK") else "UNSET")}]
                    if is_err:
                        tags.append({"key": "error", "value": True})
                    if status.get("message"):
                        tags.append({"key": "otel.status_description", "value": status["message"]})
                    start = int(sp["startTimeUnixNano"]) // 1000
                    end = int(sp["endTimeUnixNano"]) // 1000
                    refs = [{"refType": "CHILD_OF", "spanID": sp["parentSpanId"]}] if sp.get("parentSpanId") else []
                    t["spans"].append({"spanID": sp["spanId"], "operationName": sp.get("name", ""), "references": refs,
                                       "processID": pid, "startTime": start, "duration": max(0, end - start), "tags": tags})
    return list(traces.values())


class OtelDemoTelemetry(Telemetry):
    METRIC_NAMES = ["error_ratio", "p95_latency_ms", "request_rate", "dependency_errors", "cpu_percent", "memory_mb"]
    SERIES_LABEL = "service_name"
    SERIES_QUERIES = {
        "error_ratio": f"sum by (service_name) (rate({CALLS}{{{SERVER},{ERR}}}[1m])) / sum by (service_name) (rate({CALLS}{{{SERVER}}}[1m]))",
        "p95_ms": f"histogram_quantile(0.95, sum by (service_name, le) (rate({DUR}{{{SERVER}}}[1m])))",
        "rps": f"sum by (service_name) (rate({CALLS}{{{SERVER}}}[1m]))"}

    # ------------------------------------------------------------------ metrics
    def service_health(self, rng: str = "1m") -> dict[str, dict]:
        """Per-service server-span rate, error ratio and p95, now and at a baseline before the incident,
        plus the error ratio of calls *to* each service seen from its callers (client spans).
        A service counts as unreachable (up = 0) when most calls to it fail and its own server
        traffic has stopped or fallen by 80% or more.
        Also, per service, the operation whose error ratio rose most and the one whose p95 rose most,
        each with its own baseline (a failing or slow rare endpoint is otherwise diluted by healthy
        traffic), and container CPU and memory, now and at the baseline."""
        base_rng = rng
        out: dict[str, dict] = defaultdict(dict)
        ops: dict[str, dict] = {"now": {}, "baseline": {}}  # (service, op) -> {"tot", "err", "p95"}
        # "now" covers the whole incident window, not just its last minute: some faults are
        # intermittent (only some requests are affected) and would be missed by a 1-minute snapshot.
        # The baseline is the minute before the window starts.
        now_rng = f"{max(60, int(self.window.end - self.window.start))}s"
        for label, at in (("now", self.window.end), ("baseline", self.window.start)):
            rng = now_rng if label == "now" else base_rng
            for r in self._prom(f"sum by (service_name, span_name) (rate({CALLS}{{{SERVER}}}[{rng}]))", at):
                ops[label].setdefault((r["metric"]["service_name"], r["metric"].get("span_name")), {})["tot"] = float(r["value"][1])
            for r in self._prom(f"sum by (service_name, span_name) (rate({CALLS}{{{SERVER},{ERR}}}[{rng}]))", at):
                ops[label].setdefault((r["metric"]["service_name"], r["metric"].get("span_name")), {})["err"] = float(r["value"][1])
            for r in self._prom(f"histogram_quantile(0.95, sum by (service_name, span_name, le) (rate({DUR}{{{SERVER}}}[{rng}])))", at):
                v = float(r["value"][1])
                if v == v:
                    ops[label].setdefault((r["metric"]["service_name"], r["metric"].get("span_name")), {})["p95"] = v
            for r in self._prom(f"sum by (service_name) (rate({CALLS}{{{SERVER}}}[{rng}]))", at):
                out[r["metric"]["service_name"]][f"{label}_rps"] = float(r["value"][1])
            for r in self._prom(f"sum by (service_name) (rate({CALLS}{{{SERVER},{ERR}}}[{rng}]))", at):
                out[r["metric"]["service_name"]][f"{label}_err_rps"] = float(r["value"][1])
            for r in self._prom(f"histogram_quantile(0.95, sum by (service_name, le) (rate({DUR}{{{SERVER}}}[{rng}])))", at):
                v = float(r["value"][1])
                out[r["metric"]["service_name"]][f"{label}_p95_ms"] = None if v != v else round(v, 1)
            for r in self._prom(f"100 * rate(container_cpu_usage_nanoseconds_total[{rng}]) / 1e9", at):
                out[r["metric"].get("container_name", "")][f"{label}_cpu"] = float(r["value"][1])
            mem_q = f"max_over_time(container_memory_rss_bytes[{rng}])" if label == "now" else "container_memory_rss_bytes"
            for r in self._prom(f"{mem_q} / 1e6", at):  # incident side: the peak (a leak is about the highest point)
                out[r["metric"].get("container_name", "")][f"{label}_mem"] = float(r["value"][1])
        dep_tot: dict[str, float] = defaultdict(float)
        dep_err: dict[str, float] = defaultdict(float)
        # caller -> callee edges from client span metrics: unlike trace edges, these exist even
        # when the callee is never reached (no server span on its side)
        called_by: dict[str, set] = defaultdict(set)
        for r in self._prom(f"sum by (service_name, span_name) (rate({CALLS}{{{CLIENT}}}[{now_rng}]))", self.window.end):
            c = callee_of(r["metric"].get("span_name", ""))
            if c:
                dep_tot[c] += float(r["value"][1])
                if float(r["value"][1]) > 0 and r["metric"].get("service_name") in SERVICES:
                    called_by[c].add(r["metric"]["service_name"])
        for r in self._prom(f"sum by (service_name, span_name) (rate({CALLS}{{{CLIENT},{ERR}}}[{now_rng}]))", self.window.end):
            c = callee_of(r["metric"].get("span_name", ""))
            if c:
                dep_err[c] += float(r["value"][1])

        def err_ratio(m):
            return (m.get("err", 0.0) / m["tot"]) if m.get("tot") else 0.0

        worst_err: dict[str, tuple] = {}   # service -> (op, now ratio, baseline ratio of the same op)
        worst_lat: dict[str, tuple] = {}   # service -> (op, now p95, baseline p95 of the same op)
        for (svc, op), m in ops["now"].items():
            if m.get("tot", 0.0) < MIN_OP_RPS:  # too few calls for a ratio or a p95 to mean anything
                continue
            b = ops["baseline"].get((svc, op), {})
            e_now, e_base = err_ratio(m), err_ratio(b)
            if e_now - e_base > (worst_err.get(svc, (None, 0.0, 0.0))[1] - worst_err.get(svc, (None, 0.0, 0.0))[2]):
                worst_err[svc] = (op, e_now, e_base)
            # with no baseline calls there is nothing to compare with: only a very slow operation counts
            if "p95" in m and (b.get("p95") is not None or m["p95"] >= 1000):
                slowdown = m["p95"] / max(b.get("p95") or 50.0, 50.0)
                cur = worst_lat.get(svc)
                if cur is None or slowdown > cur[1] / max(cur[2] or 50.0, 50.0):
                    worst_lat[svc] = (op, m["p95"], b.get("p95"))
        res = {}
        for svc in sorted(SERVICES):
            d = out.get(svc, {})
            we, wl = worst_err.get(svc, (None, 0.0, 0.0)), worst_lat.get(svc, (None, None, None))
            rps, err = d.get("now_rps", 0.0), d.get("now_err_rps", 0.0)
            brps, berr = d.get("baseline_rps", 0.0), d.get("baseline_err_rps", 0.0)
            callers = round(dep_err[svc] / dep_tot[svc], 3) if dep_tot[svc] else None
            unreachable = callers is not None and callers >= 0.5 and (rps == 0 or rps <= 0.2 * brps)
            res[svc] = {
                "rps": round(rps, 2),
                "error_ratio": round(err / rps, 3) if rps else (1.0 if err else 0.0),
                "baseline_error_ratio": round(berr / brps, 3) if brps else 0.0,
                "p95_ms": d.get("now_p95_ms"),
                "baseline_p95_ms": d.get("baseline_p95_ms"),
                "callers_error_ratio": callers,
                "called_by": sorted(called_by.get(svc, ())),
                "up": 0.0 if unreachable else 1.0,
                "worst_error_operation": we[0],
                "worst_op_error_ratio": round(we[1], 3),
                "baseline_worst_op_error_ratio": round(we[2], 3),
                "slowest_operation": wl[0],
                "worst_op_p95_ms": _r1(wl[1]),
                "baseline_worst_op_p95_ms": _r1(wl[2]),
                "cpu_percent": _r1(d.get("now_cpu")),
                "baseline_cpu_percent": _r1(d.get("baseline_cpu")),
                "memory_mb": _r1(d.get("now_mem")),
                "baseline_memory_mb": _r1(d.get("baseline_mem")),
            }
        return res

    def _metric_queries(self, service: str) -> dict[str, str]:
        s = f'service_name="{service}"'
        return {
            "error_ratio": f"sum(rate({CALLS}{{{s},{SERVER},{ERR}}}[1m])) / sum(rate({CALLS}{{{s},{SERVER}}}[1m]))",
            "p95_latency_ms": f"histogram_quantile(0.95, sum by (le) (rate({DUR}{{{s},{SERVER}}}[1m])))",
            "request_rate": f"sum(rate({CALLS}{{{s},{SERVER}}}[1m]))",
            "dependency_errors": f"sum by (span_name) (rate({CALLS}{{{s},{CLIENT},{ERR}}}[1m]))",
            # percent of one CPU core, from the raw usage counter (docker_stats' utilization ratio is not reliable here)
            "cpu_percent": f'100 * rate(container_cpu_usage_nanoseconds_total{{container_name="{service}"}}[1m]) / 1e9',
            "memory_mb": f'container_memory_rss_bytes{{container_name="{service}"}} / 1e6',
        }

    # ------------------------------------------------------------------ logs
    def _search_logs(self, services: list[str], size: int, level: str | None = None) -> list[dict]:
        """The newest `size` log records in the window (oldest first), optionally of one level.
        The demo writes thousands of lines a minute, so the query takes the newest records and
        filters by level in OpenSearch: an oldest-first cap would cut off the fault period."""
        flt = [{"terms": {"resource.service.name.keyword": services}},
               {"range": {"@timestamp": {"gte": _iso(self.window.start), "lte": _iso(self.window.end)}}}]
        if level and level.upper() in SEVERITY_RANGE:
            lo, hi = SEVERITY_RANGE[level.upper()]
            flt.append({"range": {"severity.number": {"gte": lo, "lte": hi}}})
        body = {"size": size, "sort": [{"@timestamp": "desc"}], "query": {"bool": {"filter": flt}}}
        r = self.client.post(f"{OPENSEARCH}/otel-logs-*/_search", json=body)
        r.raise_for_status()
        rows = []
        for h in reversed(r.json()["hits"]["hits"]):
            s = h["_source"]
            rows.append({"id": h["_id"], "ts": s.get("@timestamp", "")[:23] + "Z",
                         "service": (s.get("resource") or {}).get("service.name", "?"),
                         "level": level_of((s.get("severity") or {}).get("number")),
                         "msg": s.get("body") if isinstance(s.get("body"), str) else json.dumps(s.get("body"))[:500],
                         "trace_id": s.get("traceId")})
        return rows

    def _read_logs(self, service: str, level: str | None = None) -> list[tuple[str, dict]]:
        return [(r["id"], r) for r in self._search_logs([service], 2000, level)]

    def _log_ref(self, service: str, ref) -> str:
        return f"opensearch:{service}:{str(ref)[:12]}"

    def all_log_lines(self, max_lines: int = 400) -> str:
        """Raw tail of every service's logs in the window (used only by the single-prompt baseline).
        As for ShopSim, each service contributes its own newest lines (an equal share), so chatty
        services such as the proxy's access log cannot crowd the others out."""
        per_service = max(1, max_lines // len(SERVICES))
        rows = [r for svc in sorted(SERVICES) for r in self._search_logs([svc], per_service)]
        lines = sorted(f'{r["ts"]} {r["service"]} {r["level"]} {" ".join(redact(r["msg"] or "").split())}' for r in rows)
        return "\n".join(lines[-max_lines:])

    # ------------------------------------------------------------------ changes
    def changes(self, lookback_s: float = 900) -> dict:
        # The demo has no deploy/config change feed. Feature-flag flips are deliberately NOT reported:
        # they are how we inject faults, so reporting them would hand every method the answer.
        return {"changes": [], "note": "no deployment or configuration change feed is connected in this environment"}

    # ------------------------------------------------------------------ traces
    def _traces(self, service: str, limit: int = 40, errors_only: bool = False) -> list[dict]:
        params = {"query.service_name": service, "query.start_time_min": _iso(self.window.start),
                  "query.start_time_max": _iso(self.window.end), "query.num_traces": limit}
        if errors_only:
            # filter in Jaeger: busy services produce hundreds of traces a second, so the newest
            # few traces rarely contain the failing ones
            params["query.attributes"] = json.dumps({"error": "true"})
        r = self.client.get(f"{JAEGER_V3}/api/v3/traces", params=params)
        if r.status_code == 404:  # no traces in the window
            return []
        r.raise_for_status()
        traces = v3_to_v1(_json_stream(r.text))
        if errors_only:
            traces = [t for t in traces if any(tg["key"] == "error" and tg["value"] is True for s in t["spans"] for tg in s["tags"])]
        return traces[:limit]

    def error_traces(self, service: str, limit: int = 5) -> dict:
        """Failing traces through a service: the chain of failing server spans (deepest last) and
        failing outgoing calls with their status message. A call that fails with no server span on
        the other side means the callee was never reached."""
        out = []
        for t in self._traces(service, limit=limit * 4, errors_only=True)[:limit]:
            procs = {pid: p["serviceName"] for pid, p in t["processes"].items()}
            span_ids = {s["spanID"] for s in t["spans"]}
            children = defaultdict(list)
            for s in t["spans"]:
                for ref in s["references"]:
                    if ref["spanID"] in span_ids:
                        children[ref["spanID"]].append(s)
            failing_server, failing_calls = [], []
            for s in sorted(t["spans"], key=lambda x: x["startTime"]):
                tags = {tg["key"]: tg["value"] for tg in s["tags"]}
                if tags.get("error") is not True:
                    continue
                msg = redact(str(tags.get("otel.status_description", "")))[:160]
                if tags.get("span.kind") == "server":
                    failing_server.append(f'{procs[s["processID"]]}({s["operationName"]}, {round(s["duration"] / 1000, 1)}ms)')
                elif tags.get("span.kind") == "client":
                    target = callee_of(s["operationName"]) or s["operationName"]
                    reached = any(SPAN_KIND_SERVER_TAG in c["tags"] for c in children[s["spanID"]])
                    caller = procs[s["processID"]]
                    line = (f'{caller} -> {target} [{s["operationName"]}]'
                            f'{"" if reached else " (no server span: callee not reached)"}{": " + msg if msg else ""}')
                    # most telling first: calls that never reached their callee, then calls made by
                    # application services (not the load generator or proxy), deepest (latest) first
                    failing_calls.append(((reached, caller not in SERVICES, -s["startTime"]), line))
            failing_calls = [line for _, line in sorted(failing_calls)]
            deepest = failing_server[-1].split("(")[0] if failing_server else None
            text = (f"trace {t['traceID']}: failing server spans in call order: {' -> '.join(failing_server) or 'none'}; "
                    f"deepest failing service: {deepest}; failing calls: {'; '.join(failing_calls[:4]) or 'none'}")
            eid = self.store.add("trace", f"trace:{t['traceID'][:16]}", text, meta={"trace_id": t["traceID"], "deepest": deepest})
            out.append({"evidence_id": eid, "summary": text})
        return {"service": service, "traces": out}


SPAN_KIND_SERVER_TAG = {"key": "span.kind", "value": "server"}
