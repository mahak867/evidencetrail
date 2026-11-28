"""Fill the official CODERED'26 template with EvidenceTrail content.
Keeps the template's backgrounds, titles and footer; replaces prompt text with content.
Reads evaluation results from the evidencetrail repo when available.
"""
import copy
import glob
import json
import math
import os
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

TEAM = os.environ.get("TEAM_NAME", "EvidenceTrail")
LEADER = os.environ.get("TEAM_LEADER", "Mahak Fahad")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# Contact details stay out of the public repo: put {"phone": "...", "email": "..."} in deck/team.local.json (gitignored).
CONTACT = json.load(open(os.path.join(HERE, "team.local.json"))) if os.path.exists(os.path.join(HERE, "team.local.json")) else {}
RUNS = ROOT + "/results/runs"
UI_SHOT = HERE + "/ui_crop.png"
VIDEO_FILE = ROOT + "/docs/demo/EvidenceTrail_demo.mp4"
POSTER = HERE + "/poster.png"
DEMO_URL = "https://evidencetrail.vercel.app/?tour=1"
VIDEO_URL = "https://drive.google.com/file/d/1uj3LoitDER3ILarIAnZZxmJnlDbtoqD7/view?usp=sharing"
REPO_URL = "https://github.com/mahak867/evidencetrail"
EMBED_VIDEO = os.environ.get("EMBED_VIDEO", "1") == "1"

WHITE, MUTED = RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0xB8, 0xB8, 0xC0)
GOLD, RED, GREEN, PURPLE = RGBColor(0xFF, 0xB5, 0x47), RGBColor(0xED, 0x20, 0x24), RGBColor(0x3F, 0xC9, 0x5A), RGBColor(0xB3, 0x7C, 0xFF)
CARD, CARD2, LINE = RGBColor(0x14, 0x14, 0x1A), RGBColor(0x1E, 0x1E, 0x26), RGBColor(0x3A, 0x3A, 0x46)
FONT = "Arial"
FS = 1.4  # template is 20in wide: scale sizes so they read like 14-16pt on a 13in slide


# ------------------------------------------------------------------ eval numbers
def wilson(k, n, z=1.96):
    if not n:
        return (0, 0)
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def eval_numbers():
    runs = [json.load(open(p)) for p in sorted(glob.glob(f"{RUNS}/S*.json"))]
    if not runs:
        return None
    out = {"n": len(runs), "types": len({r["truth"]["fault_type"] for r in runs})}
    for m in ("B1_dashboard_rule", "B0_single_prompt", "EvidenceTrail"):
        sc = [r["methods"].get(m, {}).get("score", {}) for r in runs]
        rs = [r["methods"].get(m, {}) for r in runs]
        k1 = sum(bool(s.get("top1")) for s in sc)
        typed = [s for s in sc if s.get("type_ok") is not None]
        times = sorted(x.get("elapsed_s") or 0 for x in rs)
        out[m] = {"top1": k1, "top3": sum(bool(s.get("top3")) for s in sc),
                  "type": (sum(bool(s["type_ok"]) for s in typed), len(typed)),
                  "inconc": sum(bool(s.get("inconclusive")) for s in sc), "ci": wilson(k1, len(runs)),
                  "median_s": times[len(times) // 2],
                  "tokens": sorted((x.get("usage") or {}).get("total_tokens", 0) for x in rs)[len(rs) // 2]}
    et = [r["methods"].get("EvidenceTrail", {}) for r in runs]
    calls = sorted((x.get("usage") or {}).get("calls", 0) for x in et)
    out["calls"] = (calls[0], calls[-1], calls[len(calls) // 2]) if calls else (0, 0, 0)  # upper median, as in SCORECARD.md
    out["kept"] = sum(len(x.get("claims") or []) for x in et)
    out["dropped"] = sum(len(x.get("dropped_claims") or []) for x in et)
    return out


EV = eval_numbers()


def hard_numbers():
    runs = [json.load(open(p)) for p in sorted(glob.glob(ROOT + "/results/runs_hard/H*.json"))]
    if not runs:
        return None
    out = {"n": len(runs)}
    for m in ("B1_dashboard_rule", "B0_single_prompt", "EvidenceTrail", "EvidenceTrail_ADK"):
        rs = [r["methods"].get(m, {}) for r in runs]
        sc = [x.get("score", {}) for x in rs]
        out[m] = {"right": sum(bool(s.get("top1")) for s in sc),
                  "wrong": sum(1 for x, s in zip(rs, sc) if x.get("verdict") == "DIAGNOSIS" and not s.get("top1")),
                  "abstain": sum(1 for x in rs if x.get("verdict") == "INCONCLUSIVE"),
                  "abstain_right": sum(1 for x, r in zip(rs, runs) if x.get("verdict") == "INCONCLUSIVE" and x.get("root_cause_service") == r["truth"]["service"])}
    return out


HV = hard_numbers()


def all_numbers():
    """Across both sets and both engines: confident wrong answers per method, gate totals, native call stats."""
    runs = [json.load(open(p)) for p in sorted(glob.glob(ROOT + "/results/runs/S*.json")) +
            sorted(glob.glob(ROOT + "/results/runs_hard/H*.json"))]
    out = {"n": len(runs)}
    for m in ("B1_dashboard_rule", "B0_single_prompt", "EvidenceTrail", "EvidenceTrail_ADK"):
        rs = [r["methods"].get(m, {}) for r in runs]
        out[m] = {"wrong": sum(1 for x in rs if x.get("verdict") == "DIAGNOSIS" and not x.get("score", {}).get("top1"))}
    eng = [r["methods"].get(m, {}) for r in runs for m in ("EvidenceTrail", "EvidenceTrail_ADK")]
    out["kept"] = sum(len(x.get("claims") or []) for x in eng)
    out["dropped"] = sum(len(x.get("dropped_claims") or []) for x in eng)
    calls = sorted((r["methods"].get("EvidenceTrail", {}).get("usage") or {}).get("calls", 0) for r in runs)
    out["calls"] = (calls[0], calls[-1], (calls[(len(calls) - 1) // 2] + calls[len(calls) // 2]) / 2)
    return out


AV = all_numbers()


def pct(k, n):
    return f"{round(100 * k / n)}%" if n else "–"


# ------------------------------------------------------------------ helpers
def remove(shape):
    shape._element.getparent().remove(shape._element)


def text(slide, x, y, w, h, runs, size=16, color=WHITE, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, name=None, spacing=4):
    """runs: str | list of paragraphs; each paragraph str or list of (text, opts) tuples."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(spacing)
        bullet = False
        if isinstance(para, dict):
            bullet, para = para.get("bullet", False), para["t"]
        segs = para if isinstance(para, list) else [(para, {})]
        if bullet:
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(Emu(Inches(0.22)))); pPr.set("indent", str(-Emu(Inches(0.22))))
            bu = pPr.makeelement(qn("a:buChar"), {"char": "•"})
            pPr.append(bu)
        for t, o in segs:
            r = p.add_run()
            r.text = t
            f = r.font
            f.name = FONT
            f.size = Pt(round(o.get("size", size) * FS, 1))
            f.bold = o.get("bold", bold)
            f.italic = o.get("italic", False)
            f.color.rgb = o.get("color", color)
            if o.get("link"):
                r.hyperlink.address = o["link"]
    return tb


def card(slide, x, y, w, h, fill=CARD, line=LINE, name=None, radius=0.06):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = radius
    s.fill.solid(); s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line; s.line.width = Pt(1)
    s.shadow.inherit = False
    if name:
        s.name = name
    return s


def pill(slide, x, y, w, h, label, fill, color=RGBColor(0, 0, 0), size=13):
    s = card(slide, x, y, w, h, fill=fill, line=None, radius=0.5)
    tf = s.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = label; r.font.size = Pt(size * FS); r.font.bold = True; r.font.name = FONT; r.font.color.rgb = color
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return s


def subtitle(slide, t):
    text(slide, 0.43, 1.55, 15.5, 0.6, t, size=24, bold=True, color=GOLD, name="Subtitle")


def arrow(slide, x1, y1, x2, y2, color=MUTED):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color; c.line.width = Pt(2)
    ln = c.line._get_or_add_ln()
    ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))
    return c


prs = Presentation(HERE + "/template.pptx")
S = list(prs.slides)
by = lambda s, txt: next(sh for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.startswith(txt))


def set_runs(shape, t, size=None, color=None):
    """Replace a template textbox's text, keeping its first run's formatting."""
    p = shape.text_frame.paragraphs[0]
    for extra in shape.text_frame.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    runs = p.runs
    runs[0].text = t
    for r in runs[1:]:
        r._r.getparent().remove(r._r)
    if size:
        runs[0].font.size = Pt(size)
    if color:
        runs[0].font.color.rgb = color


for sl in S:
    for sh in sl.shapes:
        if sh.has_text_frame and sh.text_frame.text.startswith("IDEA/APPROACH"):
            sh.width = Inches(15)
        if sh.has_text_frame and sh.text_frame.text.startswith("CODERED"):
            sh.left, sh.width = Inches(16.0), Inches(3.4)
            sh.top = Inches(10.45)

# ================================================================== slide 1
s = S[0]
title = by(s, "Soultion")
set_runs(title, "Solution Outline / Objective", size=60)
title.top, title.width = Inches(2.1), Inches(17)
for lbl in ("Track Name", "Team Name", "Team Leader"):
    remove(by(s, lbl))
text(s, 1.54, 4.45, 12.5, 1.0, [[("EvidenceTrail", {"size": 54, "bold": True, "color": GOLD})]], name="Product")
text(s, 1.54, 5.7, 12.5, 0.6, "Find the cause. Show the evidence.", size=26, color=WHITE, name="Tagline")
text(s, 1.54, 6.75, 13.5, 2.4, [
    [("Track Name & Idea Number:  ", {"bold": True, "color": MUTED}), ("Track 1 – Niveus Solutions (NTT DATA) · Challenge Brief PS2: AI Incident Investigation for Cloud-Native Systems", {})],
    [("Team Name:  ", {"bold": True, "color": MUTED}), (TEAM, {})],
    [("Team Leader Name:  ", {"bold": True, "color": MUTED}), (LEADER, {})],
    [("Objective:  ", {"bold": True, "color": MUTED}), ("help an on-call engineer reach a correct, evidence-backed root cause, with fewer confident wrong answers than a single AI prompt and a human in charge of every fix.", {})],
], size=17, spacing=8, name="Outline")
text(s, 1.54, 9.6, 17.5, 0.5, [[("Live demo: ", {"bold": True, "color": GREEN}), ("evidencetrail.vercel.app", {"link": DEMO_URL, "color": WHITE}),
    ("   ·   ", {"color": MUTED}), ("Demo video", {"link": VIDEO_URL, "color": WHITE, "bold": True}),
    ("   ·   ", {"color": MUTED}), ("Code: ", {"bold": True, "color": GREEN}), ("github.com/mahak867/evidencetrail", {"link": REPO_URL, "color": WHITE})]], size=12.5, name="Links")

# ================================================================== slide 2
s = S[1]
remove(by(s, "Describe your idea"))
subtitle(s, "A Gemini incident investigator with one rule: no evidence, no claim")
# problem column
card(s, 0.43, 2.35, 6.1, 7.4, name="ProblemCard")
text(s, 0.75, 2.6, 5.5, 0.5, "THE PROBLEM", size=15, bold=True, color=RED)
text(s, 0.75, 3.15, 5.5, 1.6, [
    "One fault makes alerts fire in many services. Dashboards show symptoms, not causes.",
    "AI summaries without evidence can't be trusted mid-incident.",
], size=15, spacing=8)
stats = [("11.3%", "best AI agent's root-cause accuracy on OpenRCA (Claude 3.5 + RCA-Agent)"),
         ("7–40%", "of root causes hallucinated by 5 frontier AI agents (ORCA-bench)")]
for i, (big, lbl) in enumerate(stats):
    y = 5.35 + i * 1.45
    text(s, 0.75, y, 2.9, 0.9, big, size=36, bold=True, color=GOLD)
    text(s, 3.65, y + 0.05, 2.7, 1.3, lbl, size=12, color=MUTED)
text(s, 0.75, 8.95, 5.6, 0.8, "Sources: OpenRCA, Xu et al., ICLR 2025 (335 failures, 3 systems); ORCA-bench, Gong et al., arXiv 2607.28545 (2026).", size=10, color=MUTED)
# solution steps
text(s, 6.95, 2.35, 7, 0.5, "HOW EVIDENCETRAIL WORKS", size=15, bold=True, color=GREEN)
steps = [("1", "Scan", "Error ratio and p95 latency per service vs a baseline window (Prometheus)"),
         ("2", "Walk the call graph", "Traces show who calls whom; the deepest failing service is the suspect, callers are victims"),
         ("3", "Test hypotheses", "Gemini proposes causes and runs read-only queries on logs, metrics, traces and recent changes"),
         ("4", "Evidence gate", "Claims citing evidence never fetched, or misquoting it, are blocked; weak evidence → INCONCLUSIVE"),
         ("5", "Human in charge", "Engineer confirms or rejects; any fix is policy-labelled safe/risky, dry-run first, run only on approval")]
for i, (n, h, d) in enumerate(steps):
    y = 2.95 + i * 1.4
    card(s, 6.95, y, 7.6, 1.28, fill=CARD2)
    pill(s, 7.15, y + 0.36, 0.56, 0.56, n, GOLD, size=16)
    text(s, 7.95, y + 0.14, 6.4, 0.4, h, size=16, bold=True)
    text(s, 7.95, y + 0.52, 6.45, 0.6, d, size=12.5, color=MUTED)
# use cases
text(s, 15.0, 2.35, 4.6, 0.5, "USE CASES", size=15, bold=True, color=PURPLE)
uses = [("On-call triage", "SaaS, fintech and e-commerce teams on Kubernetes / Cloud Run"),
        ("Managed services", "Systems integrators running many client platforms under SLAs"),
        ("Postmortems", "Timeline where every line links to its source"),
        ("Training", "Juniors see how the cause was found, not just the answer")]
for i, (h, d) in enumerate(uses):
    y = 2.95 + i * 1.75
    card(s, 15.0, y, 4.55, 1.6, fill=CARD2)
    text(s, 15.25, y + 0.18, 4.1, 0.4, h, size=16, bold=True)
    text(s, 15.25, y + 0.6, 4.1, 0.8, d, size=12.5, color=MUTED)

# ================================================================== slide 3
s = S[2]
remove(by(s, "Describe your Technology"))
subtitle(s, "Technology stack, dependencies and show-stoppers")
stack = [
    ("AI", GOLD, ["Gemini (3.1 Flash-Lite + 4 fallback models)", "Two engines: native loop or Google ADK", "MCP server for Claude / Gemini CLI",
                  (f"{EV['calls'][0]}–{EV['calls'][1]} Gemini calls per incident (median {EV['calls'][2]:g})" if EV else "Gemini calls per incident measured")]),
    ("Telemetry", GREEN, ["OpenTelemetry SDK → Jaeger (traces)", "Prometheus (metrics)", "JSON logs with trace IDs + change/event log"]),
    ("Test system", PURPLE, ["9-service shop on Docker Compose", "7 reproducible fault types", "Load generator; OpenTelemetry Demo next"]),
    ("App", RGBColor(0x4F, 0x9C, 0xF9), ["Python, FastAPI, httpx", "Web UI: diagnosis + clickable evidence", "Audit log of every approval"]),
]
for i, (h, col, items) in enumerate(stack):
    x = 0.43 + i * 3.42
    card(s, x, 2.35, 3.22, 3.75, fill=CARD2)
    text(s, x + 0.25, 2.55, 2.8, 0.45, h, size=18, bold=True, color=col)
    text(s, x + 0.25, 3.1, 2.8, 2.4, [{"t": t, "bullet": True} for t in items], size=13, color=WHITE, spacing=6)
text(s, 14.3, 2.35, 5.3, 0.45, "SAFETY BUILT IN", size=15, bold=True, color=GREEN)
text(s, 14.3, 2.85, 5.25, 2.8, [{"t": t, "bullet": True} for t in [
    "Read-only telemetry access by default",
    "Secrets, card numbers, emails redacted before Gemini sees logs",
    "Action risk decided by an allow-list policy, never by the model",
    "Keys server-side only; own test environment only"]], size=13, spacing=6)
text(s, 0.43, 6.45, 10, 0.45, "DEPENDENCIES & SHOW-STOPPERS → MITIGATION", size=15, bold=True, color=RED)
risks = [("Gemini free-tier limits / 503 \"high demand\"", "Bounded retries with back-off, automatic model fallback, clear FAILED state, token cost logged"),
         ("Telemetry too big for the context window", "Scan + call graph narrow it first; logs grouped by pattern; prompt tokens reported per run"),
         ("Injected faults are cleaner than real incidents", "Stated openly; multi-fault and OpenTelemetry Demo scenarios added in Round 2"),
         ("No Kubernetes cluster on student laptops", "Docker Compose (allowed by the brief); kind/minikube optional later")]
for i, (r, m) in enumerate(risks):
    y = 7.0 + i * 0.75
    card(s, 0.43, y, 19.1, 0.62, fill=CARD)
    text(s, 0.7, y + 0.15, 6.6, 0.4, r, size=13, bold=True)
    text(s, 7.5, y + 0.15, 11.9, 0.4, m, size=13, color=MUTED)

# ================================================================== slide 4
s = S[3]
remove(by(s, "Novelty"))
subtitle(s, "Novelty, market and revenue model")
text(s, 0.43, 2.35, 6.4, 0.45, "WHAT'S NEW", size=15, bold=True, color=GOLD)
nov = [("No evidence, no claim", "enforced citation gate + INCONCLUSIVE instead of guessing"),
       ("Hypotheses tested, not guessed", "candidate causes checked against real telemetry before a verdict"),
       ("Topology-first", "follows the call graph to the deepest failure"),
       ("Guarded actions", "policy-labelled, dry-run, named human approval"),
       ("Open integration", "MCP server for Claude / Gemini CLI; runs on Google ADK"),
       ("Public scorecard", "every fault reported, misses included")]
text(s, 0.43, 2.9, 6.4, 5, [[(h + ": ", {"bold": True}), (d, {"color": MUTED})] for h, d in nov], size=14, spacing=10)
# results
card(s, 7.1, 2.35, 6.0, 7.5, fill=CARD2, name="ResultsCard")
text(s, 7.4, 2.55, 5.5, 0.45, "PROTOTYPE RESULTS (MEASURED)", size=15, bold=True, color=GREEN)
if EV:
    text(s, 7.4, 3.0, 5.5, 0.4, f"{EV['n']} injected faults · {EV['types']} fault types", size=12, color=MUTED)
    rows = [("EvidenceTrail", EV["EvidenceTrail"], GREEN), ("Single-prompt Gemini", EV["B0_single_prompt"], GOLD), ("Dashboard rule", EV["B1_dashboard_rule"], MUTED)]
    for i, (lbl, d, col) in enumerate(rows):
        y = 3.5 + i * 1.18
        text(s, 7.4, y, 5.5, 0.4, lbl, size=13, bold=True, color=WHITE)
        for j, (k, n, sub) in enumerate(((d["top1"], EV["n"], "service"), (d["type"][0], d["type"][1], "service + fault type"))):
            yy = y + 0.38 + j * 0.34
            if not n:
                text(s, 7.4, yy, 5.4, 0.3, f"{sub}: n/a (rule gives no fault type)", size=10.5, color=MUTED)
                continue
            w = 2.6 * k / n
            card(s, 7.4, yy + 0.04, 2.6, 0.22, fill=CARD, line=None, radius=0.3)
            if w > 0.03:
                card(s, 7.4, yy + 0.04, w, 0.22, fill=col, line=None, radius=0.3)
            text(s, 10.15, yy, 2.8, 0.3, [[(f"{k}/{n}", {"bold": True}), (f"  {sub}", {"color": MUTED})]], size=11)
    y2 = 7.1
    if HV and HV["n"] >= 6:
        et, adk, b0 = HV["EvidenceTrail"], HV["EvidenceTrail_ADK"], HV["B0_single_prompt"]
        text(s, 7.4, y2, 5.5, 1.3, [
            [("Hard set ", {"bold": True, "color": GOLD}), (f"(noisy logs, silent faults, n={HV['n']}): ", {"color": MUTED})],
            [("Right service: ", {"color": MUTED}), (f"ADK {adk['right']}/{HV['n']}, native {et['right']}/{HV['n']}", {"bold": True, "color": GREEN}),
             (f" (+{et['abstain']} abstained)" if et["abstain"] else "", {"color": MUTED}), (f" vs single-prompt {b0['right']}/{HV['n']}", {"bold": True})],
        ], size=11.5, spacing=3)
        y2 += 0.95
    text(s, 7.4, y2, 5.5, 1.6, [
        [("Confident wrong answers, all ", {"color": MUTED}), (f"{AV['n']}", {"color": MUTED}), (" faults: ", {"color": MUTED}),
         (f"EvidenceTrail {AV['EvidenceTrail']['wrong'] + AV['EvidenceTrail_ADK']['wrong']}", {"bold": True, "color": GREEN}),
         (f" · single prompt {AV['B0_single_prompt']['wrong']} · dashboard {AV['B1_dashboard_rule']['wrong']}", {"bold": True})],
        [(f"{AV['dropped']} of {AV['kept'] + AV['dropped']}", {"bold": True, "color": GOLD}), (" AI claims blocked by the evidence gate (both engines)", {"color": MUTED})],
    ], size=11.5, spacing=4)
else:
    text(s, 7.4, 3.2, 5.5, 3, "Evaluation in progress: 12 injected faults × 3 methods.", size=15, color=MUTED)
# market + revenue
text(s, 13.45, 2.35, 6.1, 0.45, "MARKET & COMPETITION", size=15, bold=True, color=PURPLE)
text(s, 13.45, 2.85, 6.1, 3.0, [
    {"t": [("Users: ", {"bold": True}), ("on-call / SRE / platform teams at Indian SaaS, fintech, e-commerce, and systems integrators like NTT DATA", {"color": MUTED})]},
    {"t": [("Rivals: ", {"bold": True}), ("Resolve AI, Datadog Bits AI SRE, Azure SRE Agent: closed products (Resolve's 95% is self-reported); Gemini Cloud Assist: Google Cloud-only; k8sgpt / HolmesGPT: open source, Kubernetes-focused", {"color": MUTED})]},
    {"t": [("Our edge: ", {"bold": True}), ("every miss published, evidence on every claim, OpenTelemetry-based, usable from Claude / Gemini CLI via MCP", {"color": MUTED})]},
], size=13, spacing=8)
text(s, 13.45, 6.5, 6.1, 0.45, "REVENUE MODEL", size=15, bold=True, color=GOLD)
text(s, 13.45, 7.0, 6.1, 2.8, [
    {"t": [("Open core: ", {"bold": True}), ("free self-hosted investigator drives adoption", {"color": MUTED})], "bullet": True},
    {"t": [("Team plan: ", {"bold": True}), ("per-cluster monthly subscription: history, approvals, audit, SSO", {"color": MUTED})], "bullet": True},
    {"t": [("MSP licence: ", {"bold": True}), ("per-client pricing for systems integrators", {"color": MUTED})], "bullet": True},
    {"t": [("Unit cost: ", {"bold": True}), (f"~{EV['EvidenceTrail']['tokens']:,} Gemini tokens per investigated incident (median, measured)" if EV else "Gemini tokens per incident measured in every run", {"color": MUTED})], "bullet": True},
], size=13, spacing=6)

# ================================================================== slide 5
s = S[4]
remove(by(s, "Add a process flow"))
subtitle(s, "Process flow: from alert to approved action")
boxes = [("Alert", "SLO burn / 5xx / p95", RED), ("Health scan", "Prometheus vs baseline", GOLD), ("Call graph", "Jaeger traces → suspects", GOLD),
         ("Gemini agent", "native loop or Google ADK", GREEN), ("Evidence gate", "cited or INCONCLUSIVE", GREEN), ("Engineer", "confirm / correct / reject", PURPLE)]
bw, gap, y0 = 2.85, 0.42, 2.45
for i, (h, d, col) in enumerate(boxes):
    x = 0.43 + i * (bw + gap)
    b = card(s, x, y0, bw, 1.35, fill=CARD2, line=col)
    text(s, x + 0.2, y0 + 0.2, bw - 0.4, 0.45, h, size=17, bold=True, color=col, align=PP_ALIGN.CENTER)
    text(s, x + 0.2, y0 + 0.72, bw - 0.4, 0.5, d, size=12, color=MUTED, align=PP_ALIGN.CENTER)
    if i < len(boxes) - 1:
        arrow(s, x + bw + 0.04, y0 + 0.67, x + bw + gap - 0.04, y0 + 0.67)
# tools row under agent
tools = ["get_logs", "get_metric", "get_error_traces", "get_slow_traces", "get_recent_changes"]
tx = 0.43 + 3 * (bw + gap)
arrow(s, tx + bw / 2, y0 + 1.4, tx + bw / 2, y0 + 1.85, color=GREEN)
card(s, 5.4, y0 + 1.9, 9.3, 1.3, fill=CARD)
text(s, 5.6, y0 + 2.05, 8.9, 1.1, [[("Read-only tools: ", {"bold": True, "color": GREEN}), ("  ·  ".join(tools), {"color": WHITE})],
                                   [("Telemetry from: ", {"bold": True, "color": GREEN}), ("Prometheus · Jaeger · logs · deploy events, redacted", {"color": MUTED})]], size=12.5, spacing=2)
ex = 0.43 + 5 * (bw + gap)
arrow(s, ex + bw / 2, y0 + 1.4, ex + bw / 2, y0 + 1.85, color=PURPLE)
card(s, 15.65, y0 + 1.9, 3.9, 1.3, fill=CARD, line=PURPLE)
text(s, 15.85, y0 + 2.05, 3.5, 1.1, [[("Suggested fix", {"bold": True, "color": PURPLE})], [("safe / risky label → dry run → named approval", {"color": MUTED})]], size=12.5, spacing=2)
# eval loop + screenshot
card(s, 0.43, 5.75, 7.4, 4.15, fill=CARD)
text(s, 0.7, 5.95, 7, 0.45, "REPEATABLE EVALUATION LOOP", size=15, bold=True, color=GOLD)
text(s, 0.7, 6.45, 6.9, 3.3, [{"t": t, "bullet": True} for t in [
    "Inject a known fault into the 9-service shop (error, latency, crash, memory leak, DB pool, bad config, bad deploy)",
    "One frozen 120-second telemetry window shared by every method",
    "Score top-1 / top-3 service, fault type, time, tokens, evidence precision",
    "Every scenario reported, misses included"]], size=13, spacing=6)
vh, vw = 4.15, 4.15 * 1440 / 900
if EMBED_VIDEO and os.path.exists(VIDEO_FILE):
    mv = s.shapes.add_movie(VIDEO_FILE, Inches(8.15), Inches(5.75), Inches(vw), Inches(vh), poster_frame_image=POSTER, mime_type="video/mp4")
    mv.name = "Demo video"
else:
    mv = s.shapes.add_picture(POSTER, Inches(8.15), Inches(5.75), Inches(vw), Inches(vh)); mv.name = "Demo video poster"
    mv.click_action.hyperlink.address = VIDEO_URL
qx = 8.15 + vw + 0.3
text(s, qx, 5.75, 19.55 - qx, 0.45, "TRY IT", size=15, bold=True, color=GOLD)
text(s, qx, 6.2, 19.55 - qx, 0.9, [[("Live demo (recorded data), 2:10 video of a live run, and the full code.", {"color": MUTED})]], size=11.5)
qs = [("qr_demo.png", "Live demo", DEMO_URL), ("qr_video.png", "Video", VIDEO_URL), ("qr_repo.png", "GitHub", REPO_URL)]
qw = (19.55 - qx - 0.3) / 3
for i, (img, lbl, url) in enumerate(qs):
    x = qx + i * (qw + 0.15)
    q = s.shapes.add_picture(f"{HERE}/{img}", Inches(x), Inches(7.25), Inches(qw), Inches(qw))
    q.name = f"QR {lbl}"; q.click_action.hyperlink.address = url
    text(s, x, 7.3 + qw, qw, 0.4, [[(lbl, {"bold": True, "link": url, "color": WHITE})]], size=11.5, align=PP_ALIGN.CENTER)

# ================================================================== slide 6
s = S[5]
vals = {"Team Leader": [("Team Leader Name:  ", {"bold": True}), ("Mahak Fahad", {"bold": True, "color": GOLD}), ("  ·  AI / Backend lead: Gemini agent, evidence gate, API", {"color": MUTED})],
        "Member 1": [("Member 1 Name:  ", {"bold": True}), ("Roshini R", {"bold": True, "color": GOLD}), ("  ·  Frontend & UI/UX lead: investigation console, design", {"color": MUTED})],
        "Member 2": [("Member 2 Name:  ", {"bold": True}), ("Kanish Karthikeyan", {"bold": True, "color": GOLD}), ("  ·  Platform & observability: test env, faults, telemetry", {"color": MUTED})],
        "Member 3": [("Member 3 Name:  ", {"bold": True}), ("Annika Meril Babu", {"bold": True, "color": GOLD}), ("  ·  Evaluation, research & pitch: scorecard, market", {"color": MUTED})],
        "Phone": [("Phone Number:  ", {"bold": True}), (CONTACT.get("phone", "<phone: set deck/team.local.json>") + " (team leader)", {})],
        "Email": [("Email ID:  ", {"bold": True}), (CONTACT.get("email", "<email: set deck/team.local.json>"), {})]}
order = ["Team Leader", "Member 1", "Member 2", "Member 3", "Phone", "Email"]
for i, k in enumerate(order):
    remove(by(s, k))
    text(s, 2.44, 4.2 + i * 0.72 + (0.3 if i >= 4 else 0), 16.5, 0.6, [vals[k]], size=17, name=k)
text(s, 2.44, 9.25, 16, 0.5, "All members: B.E. Computer Science and Engineering (batch of 2029), Chennai Institute of Technology, Chennai", size=13, color=MUTED)
by(s, "TEAM").width = Inches(15)
by(s, "TEAM").top = Inches(1.9)

out = sys.argv[1] if len(sys.argv) > 1 else HERE + "/EvidenceTrail_CODERED26_Round1.pptx"
prs.save(out)
print("saved", out, "eval:", bool(EV))
