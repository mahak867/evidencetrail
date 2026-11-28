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
| Google ADK engine (`ENGINE=adk`) | same model via ADK `LiteLlm` | `evidencetrail/adk_agent.py` |

The model actually used for each run is recorded in its result JSON. Override the defaults with `GEMINI_MODEL`, `GEMINI_FALLBACKS` and `GEMINI_REASONING`.

**Free-tier budget.** Some Gemini models allow only about 20 requests per day on the free tier. EvidenceTrail is designed around that: the health scan, call graph and the top suspects' logs, traces and changes are fetched *before* Gemini is called, so an investigation needs **1–4 Gemini calls** (median 2; median 8,282 tokens per investigation on the standard set, native engine). Gemini asks for more tools only when a hypothesis still needs testing.

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
       ─► 7. recovery check (read-only): after an approved action, the affected services must be
              back to their pre-incident baseline on 2 checks in a row, else "not confirmed"
```

The recovery check (`recovery.py`) compares each affected service (the action's target, the root cause and the alerted entry service) with the baseline from before the incident: error ratio within 2 points, p95 within 2× (at least 250 ms), reachable, and no single operation still failing. It waits at least 60 s so that 1-minute rates no longer include the incident, gives up after 4 minutes, and lists what is still off. The result is shown in the UI and written to the audit log.

Safety by design:
- Read-only telemetry access by default.
- Secrets, card numbers, emails and JWTs are redacted before anything reaches Gemini (`redact.py`; the payment service deliberately logs a fake API key to demonstrate this).
- Action risk is decided by an allow-list policy, never by the model (`safety.py`).
- Every approval, block and feedback event goes to `results/audit.log`.

## Integrations: MCP server and Google ADK

**MCP server.** EvidenceTrail is also a [Model Context Protocol](https://modelcontextprotocol.io) server, so Claude Code, Claude Desktop, Gemini CLI or any MCP agent can investigate incidents with the same read-only tools and the same evidence gate (`evidencetrail/mcp_server.py`).

```bash
claude mcp add evidencetrail -- python -m evidencetrail.mcp_server     # Claude Code
python -m evidencetrail.mcp_server --http 8765                         # streamable HTTP
```

Tools: `get_service_health`, `get_suspects`, `get_logs`, `get_metric`, `get_error_traces`, `get_recent_changes`, `investigate`. All are annotated read-only. The server never injects faults or executes actions; suggested actions are returned with their policy label only.

**Google ADK engine.** The investigation can run on Google's Agent Development Kit (`evidencetrail/adk_agent.py`). An ADK `LlmAgent` with Gemini (through ADK's `LiteLlm` connector to the Gemini API's OpenAI-compatible endpoint) and EvidenceTrail's tools runs the agent loop. The same evidence gate and safety policy then verify the result: **ADK proposes, EvidenceTrail verifies.** Select it with `ENGINE=adk`, `engine="adk"` in the MCP `investigate` tool, or `Investigation(engine="adk")`. The evaluation scores both engines on the same faults.

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

### Second target: the OpenTelemetry Demo (Round 2 work in progress)

EvidenceTrail also runs against the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) (Astronomy Shop), the OpenTelemetry community's reference microservices app, with services in Go, Java, C#, C++, Ruby, TypeScript/JavaScript, PHP and Rust. **The demo is a separate project under the Apache-2.0 licence; this repository does not include its code.** `otel/up.sh` fetches the version we tested (commit `3a53fdf`, 27 Nov 2026) and starts its core services with Jaeger, Prometheus and OpenSearch, plus only the overrides in `otel/compose.evidencetrail.yaml`.

| Part | Whose |
|---|---|
| The shop's services, load generator, flagd feature flags, OpenTelemetry Collector, Jaeger/Prometheus/OpenSearch setup | OpenTelemetry Demo (Apache-2.0), run unmodified |
| `evidencetrail/otel_demo.py`: reads span metrics, container CPU/memory, Jaeger v3 traces and OpenSearch logs; per-operation error and latency signals; "unreachable" detection from callers' failed calls | ours |
| Fault injection through the demo's flagd flags, with ground truth per flag (`evidencetrail/faults.py`), `eval/scenarios_otel.yaml`, `otel/` overrides and start script | ours |
| Investigator, evidence gate, safety policy, baselines, UI, MCP server | ours, unchanged; select the target with `TARGET=oteldemo` |

```bash
bash otel/up.sh                                # fetch + start the demo (about 25 containers)
export TARGET=oteldemo OTEL_DEMO_DIR=../opentelemetry-demo
uvicorn evidencetrail.server:app --port 8080   # same UI, now on the demo's telemetry
TARGET=oteldemo python -m eval.run_eval --set otel   # writes results/runs_otel and results/SCORECARD_OTEL.md
```

Injected faults (the demo's own flags; ground truth follows each flag's implementation in the demo source):

| Flag | Root cause | Fault type |
|---|---|---|
| `paymentFailure` | payment | code_error |
| `paymentUnreachable` | payment (checkout cannot reach it) | crash_or_unreachable |
| `cartFailure` | cart (fails `EmptyCart`) | code_error |
| `productCatalogFailure` | product-catalog (fails one product) | code_error |
| `adFailure` | ad | code_error |
| `adHighCpu` | ad | resource_exhaustion |
| `intlShippingSlowdown` | shipping (delays non-US orders) | latency |
| `recommendationCacheFailure` | recommendation (cache grows without bound) | resource_exhaustion |

Fairness: flag flips are **not** reported as "recent changes", because they are how faults are injected and would give every method the answer. All methods still share one frozen telemetry window.

**Status on 28 Nov 2026: Gemini has not been run on the demo yet**, so there are no EvidenceTrail diagnosis scores for it. The cloud environment used for the port does not have the Gemini key yet. What was checked is everything before the Gemini step, on one code version (commit `f90b691`), with one run per fault (120 s settle, 120 s fault, 120 s window):

| Check | Result |
|---|---|
| Right service ranked first by EvidenceTrail's topology suspects | **7 of 8** (missed `recommendationCacheFailure`: the leak took about 2.5 minutes to show and fell outside the window) |
| Right service named by the dashboard-rule baseline (B1) | 4 of 8 |
| Healthy system, 10 replayed 2-minute windows: windows with any false suspect | 1 of 10 (checkout p95 420 ms vs 98 ms baseline: a few slow orders at about 0.2 orders/s) |

Read this as a development check, not a result. The per-operation, CPU/memory and caller-edge signals were added after earlier runs missed some of these same 8 faults, so these numbers overstate how the method would do on new faults. The scored comparison (all four methods, misses included) will come from `TARGET=oteldemo python -m eval.run_eval --set otel`.

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

### Results (re-run 25 Nov 2026, after the code review fixes)

Every method investigates **one frozen 120-second telemetry window** per scenario; the deploy/config event log is reset between scenarios; the dashboard rule treats a service Prometheus cannot scrape (`up == 0`) as down. Raw runs are in `results/runs/` and `results/runs_hard/`.

**Standard set** (12 faults, 6 fault types; [`results/SCORECARD.md`](results/SCORECARD.md)):

| Method | Right service | Right service + fault type |
|---|---|---|
| **EvidenceTrail (native)** | **12/12** | **12/12** |
| **EvidenceTrail (Google ADK)** | 10/12 | 10/12 (S07, S08 lost to Gemini HTTP 503 on every model) |
| B0 single-prompt Gemini | 12/12 | 10/12 (called both bad deploys "code error") |
| B1 dashboard rule | 10/12 | n/a |

**Hard set** (6 faults with red-herring log noise and silent faults; [`results/SCORECARD_HARD.md`](results/SCORECARD_HARD.md)):

| Method | Right service | Confident wrong answers |
|---|---|---|
| **EvidenceTrail (native)** | **5/6** (+1 correct service withheld as INCONCLUSIVE) | **0** |
| **EvidenceTrail (Google ADK)** | **6/6** | **0** |
| B0 single-prompt Gemini | 4/6 | 2 (including a service that does not exist) |
| B1 dashboard rule | 5/6 | 1 |

Across all 18 faults: **0 confident wrong answers for EvidenceTrail** (both engines) vs 2 for single-prompt Gemini and 3 for the dashboard rule. The evidence gate blocked **9 of 80** claims across both engines. The native engine used 1–4 Gemini calls per incident (median 2) across all 18 runs. On the standard set, the native engine's median is 2 calls and 8,282 tokens per investigation; see `results/SCORECARD.md`.

H01, H02, H04, H05 and H06 were re-run because the first attempt hit Google Gemini HTTP 503 "high demand" on every model for at least one method; first attempts are kept in `results/runs_hard_attempt1/`. B1 was re-scored on each scenario's saved window with the `up` rule (`eval/rescore_b1.py`; B1 makes no model calls). Results from before the fixes are archived in `results/archive_v1/` with a note on what was wrong.

## Demo video

[`docs/demo/EvidenceTrail_demo.mp4`](docs/demo/EvidenceTrail_demo.mp4) (2:10): a live run on the test environment. A bad deploy of payment is injected, Gemini diagnoses it with cited evidence, and the rollback runs after a named approval. Subtitles: `docs/demo/EvidenceTrail_demo.srt`.

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

All telemetry is generated by this repository's own test environment, or by the OpenTelemetry Demo running locally with its own load generator. No production, employer or client data is used.
