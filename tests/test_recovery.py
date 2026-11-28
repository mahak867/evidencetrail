"""Offline tests for the recovery check (no Docker, no Gemini)."""
from evidencetrail.recovery import assess, verify

HEALTHY = {"error_ratio": 0.0, "baseline_error_ratio": 0.0, "p95_ms": 40.0, "baseline_p95_ms": 35.0, "up": 1}


def test_assess_flags_each_kind_of_problem():
    health = {
        "payment": {**HEALTHY, "error_ratio": 0.5},
        "shipping": {**HEALTHY, "p95_ms": 5000.0},
        "cart": {**HEALTHY, "up": 0},
        "ad": dict(HEALTHY),
    }
    a = assess(health, ["payment", "shipping", "cart", "ad", "missing"])
    assert not a["ok"]
    s = a["services"]
    assert "error ratio" in s["payment"]["problems"][0]
    assert "p95" in s["shipping"]["problems"][0]
    assert s["cart"]["problems"] == ["unreachable"]
    assert s["ad"]["ok"] and s["missing"]["problems"] == ["no health data"]


def test_small_noise_still_counts_as_recovered():
    a = assess({"payment": {**HEALTHY, "error_ratio": 0.015, "p95_ms": 240.0, "baseline_p95_ms": 20.0}}, ["payment"])
    assert a["ok"]


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _factory(readings):
    it = iter(readings)

    class _T:
        def __init__(self, window):
            self.h = next(it)

        def service_health(self):
            return self.h
    return _T


def test_verify_needs_two_passing_checks_after_min_wait():
    clock = _Clock()
    bad, good = {"payment": {**HEALTHY, "error_ratio": 0.4}}, {"payment": dict(HEALTHY)}
    # good at t=0 and t=15 (before min_wait 60s: not counted), bad at 30, then good from 45 onwards
    readings = [good, good, bad, good, good, good, good, good]
    r = verify(["payment"], 900.0, timeout_s=240, interval_s=15, min_wait_s=60,
               telemetry_factory=_factory(readings), sleep=clock.sleep, clock=clock)
    assert r["status"] == "recovered" and r["after_s"] == 75.0


def test_verify_reports_what_is_still_off_on_timeout():
    clock = _Clock()
    bad = {"payment": {**HEALTHY, "error_ratio": 0.4}}
    r = verify(["payment"], 900.0, timeout_s=60, interval_s=15, min_wait_s=0,
               telemetry_factory=_factory([bad] * 10), sleep=clock.sleep, clock=clock)
    assert r["status"] == "not_confirmed" and "error ratio" in r["still_off"]["payment"][0]
    assert len(r["checks"]) == 5  # t = 0, 15, 30, 45, 60
