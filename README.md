# EvidenceTrail

**Find the cause. Show the evidence.**

EvidenceTrail helps an on-call engineer reach a checked root-cause diagnosis in the first minutes after an alert, using Google Gemini. It enforces one rule: **no evidence, no claim**. Every statement in a diagnosis must cite a log line, trace or metric window that the system actually fetched during the investigation. When the evidence is weak, the verdict is **INCONCLUSIVE** instead of a guess. Nothing in the system changes without human approval.

> CODERED '26 · Track 1 Niveus Solutions (NTT DATA) · PS2: AI Incident Investigation for Cloud-Native Systems

| | |
|---|---|
| **User** | On-call engineer / SRE, just paged |
| **Bottleneck** | Root-cause localisation in the first minutes, while one fault makes alerts fire in several services |
| **Metric** | Top-1 / top-3 root-cause accuracy and time to diagnosis, against two baselines on the same injected faults |

## Where Gemini is used

| Feature | Model | Where |
|---|---|---|
| Hypothesis-testing investigation agent (tool calling over logs, metrics, traces, changes) | `gemini-3.1-flash-lite` (primary); on 503 "high demand" or a daily-quota 429 it falls back to `gemini-3-flash-preview` → `gemini-3.5-flash` → `gemini-flash-latest` → `gemini-flash-lite-latest` | `evidencetrail/investigator.py`, `evidencetrail/gemini.py` |
| Structured diagnosis (service, fault type, cited claims, rejected hypotheses, suggested action) | same | `submit_diagnosis` tool in `investigator.py` |
| Baseline B0 (single prompt with raw logs) | same model, for a fair comparison | `evidencetrail/baselines.py` |

The model actually used for each run is recorded in its result JSON. Override the defaults with `GEMINI_MODEL`, `GEMINI_FALLBACKS` and `GEMINI_REASONING`.

**Free-tier budget.** Some Gemini models allow only about 20 requests per day on the free tier. EvidenceTrail is designed around that: the health scan, call graph and the top suspects' logs, traces and changes are fetched *before* Gemini is called, so an investigation needs **1–4 Gemini calls** (median 2.5; about 8.8k tokens on the standard set). Gemini asks for more tools only when a hypothesis still needs testing.

All Gemini calls use the Gemini API (OpenAI-compatible endpoint) with each team's own free-tier key. HTTP 429 and 5xx responses get bounded exponential backoff, then model fallback, then a clear `FAILED` state. Token usage is recorded for every investigation. Gemini is **inside the product**; it is not just a coding assistant.

## How it works

```
alert ─► 1. health scan (Prometheus): error ratio + p95 vs a baseline window
       ─► 2. call graph (Jaeger traces): deepest anomalous service = suspect; callers = victims
       ─► 3. prefetch: top suspects' error/warn logs, failing traces, recent deploys/config changes
       ─► 4. Gemini agent: proposes hypotheses, calls more read-only tools only if still needed
              get_logs · get_metric · get_error_traces · get_slow_traces · get_recent_changes
       ─► 5. evidence gate: drops claims citing IDs never fetched, or quotes not in the evidence
              root-cause claim must survive AND confidence ≥ 0.5, else INCONCLUSIVE
       ─► 6. engineer confirms / corrects / rejects  ─►  suggested action labelled by POLICY
              (safe / risky / blocked), dry run shown, runs only after named human approval
```

Safety by design:
- Read-only telemetry access by default.
- Secrets, card numbers, emails and JWTs are redacted before anything reaches Gemini (`redact.py`; the payment service deliberately logs a fake API key to demonstrate this).
- Action risk is decided by an allow-list policy, never by the model (`safety.py`).
- Every approval, block and feedback event goes to `results/audit.log`.

## Target application and fault injection

`docker-compose.yml` runs **ShopSim**: 9 Python microservices (frontend, checkout, catalog, recommendation, cart, payment, shipping, currency, inventory) that call each other over HTTP, so faults propagate upstream as real errors and latency. Alongside them run Jaeger (traces via OpenTelemetry), Prometheus (metrics), JSON logs with trace IDs, a deploy/config event log, and a load generator.

The fault types below are injected through each service's `/admin/fault` endpoint or `docker compose stop`, in this test environment only:

| Kind | Ground-truth type | Symptom |
|---|---|---|
| `error` | code_error | exceptions on a share of requests |
| `latency` | latency | slow responses, no errors |
| `crash` | crash_or_unreachable | container stopped; callers log connection refused |
| `memory_leak` | resource_exhaustion | heap grows, GC pauses, then OOM errors |
| `pool_exhaustion` | resource_exhaustion | DB pool saturates, timeouts |
| `bad_config` | bad_config | config version bump with an empty value, then errors |
| `bad_deploy` | bad_deploy | new image rolled out, then TypeErrors |

The scenario set with known causes is in `eval/scenarios.yaml`: 12 scenarios, 6 fault types, 6 services (the hard set adds 6 more in `eval/scenarios_hard.yaml`).

## Quick start

Requirements: Docker with Compose, Python 3.11+, and a Gemini API key from Google AI Studio.

```bash
docker compose up -d --build                  # shop + Jaeger (:16686) + Prometheus (:9090)
pip install -r requirements.txt
export GEMINI_API_KEY=...                     # never commit this
uvicorn evidencetrail.server:app --port 8080  # open http://localhost:8080
```

From the command line:

```bash
python et.py inject payment error             # inject a fault, wait ~60s
python et.py investigate "checkout error rate above 5% for 1m"
python et.py clear
```

Run the full evaluation (about 1 hour, mostly waiting for faults to show in telemetry):

```bash
python -m eval.run_eval            # writes results/runs/*.json and results/SCORECARD.md
python -m pytest -q tests          # offline tests: evidence gate, redaction, safety policy, topology
```

## Evaluation

### Results so far

**Standard set** (12 faults, 6 fault types; [`results/SCORECARD.md`](results/SCORECARD.md)):

| Method | Right service | Right service + fault type |
|---|---|---|
| **EvidenceTrail** | **12/12** | **12/12** |
| B0 single-prompt Gemini | 12/12 | 10/12 (called both bad deploys "code error") |
| B1 dashboard rule | 8/12 | n/a |

The evidence gate blocked 7 of 30 claims Gemini proposed (fabricated or misquoted citations).

**Hard set** (6 faults with red-herring log noise and silent faults; [`results/SCORECARD_HARD.md`](results/SCORECARD_HARD.md)):

| Method | Right service | Confident wrong answers |
|---|---|---|
| **EvidenceTrail** | **5/6** (plus 1 correct answer withheld as INCONCLUSIVE) | **0** |
| B0 single-prompt Gemini | 3/6 | 2 (including a service that does not exist) |
| B1 dashboard rule | 3/6 | 3 |

H03 and H05 were re-run after Google returned HTTP 503 "high demand" on every model. The first attempts are kept in `results/runs_hard_attempt1/`.


The scorecard compares three methods on the same faults, telemetry window and conditions:
- **B1, dashboard rule:** blame the service with the largest error-ratio (or p95) jump. This is how dashboard triage works.
- **B0, single-prompt Gemini:** the alert plus raw logs in one call, with no tools. This is "paste logs into a chat model".
- **EvidenceTrail.**

It reports top-1 and top-3 accuracy with 95% Wilson intervals, fault-type accuracy, inconclusive and failed counts, time, tokens, evidence precision and every individual scenario, misses included. See [`results/SCORECARD.md`](results/SCORECARD.md).

## Demo video

[`docs/demo/EvidenceTrail_demo.mp4`](docs/demo/EvidenceTrail_demo.mp4) (2:27): a live run on the test environment. A bad deploy of payment is injected, Gemini diagnoses it with cited evidence, and the rollback runs after a named approval. Subtitles: `docs/demo/EvidenceTrail_demo.srt`.

## Recording the demo video

`tools/record_demo.js` drives the real UI with Playwright against the live test environment: it injects a bad deploy, investigates, opens evidence and approves the rollback, with captions. `tools/cut_video.py` then speeds up the waiting parts with ffmpeg.

```bash
docker compose up -d --build && uvicorn evidencetrail.server:app --port 8080 &
cd tools && node record_demo.js && python cut_video.py   # writes EvidenceTrail_demo.mp4
```

## Limitations and known failure cases

- Injected faults are single-cause and cleaner than real incidents, which often have several interacting causes.
- ShopSim is small, and its telemetry volume is far below production. The agent filters and groups logs rather than sending everything, and context sizes are reported.
- Free-tier Gemini latency and availability vary with demand. Elapsed time includes back-off and fallback.
- The scenario set is small, so the confidence intervals are wide.
- This is a prototype. It is **not** autonomous operations and not production-ready. Diagnoses are hypotheses until an engineer confirms them.

## Data provenance

All telemetry is generated by this repository's own test environment. No production, employer or client data is used.
