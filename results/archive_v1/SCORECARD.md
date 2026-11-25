# EvidenceTrail evaluation scorecard

- Scenarios: **12** injected faults across **6** fault types and **6** services (see `eval/scenarios.yaml`).
- Each method investigates the same 120s telemetry window, 60s after injection.
- 95% Wilson confidence intervals in brackets. Small n: treat as indicative, not definitive.

| Method | Top-1 service | Top-3 service | Fault type correct | Inconclusive | Failed | Median time (s) | Median tokens |
|---|---|---|---|---|---|---|---|
| B1_dashboard_rule | 8/12 = 67% [39%–86%] | 10/12 = 83% [55%–95%] | n/a (no type) | 0 | 0 | 0 | 0 |
| B0_single_prompt | 12/12 = 100% [76%–100%] | 12/12 = 100% [76%–100%] | 10/12 = 83% [55%–95%] | 0 | 0 | 13.5 | 13631 |
| EvidenceTrail | 12/12 = 100% [76%–100%] | 12/12 = 100% [76%–100%] | 12/12 = 100% [76%–100%] | 0 | 0 | 34.5 | 8782 |

## EvidenceTrail evidence gate

- Claims kept: **23**, dropped by the gate: **7** (cited evidence never fetched, or quote not found).
- Mean evidence precision per investigation: **76%**
- Every suggested action labelled by policy; none executed during evaluation.

## Every scenario (misses included)

| ID | Truth | B1 | B0 | EvidenceTrail | ET verdict | ET conf | ET time (s) |
|---|---|---|---|---|---|---|---|
| S01 | payment/code_error | ✅ payment/- | ✅ payment/code_error | ✅ payment/code_error | DIAGNOSIS | 0.9 | 140.5 |
| S02 | inventory/code_error | ✅ inventory/- | ✅ inventory/code_error | ✅ inventory/code_error | DIAGNOSIS | 1.0 | 656.8 |
| S03 | currency/latency | ✅ currency/- | ✅ currency/latency | ✅ currency/latency | DIAGNOSIS | 0.9 | 8.9 |
| S04 | shipping/latency | ✅ shipping/- | ✅ shipping/latency | ✅ shipping/latency | DIAGNOSIS | 0.9 | 18.4 |
| S05 | cart/crash_or_unreachable | ❌ frontend/- | ✅ cart/crash_or_unreachable | ✅ cart/crash_or_unreachable | DIAGNOSIS | 1.0 | 34.5 |
| S06 | recommendation/crash_or_unreachable | ❌ frontend/- | ✅ recommendation/crash_or_unreachable | ✅ recommendation/crash_or_unreachable | DIAGNOSIS | 1.0 | 50.6 |
| S07 | recommendation/resource_exhaustion | ✅ recommendation/- | ✅ recommendation/resource_exhaustion | ✅ recommendation/resource_exhaustion | DIAGNOSIS | 1.0 | 399.1 |
| S08 | inventory/resource_exhaustion | ❌ catalog/- | ✅ inventory/resource_exhaustion | ✅ inventory/resource_exhaustion | DIAGNOSIS | 1.0 | 17.6 |
| S09 | currency/bad_config | ✅ currency/- | ✅ currency/bad_config | ✅ currency/bad_config | DIAGNOSIS | 1.0 | 6.3 |
| S10 | shipping/bad_config | ❌ checkout/- | ✅ shipping/bad_config | ✅ shipping/bad_config | DIAGNOSIS | 1.0 | 8.0 |
| S11 | payment/bad_deploy | ✅ payment/- | ✅ payment/code_error | ✅ payment/bad_deploy | DIAGNOSIS | 1.0 | 10.9 |
| S12 | cart/bad_deploy | ✅ cart/- | ✅ cart/code_error | ✅ cart/bad_deploy | DIAGNOSIS | 1.0 | 43.7 |

## Cost and reliability

- EvidenceTrail total tokens: 94,646 over 12 investigations (~7,887 per incident).
- Gemini retries (429/5xx with backoff): 8; hard failures: 20. Models used: ['gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-flash-lite-latest'].
- Free-tier Gemini latency varies a lot with demand; elapsed time includes retry back-off.

## Known limitations

- Injected faults are single-cause and cleaner than real incidents.
- Small scenario set (n per method is small); intervals are wide.
- The shop is a simplified 9-service app; telemetry volume is far below production.
