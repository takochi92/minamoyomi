// Local-only real browser QA. Run manually after building private/turn-watch.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve('private/turn-watch');
const server = http.createServer((req,res) => {
  const file=path.resolve(root,'.'+decodeURIComponent(req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!file.startsWith(root+path.sep)) {res.writeHead(403).end();return;}
  fs.readFile(file,(err,data) => {
    if(err){res.writeHead(404).end();return;}
    res.setHeader('Content-Type',file.endsWith('.html')?'text/html; charset=utf-8':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'image/webp');res.end(data);
  });
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const url=`http://127.0.0.1:${server.address().port}/`;
    await page.goto(url);
    const ready=()=>page.waitForFunction(()=>document.querySelector('#status').textContent.includes('確認できます'));
    await ready(); assert.equal(await page.locator('.card').count(),1);
    await page.screenshot({path:'private/turn-watch/qa-single.png',fullPage:true});
    await page.locator('#all').click();await ready();
    assert.equal(await page.locator('.card').count(),6);
    assert.equal(await page.locator('.sync:not(.missing)').count(),6);
    for(const scene of ['A','B','C','turn']){
      await page.locator('#scene').selectOption(scene);await ready();
      const before=await page.locator('.card small').allTextContents();
      await page.locator('#next').click();await ready();
      assert.notDeepEqual(await page.locator('.card small').allTextContents(),before);
      const data=await page.evaluate(()=>JSON.parse(document.querySelector('#watch-bundle').textContent));
      const clocks=await page.locator('.card small').evaluateAll(nodes=>nodes.map(n=>+n.dataset.pts));
      const relative=clocks.map((pts,i)=>{
        const gate=scene==='turn'?'A':scene;
        return pts*data.source.time_base[0]/data.source.time_base[1]-data.anchors[`${i+1}:${gate}`].time;
      });
      assert.ok(Math.max(...relative)-Math.min(...relative)<.034);
    }
    await page.locator('#scene').selectOption('B');await ready();
    await page.screenshot({path:'private/turn-watch/qa-six-desktop.png',fullPage:true});
    await page.locator('#speed').selectOption('0.25');await ready();
    await page.locator('#play').click();
    await page.waitForFunction(()=>Number(document.querySelector('#seek').value)>2);
    await page.locator('#play').click();await ready();
    await page.locator('.card button').first().click();await ready();
    await page.locator('.card canvas').first().click({position:{x:100,y:100}});await ready();
    await page.locator('.card button').first().click();await ready();
    for(const width of [390,320]){
      await page.setViewportSize({width,height:844});await ready();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      if(width===390)await page.screenshot({path:'private/turn-watch/qa-six-mobile.png',fullPage:true});
    }
    // Race/scene request replacement must invalidate any pending draw callback.
    await page.locator('#scene').selectOption('A');
    await page.locator('#scene').selectOption('C');await ready();
    await page.locator('.card').nth(3).locator('[data-action="solo"]').click();await ready();
    assert.equal(await page.locator('.card').count(),1);
    assert.match(await page.locator('.card h2').textContent(),/4号艇/);
    await page.locator('#all').click();await ready();
    await page.locator('#single').click();await ready();assert.equal(await page.locator('.card').count(),1);
    await page.route('**/frames/*.webp',route=>route.abort());
    await page.locator('#retry').click();
    await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('読み込めません'));
    assert.equal(await page.locator('#play').getAttribute('aria-pressed'),'false');
    await page.unroute('**/frames/*.webp');await page.locator('#retry').click();await ready();
    await page.route('**/index.html',async route=>{
      const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
      const changed=html.replace(/(<script type="application\/json" id="watch-bundle">)(.*?)(<\/script>)/s,(_,a,json,z)=>{
        const b=JSON.parse(json);delete b.anchors['2:A'];return a+JSON.stringify(b)+z;
      });
      await route.fulfill({contentType:'text/html',body:changed});
    });
    await page.goto(url+'index.html');await ready();await page.locator('#all').click();
    await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('同期未確認'));
    assert.equal(await page.locator('#play').isDisabled(),true);
    assert.equal(await page.locator('.sync.missing').count(),1);
    await page.locator('#single').click();await ready();
    assert.deepEqual(errors,[]);
    const promo=await browser.newPage({viewport:{width:1200,height:675}});
    const screenshot=fs.readFileSync(path.join(root,'qa-six-desktop.png')).toString('base64');
    await promo.setContent(`<html lang="ja"><style>*{box-sizing:border-box}body{margin:0;background:#0c1420;color:#e5eef8;font-family:system-ui,sans-serif}.layout{display:grid;grid-template-columns:440px 1fr;height:675px;padding:44px;gap:28px}.text{align-self:center}h1{font-size:44px;line-height:1.4}p{font-size:23px;line-height:1.7}.green{color:#7edecb}.preview{overflow:hidden;border:1px solid #466078;border-radius:14px}img{width:100%;margin-top:-80px}.label{font-size:19px;color:#ffd68b}</style><div class="layout"><div class="text"><p class="green">艇ろぐ / 展示映像</p><h1>１艇でも、６艇でも。<br>向きと膨らみを<br>見比べる。</h1><p>入口・旋回・出口<br>スロー再生 / コマ送り</p><p class="label">非公開の検証版 / タイム精度は検証中</p></div><div class="preview"><img src="data:image/png;base64,${screenshot}"></div></div></html>`);
    await promo.screenshot({path:'private/exhibition-watch-x.png'});await promo.close();
    console.log('Real Edge QA passed: 1/6 boats, all scenes, verified PTS sync, speed, playback, steps, zoom, 320/390/1440px, stale loads, failure/retry.');
  } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
