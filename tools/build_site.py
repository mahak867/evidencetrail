"""Build the static recorded demo (site/index.html) from the live UI (ui/index.html)."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
VIDEO = "/demo.mp4"
REPO = "https://github.com/mahak867/evidencetrail"
s = (ROOT / "ui/index.html").read_text()
banner = f'''<div id="staticbar" style="position:sticky;top:0;z-index:15;display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:9px 16px;background:var(--surface);border-bottom:1px solid var(--hair);font-size:13px">
  <span class="status st-warning"><span class="sw"></span>Recorded demo</span>
  <span class="ink2">The real EvidenceTrail UI, replaying data captured from our live test environment (Investigate replays at 4× speed). Live investigations run locally.</span>
  <span style="margin-left:auto;display:flex;gap:8px"><a class="chip" href="{VIDEO}" target="_blank" rel="noopener">▶ Demo video</a><a class="chip" href="{REPO}" target="_blank" rel="noopener">GitHub</a></span></div>'''
reps = [
    ('<div class="shell">', banner + '\n<div class="shell">'),
    ('<script>\nconst $ = s =>', '<script src="static-shim.js"></script>\n<script src="tour.js"></script>\n<script>\nconst $ = s =>'),
    ('<title>EvidenceTrail</title>', '<title>EvidenceTrail</title>\n<meta name="description" content="EvidenceTrail: evidence-backed incident investigation powered by Google Gemini. CODERED \'26, NTT DATA Track B.">'),
    ('  await loadRecorded(); go(location.hash.slice(1)||"investigate");', '''  await loadRecorded(); go(location.hash.slice(1)||"investigate");
  window.__staticNote = m => toast(m);
  if (!location.hash || location.hash === "#investigate") { $("#recorded").value = "0"; $("#recorded").dispatchEvent(new Event("change")); }'''),
    ("position:sticky;top:0;height:100vh}", "position:sticky;top:44px;height:calc(100vh - 44px)}"),
    ("Test env · telemetry live", "Recorded telemetry · 19 Nov 2026"),
]
for a, b in reps:
    assert a in s, f"pattern not found: {a[:50]}"
    s = s.replace(a, b)
(ROOT / "site/index.html").write_text(s)
print("built site/index.html")
