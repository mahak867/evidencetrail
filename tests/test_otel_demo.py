"""Offline tests for the OpenTelemetry Demo adapter (no Docker, no Gemini needed)."""
import json

import pytest

from evidencetrail import faults, otel_demo
from evidencetrail.otel_demo import OtelDemoTelemetry, callee_of, level_of, v3_to_v1
from evidencetrail.telemetry import Window


def _span(trace, span, parent, name, kind, start_ms, end_ms, error=False, msg=None):
    s = {"traceId": trace, "spanId": span, "name": name, "kind": kind,
         "startTimeUnixNano": str(start_ms * 1_000_000), "endTimeUnixNano": str(end_ms * 1_000_000),
         "attributes": [{"key": "rpc.system", "value": {"stringValue": "grpc"}}],
         "status": {"code": 2, "message": msg} if error else {}}
    if parent:
        s["parentSpanId"] = parent
    return s


def _rs(service, spans):
    return {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
            "scopeSpans": [{"spans": spans}]}


def test_v3_traces_convert_to_v1_shape():
    payload = {"result": {"resourceSpans": [
        _rs("checkout", [_span("t1", "a", None, "oteldemo.CheckoutService/PlaceOrder", 2, 0, 50, error=True),
                         _span("t1", "b", "a", "oteldemo.PaymentService/Charge", 3, 10, 40, error=True, msg="charge failed")]),
        _rs("payment", [_span("t1", "c", "b", "oteldemo.PaymentService/Charge", "SPAN_KIND_SERVER", 12, 38, error=True)]),
    ]}}
    [t] = v3_to_v1([payload])
    assert t["traceID"] == "t1"
    assert {p["serviceName"] for p in t["processes"].values()} == {"checkout", "payment"}
    spans = {s["spanID"]: s for s in t["spans"]}
    tags = {tg["key"]: tg["value"] for tg in spans["c"]["tags"]}
    assert tags["span.kind"] == "server" and tags["error"] is True and tags["otel.status_code"] == "ERROR"
    assert spans["c"]["references"] == [{"refType": "CHILD_OF", "spanID": "b"}]
    assert spans["c"]["duration"] == 26_000  # microseconds, like Jaeger v1
    assert {tg["key"]: tg["value"] for tg in spans["b"]["tags"]}["otel.status_description"] == "charge failed"


def test_severity_levels_and_grpc_callee():
    assert [level_of(n) for n in (21, 17, 13, 9, 5, None)] == ["ERROR", "ERROR", "WARN", "INFO", "DEBUG", "DEBUG"]
    assert callee_of("oteldemo.PaymentService/Charge") == "payment"
    assert callee_of("oteldemo.ProductCatalogService/GetProduct") == "product-catalog"
    assert callee_of("POST") is None


def test_flag_injection_edits_default_variant_and_targeting_rule(tmp_path, monkeypatch):
    f = tmp_path / "demo.flagd.json"
    f.write_text(json.dumps({"flags": {
        "paymentFailure": {"defaultVariant": "off", "variants": {"off": 0, "50%": 0.5}},
        "productCatalogFailure": {"defaultVariant": "off", "variants": {"off": False, "on": True},
                                  "targeting": {"if": [{"==": [{"var": "product_id"}, "X"]}, "off", "off"]}}}}))
    monkeypatch.setenv("FLAGD_FILE", str(f))
    faults.set_flag("paymentFailure", "50%")
    faults.set_flag("productCatalogFailure", "on")
    d = json.loads(f.read_text())["flags"]
    assert d["paymentFailure"]["defaultVariant"] == "50%"
    assert d["productCatalogFailure"]["targeting"]["if"][1] == "on"
    assert d["productCatalogFailure"]["defaultVariant"] == "off"  # only the targeted product fails
    with pytest.raises(ValueError):
        faults.set_flag("paymentFailure", "200%")


class _FakeProm(OtelDemoTelemetry):
    """Serves canned Prometheus answers: {(time, kind): {label_value: value}}."""
    answers: dict = {}

    def _prom(self, query, at=None):
        kind = "hist" if "histogram_quantile" in query else \
               ("client_err" if "SPAN_KIND_CLIENT" in query and "ERROR" in query else
                "client" if "SPAN_KIND_CLIENT" in query else
                "err" if "STATUS_CODE_ERROR" in query else "rps")
        label = "span_name" if kind.startswith("client") else "service_name"
        when = "now" if at == self.window.end else "base"
        vals = self.answers.get((when if not kind.startswith("client") else "now", kind), {})
        return [{"metric": {label: k}, "value": [0, str(v)]} for k, v in vals.items()]


def test_unreachable_needs_failing_callers_and_lost_traffic(monkeypatch):
    monkeypatch.setattr(otel_demo, "SERVICES", {"checkout", "payment"})
    charge = "oteldemo.PaymentService/Charge"
    # payment unreachable: its own server traffic stops and every call to it fails
    _FakeProm.answers = {("base", "rps"): {"checkout": 0.1, "payment": 0.1}, ("now", "rps"): {"checkout": 0.1},
                         ("now", "err"): {"checkout": 0.1}, ("now", "client"): {charge: 0.1}, ("now", "client_err"): {charge: 0.1}}
    h = _FakeProm(window=Window(0, 120)).service_health()
    assert h["payment"]["up"] == 0.0 and h["payment"]["callers_error_ratio"] == 1.0
    assert h["checkout"]["up"] == 1.0 and h["checkout"]["error_ratio"] == 1.0
    # payment failing but reachable: it still serves (and fails) requests, so it is not "down"
    _FakeProm.answers = {("base", "rps"): {"checkout": 0.1, "payment": 0.1}, ("now", "rps"): {"checkout": 0.1, "payment": 0.1},
                         ("now", "err"): {"checkout": 0.05, "payment": 0.05}, ("now", "client"): {charge: 0.1},
                         ("now", "client_err"): {charge: 0.05}}
    h = _FakeProm(window=Window(0, 120)).service_health()
    assert h["payment"]["up"] == 1.0 and h["payment"]["error_ratio"] == 0.5


def test_suspects_ignore_infrastructure_in_call_graph():
    from evidencetrail.investigator import suspects
    health = {"payment": {"error_ratio": 0.5, "baseline_error_ratio": 0.0, "up": 1},
              "checkout": {"error_ratio": 0.5, "baseline_error_ratio": 0.0, "up": 1}}
    edges = [{"caller": "checkout", "callee": "payment"}, {"caller": "payment", "callee": "flag-service-not-in-list"},
             {"caller": "load-generator", "callee": "checkout"}]
    out = suspects(health, edges)
    names = [x["service"] for x in out]
    assert "flag-service-not-in-list" not in names and "load-generator" not in names
    assert out[0]["service"] == "payment" and out[0]["deepest"] is True


def test_error_trace_puts_unreached_callee_first(monkeypatch):
    monkeypatch.setattr(otel_demo, "SERVICES", {"frontend", "checkout", "payment"})
    payload = {"result": {"resourceSpans": [
        _rs("load-generator", [_span("t9", "l", None, "POST", 3, 0, 60, error=True)]),
        _rs("frontend", [_span("t9", "f", "l", "POST /api/checkout", 2, 1, 59, error=True),
                         _span("t9", "g", "f", "oteldemo.CheckoutService/PlaceOrder", 3, 2, 58, error=True)]),
        _rs("checkout", [_span("t9", "c", "g", "oteldemo.CheckoutService/PlaceOrder", 2, 3, 57, error=True),
                         _span("t9", "p", "c", "oteldemo.PaymentService/Charge", 3, 10, 50, error=True, msg="dial tcp: no such host")]),
    ]}}

    class T(OtelDemoTelemetry):
        def _traces(self, service, limit=40, errors_only=False):
            return v3_to_v1([payload])
    tr = T(window=Window(0, 120)).error_traces("checkout")["traces"][0]["summary"]
    calls = tr.split("failing calls: ")[1]
    assert calls.startswith("checkout -> payment [oteldemo.PaymentService/Charge] (no server span: callee not reached)")
    assert "deepest failing service: checkout" in tr


def test_suspects_use_operation_and_resource_signals_when_present():
    from evidencetrail.investigator import suspects
    quiet = {"error_ratio": 0.0, "baseline_error_ratio": 0.0, "up": 1}
    health = {
        "cart": {**quiet, "error_ratio": 0.03, "worst_op_error_ratio": 0.5, "baseline_worst_op_error_ratio": 0.0},
        "payment": {**quiet, "cpu_percent": 240.0, "baseline_cpu_percent": 1.2},
        "recommendation": {**quiet, "memory_mb": 420.0, "baseline_memory_mb": 200.0},
        "checkout": {**quiet, "cpu_percent": 30.0, "baseline_cpu_percent": 2.0, "memory_mb": 210.0, "baseline_memory_mb": 200.0},
    }
    names = {x["service"] for x in suspects(health, [])}
    assert {"cart", "payment", "recommendation"} <= names and "checkout" not in names


def test_active_flags_reads_default_and_targeting(tmp_path, monkeypatch):
    f = tmp_path / "demo.flagd.json"
    flags = {name: {"defaultVariant": "off", "variants": {"off": 0, "on": 1, "50%": 0.5, "5sec": 5}} for name in faults.OTEL_FLAGS}
    flags["productCatalogFailure"]["targeting"] = {"if": [{"==": [1, 1]}, "off", "off"]}
    f.write_text(json.dumps({"flags": flags}))
    monkeypatch.setenv("FLAGD_FILE", str(f))
    assert faults.active_flags() == []
    faults.set_flag("productCatalogFailure", "on")
    faults.set_flag("recommendationCacheFailure", "on")
    assert sorted(faults.active_flags()) == ["productCatalogFailure", "recommendationCacheFailure"]
    faults.clear_flags_for(None)
    assert faults.active_flags() == []


class _Resp:
    def __init__(self, data=None, text="", status=200):
        self._d, self.text, self.status_code = data, text, status

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _Client:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None):
        self.calls.append(("post", url, json))
        hits = [{"_id": f"id{i}", "_source": {"@timestamp": f"2026-11-28T08:00:0{i}.000Z", "body": f"line {i}",
                                               "severity": {"number": 17}, "resource": {"service.name": "cart"}}}
                for i in (3, 2, 1)]  # OpenSearch returns newest first for a descending sort
        return _Resp({"hits": {"hits": hits}})

    def get(self, url, params=None):
        self.calls.append(("get", url, params))
        return _Resp(text="", status=404)


def test_logs_take_newest_records_and_filter_level_at_source():
    c = _Client()
    t = OtelDemoTelemetry(window=Window(0, 120), client=c)
    rows = t._search_logs(["cart"], 2000, "ERROR")
    body = c.calls[0][2]
    assert body["sort"] == [{"@timestamp": "desc"}]
    assert {"range": {"severity.number": {"gte": 17, "lte": 24}}} in body["query"]["bool"]["filter"]
    assert [r["msg"] for r in rows] == ["line 1", "line 2", "line 3"]  # handed back oldest first


def test_error_traces_are_filtered_in_jaeger():
    c = _Client()
    OtelDemoTelemetry(window=Window(0, 120), client=c)._traces("frontend", limit=20, errors_only=True)
    params = c.calls[0][2]
    assert json.loads(params["query.attributes"]) == {"error": "true"} and params["query.num_traces"] == 20


def test_rollback_with_no_active_fault_is_not_reported_as_executed(tmp_path, monkeypatch):
    from evidencetrail import safety
    f = tmp_path / "demo.flagd.json"
    f.write_text(json.dumps({"flags": {n: {"defaultVariant": "off", "variants": {"off": 0, "on": 1}} for n in faults.OTEL_FLAGS}}))
    monkeypatch.setenv("FLAGD_FILE", str(f))
    monkeypatch.setattr(safety, "OTEL", True)
    monkeypatch.setattr(safety, "SERVICES", safety.OTEL_SERVICES)
    res = safety.execute({"action": "rollback_config", "service": "checkout"}, approved_by="tester")
    assert res["executed"] is False and res["flags_turned_off"] == [] and "nothing was changed" in res["reason"]


def test_missing_flags_are_skipped_on_clear_and_rejected_on_set(tmp_path, monkeypatch):
    f = tmp_path / "demo.flagd.json"
    f.write_text(json.dumps({"flags": {"paymentFailure": {"defaultVariant": "50%", "variants": {"off": 0, "50%": 0.5}}}}))
    monkeypatch.setenv("FLAGD_FILE", str(f))
    assert faults.active_flags() == ["paymentFailure"]
    assert faults.clear_flags_for(None) == ["paymentFailure"]
    with pytest.raises(ValueError, match="not defined"):
        faults.set_flag("adHighCpu", "on")


def test_unreachable_callee_makes_its_caller_a_victim_without_a_trace_edge():
    from evidencetrail.investigator import suspects
    health = {"checkout": {"error_ratio": 1.0, "baseline_error_ratio": 0.0, "up": 1, "called_by": []},
              "payment": {"error_ratio": 0.0, "baseline_error_ratio": 0.0, "up": 0, "called_by": ["checkout"]}}
    out = suspects(health, edges=[])  # no checkout -> payment trace edge: payment was never reached
    names = [x["service"] for x in out]
    pay, chk = out[names.index("payment")], out[names.index("checkout")]
    assert pay["deepest"] is True and chk["deepest"] is False and "payment" in chk["anomalous_dependencies"]
    assert names.index("payment") < names.index("checkout")
