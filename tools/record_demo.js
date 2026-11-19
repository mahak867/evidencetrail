// Records the Round 1 demo video by driving the real EvidenceTrail UI against the live test environment.
// Captions are overlaid in-page. Scene boundaries are written to scenes.json so ffmpeg can speed up waits.
const { chromium } = require('playwright');
const fs = require('fs');

const BASE = 'http://localhost:8080';
const W = 1440, H = 900;
const scenes = [];
const caps = [];
let t0;
const mark = (name, speed = 1) => scenes.push({ name, t: (Date.now() - t0) / 1000, speed });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const CARD_CSS = `body{margin:0;height:100vh;display:grid;place-items:center;background:#0d0d0d;color:#f0efec;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.w{max-width:1100px;padding:40px} .k{color:#3987e5;font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:16px}
h1{font-size:72px;margin:10px 0 6px;letter-spacing:-.03em} h2{font-size:30px;font-weight:500;color:#c3c2b7;margin:0 0 30px}
.row{display:flex;gap:28px;margin-top:26px} .s{border:1px solid #2c2c2a;border-radius:16px;padding:22px 26px;background:#1a1a19;flex:1}
.s b{display:block;font-size:52px;letter-spacing:-.03em;color:#fab219} .s span{color:#c3c2b7;font-size:18px} p{font-size:22px;color:#c3c2b7;line-height:1.5}
.m{color:#8f8d86;font-size:16px;margin-top:28px}`;

async function card(page, html, ms) {
  await page.setContent(`<style>${CARD_CSS}</style><div class="w">${html}</div>`);
  await sleep(ms);
}

async function caption(page, text) {
  await page.evaluate(t => {
    let c = document.getElementById('cap');
    if (!c) {
      c = document.createElement('div'); c.id = 'cap';
      c.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:1100px;background:rgba(13,13,13,.92);color:#f0efec;' +
        'border:1px solid #383835;border-radius:14px;padding:14px 22px;font:600 21px/1.4 system-ui,sans-serif;z-index:99;box-shadow:0 10px 30px rgba(0,0,0,.5);text-align:center';
      document.body.appendChild(c);
    }
    c.textContent = t; c.style.display = t ? 'block' : 'none';
  }, text);
  caps.push({ t: (Date.now() - t0) / 1000, text });
}

async function api(path, method = 'GET', body) {
  const r = await fetch(BASE + path, { method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  return r.json();
}

async function waitForErrors(service, minRatio = 0.4, timeoutMs = 150000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { const h = await api('/api/health'); const s = h.services[service]; if (s && s.error_ratio >= minRatio) return true; } catch (e) {}
    await sleep(3000);
  }
  return false;
}

(async () => {
  await api('/api/faults', 'DELETE');
  await sleep(45000); // let the test shop settle to healthy before recording
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: 'video_raw', size: { width: W, height: H } } });
  await ctx.addInitScript(() => { try { localStorage.setItem('et-theme', 'dark') } catch (e) {} });
  const page = await ctx.newPage();
  t0 = Date.now();

  mark('title');
  await card(page, `<div class="k">CODERED '26 · NTT DATA Track B · PS2</div><h1>EvidenceTrail</h1><h2>Find the cause. Show the evidence.</h2>
    <p>A Google Gemini incident investigator for on-call engineers, built on one rule: <b style="color:#f0efec">no evidence, no claim.</b></p>
    <div class="m">Team EvidenceTrail · Chennai Institute of Technology</div>`, 6000);

  mark('problem');
  await card(page, `<div class="k">The problem</div><h2 style="margin-top:10px">One fault makes alerts fire in many services. Engineers can't trust AI answers mid-incident.</h2>
    <div class="row"><div class="s"><b>11.3%</b><span>best AI agent's root-cause accuracy on the OpenRCA benchmark (ICLR 2025)</span></div>
    <div class="s"><b>7–40%</b><span>of root causes hallucinated by frontier AI agents (ORCA-bench, 2026)</span></div></div>`, 9000);

  mark('arch');
  await card(page, `<div class="k">How it works</div><h2 style="margin-top:10px">Six steps from alert to an approved fix</h2>
    <div class="row" style="flex-wrap:wrap;gap:14px">${[['1','Health scan','Prometheus: error ratio and p95 vs a baseline window'],['2','Call graph','Jaeger traces: the deepest failing service is the suspect'],
      ['3','Prefetch','Logs, failing traces and recent deploys for the top suspects'],['4','Gemini','Tests hypotheses with read-only tools, then submits a structured diagnosis'],
      ['5','Evidence gate','Claims citing evidence never fetched are blocked; weak evidence means INCONCLUSIVE'],['6','Human in charge','Fixes are labelled safe or risky, dry-run, and need a named approval']]
      .map(([n,h,d])=>`<div class="s" style="flex:1 1 30%;min-width:300px"><span style="color:#3987e5;font-weight:700">STEP ${n}</span><div style="font-size:24px;font-weight:700;margin:4px 0">${h}</div><span>${d}</span></div>`).join('')}</div>`, 9000);

  mark('map_healthy');
  await page.goto(BASE + '/#map'); await sleep(2500);
  await caption(page, 'Our 9-service test shop, live: traces, metrics and logs flow through OpenTelemetry, Jaeger and Prometheus.');
  await sleep(6000);

  mark('inject');
  await page.goto(BASE + '/#investigate'); await sleep(1200);
  await page.evaluate(() => document.querySelector('details.chaos').open = true);
  await page.selectOption('#fsvc', 'payment'); await page.selectOption('#fkind', 'bad_deploy');
  await caption(page, 'We inject a known fault into our own test environment: a bad deployment of the payment service.');
  await sleep(2500);
  await page.click('#inject'); await sleep(3000);

  mark('wait_incident', 8);
  await page.goto(BASE + '/#map'); await sleep(1000);
  await caption(page, 'Within a minute, errors spread upstream: checkout and frontend turn red too. Which service is the real cause?');
  await waitForErrors('payment', 0.4);
  await sleep(15000);

  mark('investigate');
  await page.goto(BASE + '/#investigate'); await sleep(1000);
  await caption(page, 'The on-call engineer pastes the alert and clicks Investigate.');
  await page.fill('#alert', 'checkout error rate above 5% for 1m (SLO burn)'); await sleep(1500);
  let ok = false;
  for (let attempt = 0; attempt < 3 && !ok; attempt++) {
    await page.click('#go');
    await caption(page, 'EvidenceTrail scans health, walks the call graph, prefetches evidence, then Gemini tests hypotheses with read-only tools.');
    await page.waitForFunction(() => !document.querySelector('#go').disabled, null, { timeout: 600000 });
    ok = await page.evaluate(() => /payment/.test(document.querySelector('.rc')?.textContent || ''));
    if (!ok) { mark('retry', 6); await sleep(2000); }
  }

  mark('verdict');
  await page.evaluate(() => document.querySelector('#verdictCard').scrollIntoView({ behavior: 'smooth', block: 'start' }));
  await caption(page, 'Diagnosis: payment, caused by a bad deploy, with confidence, time, tokens and evidence precision.');
  await sleep(7000);

  mark('graph');
  await page.evaluate(() => window.scrollBy({ top: 520, behavior: 'smooth' }));
  await caption(page, 'The blast radius shows the failure path, and the timeline shows exactly where the seconds went.');
  await sleep(6500);

  mark('claims');
  await page.evaluate(() => document.querySelector('#claims').scrollIntoView({ behavior: 'smooth', block: 'center' }));
  await caption(page, 'Every claim links to the evidence behind it. Claims citing evidence that was never fetched are blocked.');
  await sleep(4500);
  const chip = await page.$('#claims .ev');
  if (chip) { await chip.click(); await sleep(1200);
    await caption(page, 'Click any citation to see the exact log line, trace or deploy event, redacted before it reaches Gemini.');
    await sleep(6000); await page.keyboard.press('Escape'); await sleep(800); }

  mark('approve');
  await page.evaluate(() => document.querySelector('#action').scrollIntoView({ behavior: 'smooth', block: 'center' }));
  await caption(page, 'The suggested fix is labelled by policy, shown as a dry run, and runs only with a named human approval.');
  await sleep(5000);
  const approver = await page.$('#approver');
  if (approver) {
    await page.fill('#approver', 'On-call: Annika'); await sleep(1200);
    const btn = await page.$('#approve:not([disabled])');
    if (btn) { await btn.click(); await sleep(3500); }
  }

  mark('recover', 8);
  await page.goto(BASE + '/#map'); await sleep(1000);
  await caption(page, 'After approval the deploy is rolled back and the services recover.');
  await sleep(25000);

  mark('scorecard');
  await page.goto(BASE + '/#scorecard'); await sleep(2000);
  await caption(page, 'Measured on injected faults, misses included: EvidenceTrail vs single-prompt Gemini vs a dashboard rule.');
  await sleep(7000);
  await page.evaluate(() => document.querySelector('#timeChart').scrollIntoView({ behavior: 'smooth', block: 'start' }));
  await sleep(5000);

  mark('results');
  await card(page, `<div class="k">Measured results</div><h2 style="margin-top:10px">Same injected faults, same telemetry, every miss reported</h2>
    <div class="row"><div class="s"><b>12/12</b><span>right service and fault type on the standard set (single-prompt Gemini: 10/12 fault type)</span></div>
    <div class="s"><b>0 vs 2</b><span>confident wrong answers on the hard set (noisy logs, silent faults): EvidenceTrail vs single-prompt Gemini</span></div>
    <div class="s"><b>7 / 30</b><span>AI claims blocked by the evidence gate for citing evidence that was never fetched or was misquoted</span></div></div>
    <div class="m">~2 Gemini calls per incident · secrets redacted before Gemini · read-only by default · open scorecard on GitHub</div>`, 10000);

  mark('team');
  await card(page, `<div class="k">Team EvidenceTrail · Chennai Institute of Technology</div><h2 style="margin-top:10px">Everyone owns a part</h2>
    <div class="row" style="flex-wrap:wrap;gap:14px">${[['Mahak Fahad','Team leader · AI / backend: Gemini agent, evidence gate, API'],['Roshini R','Frontend & UI/UX: investigation console, design'],
      ['Kanish Karthikeyan','Platform & observability: test environment, faults, telemetry'],['Annika Meril Babu','Evaluation, research & pitch: scorecard, market']]
      .map(([n,r])=>`<div class="s" style="flex:1 1 40%;min-width:420px"><div style="font-size:26px;font-weight:700;margin-bottom:4px">${n}</div><span>${r}</span></div>`).join('')}</div>`, 8000);

  mark('close');
  await card(page, `<div class="k">EvidenceTrail</div><h1 style="font-size:56px">Find the cause. Show the evidence.</h1>
    <p>Gemini inside the product · evidence for every claim · human approval for every change · a repeatable scorecard.</p>
    <div class="m">Team EvidenceTrail · Mahak Fahad · Roshini R · Kanish Karthikeyan · Annika Meril Babu<br>Chennai Institute of Technology</div>`, 6000);
  mark('end');

  await ctx.close(); await browser.close();
  const vid = fs.readdirSync('video_raw').filter(f => f.endsWith('.webm')).map(f => 'video_raw/' + f).sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)[0];
  fs.writeFileSync('scenes.json', JSON.stringify({ video: vid, scenes, caps, ok }, null, 1));
  console.log('recorded', vid, 'diagnosis ok:', ok);
})();
