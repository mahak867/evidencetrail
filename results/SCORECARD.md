# EvidenceTrail evaluation scorecard (standard set)

- Scenarios: **12** injected faults across **6** fault types and **6** services (see `eval/scenarios.yaml`).
- Each method investigates the same 120s telemetry window, 60s after injection.
- 95% Wilson confidence intervals in brackets. Small n: treat as indicative, not definitive.

| Method | Top-1 service | Top-3 service | Fault type correct | Inconclusive | Failed | Median time (s) | Median tokens |
|---|---|---|---|---|---|---|---|
| B1_dashboard_rule | 10/12 = 83% [55%–95%] | 12/12 = 100% [76%–100%] | n/a (no type) | 0 | 0 | 0 | 0 |
| B0_single_prompt | 12/12 = 100% [76%–100%] | 12/12 = 100% [76%–100%] | 10/12 = 83% [55%–95%] | 0 | 0 | 14.1 | 13847 |
| EvidenceTrail | 12/12 = 100% [76%–100%] | 12/12 = 100% [76%–100%] | 12/12 = 100% [76%–100%] | 0 | 0 | 30.6 | 8282 |
| EvidenceTrail_ADK | 10/12 = 83% [55%–95%] | 12/12 = 100% [76%–100%] | 10/12 = 83% [55%–95%] | 0 | 2 | 69.1 | 12090 |

## EvidenceTrail evidence gate

- Claims kept: **31**, dropped by the gate: **0** (cited evidence never fetched, or quote not found).
- Mean evidence precision per investigation: **100%**
- Every suggested action labelled by policy; none executed during evaluation.

## Every scenario (misses included)

| ID | Truth | B1 | B0 | EvidenceTrail | ET verdict | ET conf | ET time (s) |
|---|---|---|---|---|---|---|---|
| S01 | payment/code_error | ❌ checkout/- | ✅ payment/code_error | ✅ payment/code_error | DIAGNOSIS | 1.0 | 37.8 |
| S02 | inventory/code_error | ✅ inventory/- | ✅ inventory/code_error | ✅ inventory/code_error | DIAGNOSIS | 1.0 | 44.9 |
| S03 | currency/latency | ✅ currency/- | ✅ currency/latency | ✅ currency/latency | DIAGNOSIS | 0.9 | 30.6 |
| S04 | shipping/latency | ✅ shipping/- | ✅ shipping/latency | ✅ shipping/latency | DIAGNOSIS | 0.95 | 352.3 |
| S05 | cart/crash_or_unreachable | ✅ cart/- | ✅ cart/crash_or_unreachable | ✅ cart/crash_or_unreachable | DIAGNOSIS | 0.95 | 77.3 |
| S06 | recommendation/crash_or_unreachable | ✅ recommendation/- | ✅ recommendation/crash_or_unreachable | ✅ recommendation/crash_or_unreachable | DIAGNOSIS | 1.0 | 27.1 |
| S07 | recommendation/resource_exhaustion | ✅ recommendation/- | ✅ recommendation/resource_exhaustion | ✅ recommendation/resource_exhaustion | DIAGNOSIS | 0.95 | 16.6 |
| S08 | inventory/resource_exhaustion | ✅ inventory/- | ✅ inventory/resource_exhaustion | ✅ inventory/resource_exhaustion | DIAGNOSIS | 1.0 | 92.9 |
| S09 | currency/bad_config | ✅ currency/- | ✅ currency/bad_config | ✅ currency/bad_config | DIAGNOSIS | 1.0 | 6.3 |
| S10 | shipping/bad_config | ❌ checkout/- | ✅ shipping/bad_config | ✅ shipping/bad_config | DIAGNOSIS | 1.0 | 5.2 |
| S11 | payment/bad_deploy | ✅ payment/- | ✅ payment/code_error | ✅ payment/bad_deploy | DIAGNOSIS | 1.0 | 15.1 |
| S12 | cart/bad_deploy | ✅ cart/- | ✅ cart/code_error | ✅ cart/bad_deploy | DIAGNOSIS | 1.0 | 8.1 |

## Cost and reliability

- EvidenceTrail total tokens: 90,836 over 12 investigations. Per investigation: median 8,282 tokens (mean 7,570).
- Gemini calls per investigation: median 2 (range 1–4).
- Gemini retries (429/5xx with backoff): 2; hard failures: 36. Models used: ['gemini-3-flash-preview', 'gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-flash-lite-latest'].
- Free-tier Gemini latency varies a lot with demand; elapsed time includes retry back-off.
- Median EvidenceTrail time excluding provider back-off/overload waits: 10.8s

## Known limitations

- Injected faults are single-cause and cleaner than real incidents.
- Small scenario set (n per method is small); intervals are wide.
- The shop is a simplified 9-service app; telemetry volume is far below production.
