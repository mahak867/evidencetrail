# EvidenceTrail: handoff for the next engineer (or AI session)

Read this first, then `README.md`. Everything here can be checked against the code.
Strategy, rival analysis and team contacts are **not** in this public repo. The team keeps them in a private bundle (`HANDOFF_PRIVATE.md`).

## 1. What this is

CODERED '26 (E-Cell BMSIT&M, Bengaluru, on Unstop), **Track 1 · Niveus Solutions (NTT DATA) · Challenge Brief PS2: AI Incident Investigation for Cloud-Native Systems**.

| Stage | Date | Format | Status |
|---|---|---|---|
| Round 1 | deadline extended to 30 Nov 2026, 11:59 PM IST (was 27 Nov) | Deck (official template) + demo video | Submitted files: `deck/` builds the deck; video in `docs/demo/` |
| Round 2 | 12–13 Dec 2026 | Online live demo | **Next** |
| Finale | 28–29 Dec 2026, BMSIT&M (the Niveus brief says 3–4 Dec; confirm with the organisers) | 24-hour on-site sprint | |

**Product:** a Google Gemini incident investigator with one rule: *no evidence, no claim*. Every claim must cite a log line, trace or metric that was actually fetched, with a quote that matches the source. Otherwise the claim is blocked, or the verdict is INCONCLUSIVE. Fixes are labelled by policy (safe/risky/blocked), shown as a dry run, and need a named human approval.

Links: live static demo https://evidencetrail.vercel.app (`?tour=1` starts the captioned guided tour) · repo https://github.com/mahak867/evidencetrail · video: `docs/demo/EvidenceTrail_demo.mp4` (2:10, captions burned in) and the team's Drive link (in the deck).

## 2. Repository map

| Path | What |
|---|---|
| `shop/` | ShopSim test environment: 9 FastAPI services (frontend, checkout, catalog, recommendation, cart, payment, shipping, currency, inventory) + load generator. Fault admin at `/admin/fault` and `/admin/noise`. Fault kinds: error, latency (optionally silent), crash, memory_leak (capped 300 MB), pool_exhaustion, bad_config, bad_deploy, noise. JSON logs to `logs/*.log`, deploy/config events to `logs/events.log`. Python wheels vendored in `shop/wheels/` (gitignored; pip was unreachable inside Docker builds). |
| `docker-compose.yml` | Shop + Jaeger (traces, OTLP) + Prometheus (metrics; `instance_service` relabel). |
| `evidencetrail/telemetry.py` | Prometheus/Jaeger/log queries. `service_health` includes Prometheus `up` (down = missing or up==0). |
| `evidencetrail/investigator.py` | `Investigation` dataclass. Pipeline: health scan → call graph from Jaeger → `suspects()` (deepest anomaly) → parallel prefetch (ThreadPoolExecutor: top-3 suspects' ERROR/WARN logs, error traces via the entry service, recent changes) → `_fit()` JSON trimming (PROMPT_BUDGET 30000, TOOL_BUDGET 6000) → Gemini tool loop (`max_steps=4`) → `submit_diagnosis` → evidence gate → root cause must be backed by a kept claim. `engine="native"` or `"adk"`. |
| `evidencetrail/gemini.py` | OpenAI-compatible Gemini endpoint, model fallbacks, 2-pass retry (`GEMINI_PASSES`, `GEMINI_PASS_WAIT_S`), token accounting. |
| `evidencetrail/adk_agent.py` | Same investigation on Google ADK (`LlmAgent` + `LiteLlm("openai/<model>")`). |
| `evidencetrail/evidence.py` | `quote_supported` (punctuation/space tolerant, ≥85% of words in order) and `gate`. |
| `evidencetrail/safety.py`, `redact.py` | Action policy and dry run; secret/card/email redaction before Gemini. |
| `evidencetrail/baselines.py` | B0 single Gemini prompt with raw logs; B1 dashboard rule. Both take the same frozen window. |
| `evidencetrail/mcp_server.py` | MCP server (mcp 2.3, `MCPServer`): read-only tools get_service_health, get_suspects, get_logs, get_metric, get_error_traces, get_recent_changes, investigate. stdio by default, `--http` option. |
| `evidencetrail/server.py` | FastAPI app serving `ui/index.html` and `/api/*` (health, series, investigate, faults, scorecard.json, recorded, audit, meta). |
| `eval/run_eval.py` | Evaluation: one frozen telemetry window shared by B1, B0, EvidenceTrail and EvidenceTrail_ADK; `--set standard|hard`, `--only S03`, `--report-only`. Failed runs count as misses. Wilson 95% intervals. `eval/rescore_b1.py` re-scores B1 offline on saved windows. |
| `eval/scenarios.yaml`, `scenarios_hard.yaml` | 12 standard + 6 hard (noisy logs, silent faults) scenarios. |
| `results/` | `SCORECARD.md`, `SCORECARD_HARD.md`, raw runs (`runs/`, `runs_hard/`), `archive_v1/` (older, flawed runs, kept with a README that explains why). |
| `ui/index.html` | Single-file UI (no build step). Views: Investigate, Service map, Scorecard, Integrations, Audit log. Key functions: `topology()` (layered service map), `openSvc` (detail drawer), `timeline`, `egraph`, `heatmap`, `drawScore`. |
| `tools/build_site.py` + `build_site_data.py` | Build the static Vercel site in `site/` from `ui/index.html` + recorded data (`site/data/*.json`), injecting `site/static-shim.js` (fakes `/api` from JSON) and `site/tour.js` (16-step captioned guided demo). |
| `tools/record_demo.js`, `tools/cut_video.py` | Record the demo video with Playwright against the live system, then cut it with ffmpeg (fast-forwards waits, writes SRT). |
| `deck/` | Round 1 deck generator (python-pptx on the official template). Contact details come from `deck/team.local.json` (gitignored): `{"phone": "...", "email": "..."}`. |
| `tests/test_core.py` | 12 unit tests (`python3 -m pytest -q tests`). |
| `et.py` | CLI entry point. |

## 3. Run it

```bash
pip install -r requirements.txt
docker compose up -d --build
GEMINI_API_KEY=<key> uvicorn evidencetrail.server:app --port 8080   # http://localhost:8080
```

Environment variables: `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.1-flash-lite`), `GEMINI_FALLBACKS`, `GEMINI_REASONING`, `GEMINI_PASSES`, `GEMINI_PASS_WAIT_S`, `GEMINI_BASE_URL`, `ENGINE` (`native`|`adk`), `PROM_URL`, `JAEGER_URL`, `LOG_DIR`.

```bash
python3 -m pytest -q tests
python3 eval/run_eval.py --set standard            # ~1 Gemini quota-day; free tier has 503 spells
python3 eval/run_eval.py --set hard
python3 tools/build_site.py                        # rebuild site/ after any ui/index.html change
cd site && python3 -m http.server 8090             # preview the static site
```

Deck: `cd deck && python3 build_deck.py` (writes `EvidenceTrail_CODERED26_Round1.pptx`; `EMBED_VIDEO=0` to link instead of embed). `render.sh` needs `PPTX_SKILL` pointing at the Claude pptx skill (soffice + validate.py).

Video: start the stack and server, then `cd deck && node record_demo.js && python3 ../tools/cut_video.py` (~10 minutes; it retries the investigation up to 3 times if the diagnosis is wrong).

### Claude Code cloud-session notes (what bit us)
- Start `dockerd` inside a bounded command and stop it when done. Background jobs are killed after 2 hours, which took dockerd down mid-run.
- `ghcr.io` pulls were blocked in our environment, so the official OpenTelemetry Demo images could not be pulled; Docker Hub works. This blocks the Round 2 OTel Demo port unless mirrors or another network policy are used.
- The Gemini key lived as an environment network secret for `generativelanguage.googleapis.com` (injected as `Authorization: Bearer`), so the code ran with `GEMINI_API_KEY=proxy-injected`.
- Gemini free tier: 503 "high demand" spells; some models are capped at about 20 requests/day. The fallback chain handles this; budget the eval runs.
- Big heredocs can trip the shell safety check: write scripts to a scratch file, then run them.
- Commits are authored as the team leader. **Do not add Claude as a co-author or contributor** (team instruction).
- Vercel project `evidencetrail`, root directory `site/`, auto-deploys on push to `main`. Production is public; previews are SSO-protected.

## 4. Measured results (from `results/`, 25 Nov 2026 re-run)

- Standard set (12 faults, 6 types): EvidenceTrail 12/12 right service and 12/12 fault type. Single Gemini prompt: 12/12 service, 10/12 fault type. Dashboard rule: 10/12 service, no fault type.
- Hard set (6): right service ADK 6/6, native 5/6 (+1 abstained), single prompt 4/6.
- Confident wrong answers across all 18: EvidenceTrail 0, single prompt 2, dashboard rule 3.
- Evidence gate blocked 9 of 80 AI claims (both engines).
- Cost: 1–4 Gemini calls per incident.
- **Check before reusing numbers:** the README says median 2.5 calls and ~8.8k tokens; the deck says median 2 and ~8,282 tokens; `SCORECARD.md` says ~7,569 tokens/incident on the standard set. They come from different subsets (standard only vs all 18 runs, native vs ADK). Pick one definition and make all three agree.

External statistics used in the deck: OpenRCA 11.34% best-agent root-cause accuracy (ICLR 2025); ORCA-bench 7–40% hallucinated root causes (arXiv 2607.28545).

## 5. Known weaknesses (be honest about these in Q&A)
1. The test shop is our own, and its logs make the fault fairly easy to find. Injected faults are cleaner than real incidents.
2. A single Gemini prompt also gets 12/12 service on the standard set. The edge is fault type, hard-set accuracy, 0 confident wrong answers and blocked claims.
3. No Google Cloud deployment yet (Niveus is a Google Cloud partner).
4. Slower than one prompt (several tool steps).
5. No real users or SRE feedback yet (`deck/SRE_feedback_kit.md` has the interview kit).

## 6. Round 2 plan (12–13 Dec), in priority order
1. **Port to the OpenTelemetry Demo** (Astronomy Shop). Use its flagd feature flags for faults (e.g. `paymentFailure`, `cartFailure`, `productCatalogFailure`, `adHighCpu`, `kafkaQueueProblems`; check `src/flagd/demo.flagd.json` for the current names). Adapt `telemetry.py` service names and queries; keep ShopSim as a fallback.
2. **Run the same baseline comparison on the OTel Demo** and publish it. This comparison is the one thing comparable projects do not show; make it the headline.
3. **Deploy on Google Cloud Run** (investigator + UI; telemetry backends on a small VM or GKE Autopilot).
4. **Verify recovery after a fix** and **auto-generate a postmortem** from the timeline (claims must cite evidence).
5. Rehearse a 5–7 minute live demo with the recorded replay (`/api/recorded`, static site) as the backup if Gemini is overloaded.
6. Optional: one feature beyond the field, such as incident memory (match past incidents) or opening the fix as a pull request.

Team roles for the demo: problem + results (Annika), live UI (Roshini), live fault injection and test environment (Kanish), agent and evidence gate + technical Q&A (Mahak).

## 7. Useful Claude skills and tools for this work
- `dataviz` skill: chart palette and validator (the UI palette was validated with it: blue #2a78d6/#3987e5, orange #eb6834/#d95926, aqua #1baf7a/#199e70; the ADK series uses hatching, not a fourth hue).
- `pptx` skill: `validate.py --original template.pptx`, soffice rendering.
- `code-review` skill at medium/high before each push; `run` skill to launch and screenshot the app.
- Playwright + Chromium for screenshots and video (`require('playwright')`, `chromium.launch()`).
- Vercel MCP for deployment checks; Google Drive MCP to check the video link's version and sharing.
