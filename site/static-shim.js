// Static demo mode: the real EvidenceTrail UI, fed by data captured from the live test environment.
(function () {
  const ORIG = window.fetch.bind(window);
  const J = p => ORIG(p).then(r => r.json());
  const ok = d => Promise.resolve(new Response(JSON.stringify(d), { headers: { 'content-type': 'application/json' } }));
  const SPEED = 4;
  let job = null;
  window.fetch = async function (url, opts = {}) {
    const u = String(url), m = (opts.method || 'GET').toUpperCase();
    if (!u.startsWith('/api/')) return ORIG(url, opts);
    if (u.startsWith('/api/meta')) return ok(await J('data/meta.json'));
    if (u.startsWith('/api/recorded')) return ok(await J('data/recorded.json'));
    if (u.startsWith('/api/scorecard.json')) return ok(await J('data/scorecard.json'));
    if (u.startsWith('/api/audit')) return ok(await J('data/audit.json'));
    if (u.startsWith('/api/health')) return ok(await J('data/health_incident.json'));
    if (u.startsWith('/api/series')) return ok(await J('data/series.json'));
    if (u.startsWith('/api/faults')) { window.__staticNote && window.__staticNote('Fault injection runs in the local test environment (see GitHub). This static demo replays a captured incident: a bad deploy of payment.'); return ok({ ok: true }); }
    if (u === '/api/investigate' && m === 'POST') {
      const live = (await J('data/recorded.json'))[0];
      job = { started: Date.now(), result: live.result };
      return ok({ id: 'replay' });
    }
    if (u.startsWith('/api/investigations/')) {
      if (u.endsWith('/action') || u.endsWith('/feedback')) return ok({ executed: false, reason: 'static demo: actions run only in the local test environment' });
      if (!job) return ok({ status: 'error', error: 'no investigation' });
      const r = job.result, el = (Date.now() - job.started) / 1000 * SPEED, total = r.elapsed_s;
      if (el >= total) return ok({ status: 'done', stage: 'done', result: r });
      const trail = (r.trail || []).filter(t => t.step === 'tool' && (t.t ?? 0) <= el);
      const llm = (r.trail || []).filter(t => t.step === 'llm');
      const firstLlm = llm.length ? llm[0].t : total * 0.6;
      const stage = el < (r.trail?.[0]?.dur || 2) ? 'scan' : el < firstLlm ? 'prefetch' : el < total - 1 ? 'gemini' : 'gate';
      return ok({ status: 'running', stage, live_trail: trail, elapsed_s: el });
    }
    return ok({});
  };
})();
