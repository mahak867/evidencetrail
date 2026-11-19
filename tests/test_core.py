"""Offline tests for the safety-critical pieces (no Docker, no Gemini needed)."""
from evidencetrail import safety
from evidencetrail.evidence import EvidenceStore, gate
from evidencetrail.investigator import suspects
from evidencetrail.redact import redact


def test_gate_keeps_real_citation_and_quote():
    s = EvidenceStore()
    eid = s.add("log", "payment.log:12", "PaymentGatewayError: upstream gateway rejected request")
    g = gate([{"text": "payment is failing", "evidence_ids": [eid], "quote": "gateway rejected"}], s)
    assert len(g.kept) == 1 and not g.dropped and g.precision == 1.0


def test_gate_drops_fabricated_id():
    s = EvidenceStore()
    g = gate([{"text": "cart crashed", "evidence_ids": ["L-ffffff"]}], s)
    assert not g.kept and "never fetched" in g.dropped[0]["rejected_because"][0]


def test_gate_drops_claim_without_evidence():
    g = gate([{"text": "it is probably DNS", "evidence_ids": []}], EvidenceStore())
    assert g.dropped and g.precision == 0.0


def test_gate_drops_misquote():
    s = EvidenceStore()
    eid = s.add("log", "cart.log:3", "connection refused: cart:8000")
    g = gate([{"text": "x", "evidence_ids": [eid], "quote": "OutOfMemoryError"}], s)
    assert g.dropped and "quoted text" in g.dropped[0]["rejected_because"][0]


def test_redaction():
    out = redact("charged card 4242 4242 4242 4242 via gateway (api_key=FAKE-DEMO-KEY-51HxD9f3k2) for a@b.com")
    assert "FAKE-DEMO-KEY" not in out and "4242 4242" not in out and "a@b.com" not in out


def test_safety_policy_labels_and_blocks():
    assert safety.classify({"action": "collect_diagnostics", "service": "cart"})["risk"] == "safe"
    assert safety.classify({"action": "restart_service", "service": "cart"})["risk"] == "risky"
    assert safety.classify({"action": "rm -rf /", "service": "cart"})["risk"] == "blocked"
    assert safety.classify({"action": "restart_service", "service": "prod-db"})["risk"] == "blocked"
    assert safety.execute({"action": "restart_service", "service": "cart"}, approved_by=None)["executed"] is False


def test_suspects_prefers_deepest_anomaly():
    health = {
        "frontend": {"rps": 5, "error_ratio": 0.3, "baseline_error_ratio": 0, "p95_ms": 40, "baseline_p95_ms": 30},
        "checkout": {"rps": 1, "error_ratio": 1.0, "baseline_error_ratio": 0, "p95_ms": 40, "baseline_p95_ms": 30},
        "payment": {"rps": 1, "error_ratio": 1.0, "baseline_error_ratio": 0, "p95_ms": 10, "baseline_p95_ms": 10},
        "cart": {"rps": 2, "error_ratio": 0, "baseline_error_ratio": 0, "p95_ms": 10, "baseline_p95_ms": 10},
    }
    edges = [{"caller": "frontend", "callee": "checkout"}, {"caller": "checkout", "callee": "payment"},
             {"caller": "checkout", "callee": "cart"}]
    out = suspects(health, edges)
    assert out[0]["service"] == "payment" and out[0]["deepest"]


def test_suspects_flags_missing_service_as_down():
    health = {"frontend": {"rps": 5, "error_ratio": 0.4, "baseline_error_ratio": 0, "p95_ms": 40, "baseline_p95_ms": 30}}
    edges = [{"caller": "frontend", "callee": "cart"}]
    assert suspects(health, edges)[0]["service"] == "cart"
