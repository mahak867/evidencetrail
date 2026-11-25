# EvidenceTrail evaluation scorecard (hard set)

- Scenarios: **6** injected faults across **5** fault types and **5** services (see `eval/scenarios.yaml`).
- Each method investigates the same 120s telemetry window, 60s after injection.
- 95% Wilson confidence intervals in brackets. Small n: treat as indicative, not definitive.

| Method | Top-1 service | Top-3 service | Fault type correct | Inconclusive | Failed | Median time (s) | Median tokens |
|---|---|---|---|---|---|---|---|
| B1_dashboard_rule | 5/6 = 83% [44%–97%] | 6/6 = 100% [61%–100%] | n/a (no type) | 0 | 0 | 0 | 0 |
| B0_single_prompt | 4/6 = 67% [30%–90%] | 4/6 = 67% [30%–90%] | 4/6 = 67% [30%–90%] | 0 | 0 | 11.4 | 14929 |
| EvidenceTrail | 2/6 = 33% [10%–70%] | 5/6 = 83% [44%–97%] | 2/6 = 33% [10%–70%] | 0 | 4 | 63.8 | 5800 |
| EvidenceTrail_ADK | 5/6 = 83% [44%–97%] | 6/6 = 100% [61%–100%] | 5/6 = 83% [44%–97%] | 0 | 1 | 60.3 | 12365 |

## EvidenceTrail evidence gate

- Claims kept: **4**, dropped by the gate: **1** (cited evidence never fetched, or quote not found).
- Mean evidence precision per investigation: **83%**
- Every suggested action labelled by policy; none executed during evaluation.

## Every scenario (misses included)

| ID | Truth | B1 | B0 | EvidenceTrail | ET verdict | ET conf | ET time (s) |
|---|---|---|---|---|---|---|---|
| H01 | currency/latency | ❌ frontend/- | ❌ analytics-collector/resource_exhaustion | ❌ None/- | FAILED | - | 77.7 |
| H02 | shipping/latency | ✅ shipping/- | ❌ checkout/latency | ❌ None/- | FAILED | - | 63.8 |
| H03 | payment/bad_deploy | ✅ payment/- | ✅ payment/code_error | ✅ payment/bad_deploy | DIAGNOSIS | 1.0 | 8.9 |
| H04 | inventory/resource_exhaustion | ✅ inventory/- | ✅ inventory/resource_exhaustion | ❌ None/- | FAILED | - | 52.4 |
| H05 | currency/bad_config | ✅ currency/- | ✅ currency/bad_config | ❌ None/- | FAILED | - | 47.9 |
| H06 | cart/crash_or_unreachable | ✅ cart/- | ✅ cart/crash_or_unreachable | ✅ cart/crash_or_unreachable | DIAGNOSIS | 1.0 | 84.2 |

## Cost and reliability

- EvidenceTrail total tokens: 31,079 over 6 investigations (~5,179 per incident).
- Gemini retries (429/5xx with backoff): 5; hard failures: 73. Models used: ['gemini-3.1-flash-lite', 'gemini-flash-lite-latest'].
- Free-tier Gemini latency varies a lot with demand; elapsed time includes retry back-off.
- Median EvidenceTrail time excluding provider back-off/overload waits: 3.2s

## Known limitations

- Injected faults are single-cause and cleaner than real incidents.
- Small scenario set (n per method is small); intervals are wide.
- The shop is a simplified 9-service app; telemetry volume is far below production.
