const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  for (const th of ['dark','light']) {
    const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
    const errs=[]; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => m.type()==='error' && errs.push(m.text()));
    await p.addInitScript(t => { try { localStorage.setItem('et-theme',t) } catch(e){} }, th);
    await p.goto('http://localhost:8090/?t='+th+'#map'); await p.waitForTimeout(2000);
    const c = await p.$('#topoMap'); const bb = await c.boundingBox();
    await p.screenshot({ path: `topo-${th}.png`, clip: { x: bb.x-20, y: bb.y-50, width: bb.width+40, height: bb.height+70 } });
    if (th==='dark') { const n = await p.$('#topoMap .node[data-n="checkout"]'); await n.hover(); await p.waitForTimeout(300);
      await p.screenshot({ path: 'topo-hover.png', clip: { x: bb.x-20, y: bb.y-50, width: bb.width+40, height: bb.height+70 } }); }
    await p.goto('http://localhost:8090/?r='+th); await p.waitForTimeout(2000);
    const t2 = await p.$('#topoInv'); await t2.scrollIntoViewIfNeeded(); const b2 = await t2.boundingBox();
    await p.screenshot({ path: `topo-inv-${th}.png`, clip: { x: b2.x-20, y: b2.y-50, width: b2.width+40, height: b2.height+70 } });
    console.log(th, 'errors', JSON.stringify(errs)); await p.close();
  }
  await b.close();
})();
