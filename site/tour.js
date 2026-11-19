// Guided demo: walks through EvidenceTrail on the recorded incident, with captions and highlights.
(function () {
  const $ = s => document.querySelector(s);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let running = false, paused = false, skip = false, stopReq = false;

  const css = `
  .tour-focus{outline:3px solid var(--brand)!important;outline-offset:6px;border-radius:14px;transition:outline-color .2s}
  #tourcap{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);width:min(860px,calc(100vw - 32px));z-index:60;
    background:var(--surface);color:var(--ink);border:1px solid var(--hair);border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.35);padding:14px 16px 12px}
  #tourcap .tt{font:600 18px/1.45 system-ui,sans-serif;margin:2px 0 10px}
  #tourcap .meta{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--muted)}
  #tourcap .bar{flex:1;height:4px;border-radius:9px;background:var(--surface-3);overflow:hidden}
  #tourcap .bar i{display:block;height:100%;background:var(--brand);transition:width .3s}
  #tourcap button{border:1px solid var(--hair);background:var(--surface-2);color:var(--ink);border-radius:8px;padding:5px 10px;font:600 12px system-ui;cursor:pointer}
  #tourcap button.p{background:var(--brand);border-color:var(--brand);color:#fff}
  #tourbtn{background:var(--brand);color:#fff;border:0;border-radius:999px;padding:6px 14px;font:700 13px system-ui;cursor:pointer}`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  function capBox() {
    let c = $('#tourcap');
    if (!c) {
      c = document.createElement('div'); c.id = 'tourcap'; c.setAttribute('role', 'status'); c.setAttribute('aria-live', 'polite');
      c.innerHTML = `<div class="meta"><b style="color:var(--brand)">Guided demo</b><span id="tstep"></span><div class="bar"><i id="tbar"></i></div>
        <button id="tpause">Pause</button><button id="tnext">Next ›</button><button id="texit">Exit</button></div><div class="tt" id="ttext"></div>`;
      document.body.appendChild(c);
      $('#tpause').onclick = () => { paused = !paused; $('#tpause').textContent = paused ? 'Resume' : 'Pause'; };
      $('#tnext').onclick = () => { skip = true; };
      $('#texit').onclick = () => { stopReq = true; skip = true; };
    }
    return c;
  }
  function focus(sel) {
    document.querySelectorAll('.tour-focus').forEach(e => e.classList.remove('tour-focus'));
    const el = sel && $(sel);
    if (el) { el.classList.add('tour-focus'); el.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  }
  async function hold(ms) {               // waits ms, honouring pause / next / exit
    let t = 0; skip = false;
    while (t < ms && !skip) { await sleep(100); if (!paused) t += 100; }
  }
  const go = v => { location.hash = v; };

  const STEPS = [
    { cap: 'EvidenceTrail helps an on-call engineer find the root cause of an incident. One rule: no evidence, no claim. This tour replays a real incident we captured from our test environment.', run: () => { go('investigate'); focus(null); window.scrollTo({ top: 0, behavior: 'smooth' }); }, ms: 7000 },
    { cap: 'The incident: a bad deployment of the payment service. In the live service map, payment, checkout and frontend are all failing. Which one is the real cause?', run: () => { go('map'); setTimeout(() => focus('#topoMap'), 400); }, ms: 8000 },
    { cap: 'The heatmap shows the errors started in payment and then spread upstream to checkout and frontend.', run: () => focus('#heat'), ms: 7000 },
    { cap: 'Each service has three real charts: error ratio against the 5% SLO, p95 latency against its baseline, and request rate. Failing services are sorted first.', run: () => focus('#tiles .svcpanel'), ms: 8000 },
    { cap: 'The engineer pastes the alert and clicks Investigate. Watch each step: health scan, call graph, evidence prefetch, Gemini, then the evidence gate.', run: async () => { go('investigate'); await sleep(500); focus('#stepper'); $('#go').click(); }, ms: 2500 },
    { cap: 'EvidenceTrail fetches logs, failing traces and recent deploys for the top suspects, then Gemini tests its hypotheses with read-only tools. (Replayed at 4× speed.)', run: async () => { focus('#feed'); }, wait: async () => { for (let i = 0; i < 300 && $('#go').disabled && !skip; i++) await sleep(100); }, ms: 1500 },
    { cap: 'Diagnosis: payment, caused by a bad deploy. It shows confidence, time to diagnosis, Gemini token cost and evidence precision.', run: () => focus('#verdictCard'), ms: 8000 },
    { cap: 'The blast radius marks the root cause and the failure path through the call graph.', run: () => focus('#topoInv'), ms: 6500 },
    { cap: 'The timeline shows where every second went: telemetry queries in orange, Gemini calls in blue, plus the mix of evidence fetched.', run: () => focus('#timeline'), ms: 6500 },
    { cap: 'Every claim links to the evidence behind it. Claims that cite evidence which was never fetched, or misquote it, are blocked.', run: () => focus('#claims'), ms: 6500 },
    { cap: 'Click any citation to see the exact log line, trace or deploy event. Secrets are redacted before anything reaches Gemini.', run: async () => { const c = $('#claims .ev'); if (c) c.click(); }, ms: 7000, after: () => { const sc = document.getElementById('scrim'); if (sc) sc.click(); } },
    { cap: 'The suggested fix is labelled by policy, not by the AI: "rollback deploy" is risky, shown as a dry run, and runs only after a named engineer approves it.', run: () => focus('#action'), ms: 8000 },
    { cap: 'We measure everything on injected faults against two baselines, and report every miss. EvidenceTrail: 12/12 on service and fault type.', run: async () => { go('scorecard'); await sleep(600); focus('#accChart'); }, ms: 8000 },
    { cap: 'On the hard set (noisy logs, silent faults): 0 confident wrong answers for EvidenceTrail, against 2 for a single Gemini prompt. The chart has switched to the hard set.', run: async () => { const t = document.querySelector('#setTabs button[data-set="hard"]'); if (t) t.click(); await sleep(300); focus('#accChart'); }, ms: 9000 },
    { cap: 'That is EvidenceTrail: Gemini inside the product, evidence for every claim, a human in charge of every change. Explore freely, or watch the video.', run: () => { focus(null); go('investigate'); window.scrollTo({ top: 0, behavior: 'smooth' }); }, ms: 9000 },
  ];

  async function start() {
    if (running) return; running = true; stopReq = false; paused = false;
    capBox().style.display = 'block';
    for (let i = 0; i < STEPS.length && !stopReq; i++) {
      const s = STEPS[i];
      $('#tstep').textContent = `${i + 1} / ${STEPS.length}`;
      $('#tbar').style.width = `${(i + 1) / STEPS.length * 100}%`;
      $('#ttext').textContent = s.cap;
      try { await s.run(); } catch (e) { console.warn(e); }
      if (s.wait) await s.wait();
      await hold(s.ms);
      if (s.after) s.after();
      if (stopReq) { const sc = document.getElementById('scrim'); if (sc) sc.click(); }
    }
    focus(null); $('#tourcap').style.display = 'none'; running = false;
  }
  window.EvidenceTrailTour = { start };

  // the button lives in the recorded-demo banner
  window.addEventListener('load', () => {
    const bar = document.getElementById('staticbar');
    if (bar) {
      const b = document.createElement('button'); b.id = 'tourbtn'; b.textContent = '▶ Run guided demo';
      b.onclick = start; bar.insertBefore(b, bar.children[1]);
    }
    if (new URLSearchParams(location.search).get('tour') === '1') setTimeout(start, 1200);
  });
})();
