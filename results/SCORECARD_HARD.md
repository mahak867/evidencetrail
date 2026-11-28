# EvidenceTrail evaluation scorecard (hard set)

- Scenarios: **6** injected faults across **5** fault types and **5** services (see `eval/scenarios.yaml`).
- Each method investigates the same 120s telemetry window, 60s after injection.
- 95% Wilson confidence intervals in brackets. Small n: treat as indicative, not definitive.

| Method | Top-1 service | Top-3 service | Fault type correct | Inconclusive | Failed | Median time (s) | Median tokens |
|---|---|---|---|---|---|---|---|
| B1_dashboard_rule | 5/6 = 83% [44%–97%] | 6/6 = 100% [61%–100%] | n/a (no type) | 0 | 0 | 0 | 0 |
| B0_single_prompt | 4/6 = 67% [30%–90%] | 4/6 = 67% [30%–90%] | 3/6 = 50% [19%–81%] | 0 | 0 | 4.2 | 15050 |
| EvidenceTrail | 5/6 = 83% [44%–97%] | 6/6 = 100% [61%–100%] | 6/6 = 100% [61%–100%] | 1 | 0 | 25.5 | 6387 |
| EvidenceTrail_ADK | 6/6 = 100% [61%–100%] | 6/6 = 100% [61%–100%] | 6/6 = 100% [61%–100%] | 0 | 0 | 67.9 | 17226 |

## EvidenceTrail evidence gate

- Claims kept: **10**, dropped by the gate: **3** (cited evidence never fetched, or quote not found).
- Mean evidence precision per investigation: **72%**
- Every suggested action labelled by policy; none executed during evaluation.

## Every scenario (misses included)

| ID | Truth | B1 | B0 | EvidenceTrail | ET verdict | ET conf | ET time (s) |
|---|---|---|---|---|---|---|---|
| H01 | currency/latency | ❌ frontend/- | ❌ cart/resource_exhaustion | ❌ currency/latency | INCONCLUSIVE | 0.9 | 5.3 |
| H02 | shipping/latency | ✅ shipping/- | ❌ analytics-collector/crash_or_unreachable | ✅ shipping/latency | DIAGNOSIS | 1.0 | 25.5 |
| H03 | payment/bad_deploy | ✅ payment/- | ✅ payment/code_error | ✅ payment/bad_deploy | DIAGNOSIS | 1.0 | 8.9 |
| H04 | inventory/resource_exhaustion | ✅ inventory/- | ✅ inventory/resource_exhaustion | ✅ inventory/resource_exhaustion | DIAGNOSIS | 1.0 | 49.3 |
| H05 | currency/bad_config | ✅ currency/- | ✅ currency/bad_config | ✅ currency/bad_config | DIAGNOSIS | 1.0 | 64.5 |
| H06 | cart/crash_or_unreachable | ✅ cart/- | ✅ cart/crash_or_unreachable | ✅ cart/crash_or_unreachable | DIAGNOSIS | 1.0 | 16.7 |

## Cost and reliability

- EvidenceTrail total tokens: 42,180 over 6 investigations. Per investigation: median 6,387 tokens (mean 7,030).
- Gemini calls per investigation: median 2 (range 1–2).
- Gemini retries (429/5xx with backoff): 1; hard failures: 41. Models used: ['gemini-flash-lite-latest'].
- Free-tier Gemini latency varies a lot with demand; elapsed time includes retry back-off.
- Median EvidenceTrail time excluding provider back-off/overload waits: 3.2s

## Known limitations

- Injected faults are single-cause and cleaner than real incidents.
- Small scenario set (n per method is small); intervals are wide.
- The shop is a simplified 9-service app; telemetry volume is far below production.
