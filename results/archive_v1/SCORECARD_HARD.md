# EvidenceTrail evaluation scorecard (hard set)

- Scenarios: **6** injected faults across **5** fault types and **5** services (see `eval/scenarios.yaml`).
- Each method investigates the same 120s telemetry window, 60s after injection.
- 95% Wilson confidence intervals in brackets. Small n: treat as indicative, not definitive.

| Method | Top-1 service | Top-3 service | Fault type correct | Inconclusive | Failed | Median time (s) | Median tokens |
|---|---|---|---|---|---|---|---|
| B1_dashboard_rule | 3/6 = 50% [19%–81%] | 5/6 = 83% [44%–97%] | n/a (no type) | 0 | 0 | 0 | 0 |
| B0_single_prompt | 3/6 = 50% [19%–81%] | 3/6 = 50% [19%–81%] | 3/5 = 60% [23%–88%] | 0 | 1 | 6.0 | 14871 |
| EvidenceTrail | 5/6 = 83% [44%–97%] | 6/6 = 100% [61%–100%] | 6/6 = 100% [61%–100%] | 1 | 0 | 43.5 | 12441 |

## EvidenceTrail evidence gate

- Claims kept: **10**, dropped by the gate: **3** (cited evidence never fetched, or quote not found).
- Mean evidence precision per investigation: **78%**
- Every suggested action labelled by policy; none executed during evaluation.

## Every scenario (misses included)

| ID | Truth | B1 | B0 | EvidenceTrail | ET verdict | ET conf | ET time (s) |
|---|---|---|---|---|---|---|---|
| H01 | currency/latency | ❌ frontend/- | ❌ analytics-collector/crash_or_unreachable | ❌ currency/latency | INCONCLUSIVE | 0.9 | 43.5 |
| H02 | shipping/latency | ✅ shipping/- | ❌ checkout/latency | ✅ shipping/latency | DIAGNOSIS | 0.9 | 38.2 |
| H03 | payment/bad_deploy | ✅ payment/- | ✅ payment/code_error | ✅ payment/bad_deploy | DIAGNOSIS | 1.0 | 38.9 |
| H04 | inventory/resource_exhaustion | ✅ inventory/- | ✅ inventory/resource_exhaustion | ✅ inventory/resource_exhaustion | DIAGNOSIS | 1.0 | 18.7 |
| H05 | currency/bad_config | ❌ catalog/- | ✅ currency/bad_config | ✅ currency/bad_config | DIAGNOSIS | 1.0 | 57.5 |
| H06 | cart/crash_or_unreachable | ❌ frontend/- | ❌ None/- | ✅ cart/crash_or_unreachable | DIAGNOSIS | 1.0 | 188.2 |

## Cost and reliability

- EvidenceTrail total tokens: 69,155 over 6 investigations (~11,525 per incident).
- Gemini retries (429/5xx with backoff): 3; hard failures: 26. Models used: ['gemini-3.1-flash-lite', 'gemini-flash-lite-latest'].
- Free-tier Gemini latency varies a lot with demand; elapsed time includes retry back-off.
- Median EvidenceTrail time excluding provider back-off/overload waits: 34.0s

## Known limitations

- Injected faults are single-cause and cleaner than real incidents.
- Small scenario set (n per method is small); intervals are wide.
- The shop is a simplified 9-service app; telemetry volume is far below production.
