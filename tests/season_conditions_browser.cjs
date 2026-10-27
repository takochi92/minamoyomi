// Manual real-browser QA against private/season-preview; all network stays local.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve('private/season-preview');
const server=http.createServer((req,res)=>{
  const file=path.resolve(root,'.'+decodeURIComponent(req.url.split('?')[0]));
  if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}
  fs.readFile(file,(error,data)=>{if(error){res.writeHead(404).end();return;}
    res.setHeader('Content-Type',file.endsWith('.html')?'text/html; charset=utf-8':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'application/octet-stream');res.end(data);});
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000},colorScheme:'dark'}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    const origin=`http://127.0.0.1:${server.address().port}`;
    await page.route('**/*',route=>route.request().url().startsWith(origin)?route.continue():route.abort());
    await page.goto(origin+'/database/season-fixture.html');
    await page.waitForSelector('.sw-condition strong');
    assert.match(await page.locator('.sw-condition').textContent(),/2着以上/);
    assert.match(await page.locator('.sw-condition').textContent(),/期末当日.*残り1走/);
    await page.locator('#sw-mode').selectOption('scenario');
    assert.match(await page.locator('.sw-condition').textContent(),/合計14点以上/);
    assert.match(await page.locator('.sw-condition').textContent(),/1着＋4着.*2着＋3着/);
    assert.match(await page.locator('.sw-condition').textContent(),/仮定/);
    await page.locator('#sw-remaining').fill('1');
    await page.locator('#sw-kind').selectOption('sg');await page.locator('#sw-final').check();
    assert.match(await page.locator('.sw-condition').textContent(),/4着以上/);
    await page.locator('#sw-remaining').fill('13');
    assert.match(await page.locator('.sw-condition').textContent(),/１〜12走/);
    await page.locator('#sw-mode').selectOption('auto');
    assert.equal(await page.locator('#sw-scenario').isVisible(),false);
    await page.screenshot({path:'private/season-preview/qa-fixture-desktop.png',fullPage:true});
    for(const width of [390,320]){
      await page.setViewportSize({width,height:950});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      if(width===390)await page.screenshot({path:'private/season-preview/qa-fixture-mobile.png',fullPage:true});
    }
    await page.goto(origin+'/database/season.html');await page.waitForSelector('.sw-card');
    const candidate=await page.evaluate(()=>{
      const data=JSON.parse(document.querySelector('#sw-data').textContent);
      return data.players.filter(p=>p.n>=90&&!p.unknown&&p.condition?.programme_complete&&
        !p.condition.issues.length&&p.condition.races.length&&p.condition.races.every(r=>r.points))
        .sort((a,b)=>Math.abs(a.win-6.3)-Math.abs(b.win-6.3))[0]?.toban;
    });
    assert.ok(candidate,'Real fixture must include a verified programme candidate');
    await page.locator('#sw-advanced > summary').click();
    await page.locator('#sw-scope').selectOption('all');await page.locator('#sw-q').fill(candidate);
    assert.equal(await page.locator('.sw-card').count(),1);
    assert.match(await page.locator('.sw-condition').textContent(),/期末全体は未確定/);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.setViewportSize({width:390,height:1100});
    await page.screenshot({path:'private/season-preview/qa-real-mobile.png',fullPage:true});
    await page.locator('#sw-tier').selectOption('A2');
    await page.locator('#sw-mode').selectOption('scenario');await page.locator('#sw-remaining').fill('2');
    assert.match(await page.locator('.sw-condition').textContent(),/残り2走と仮定/);
    assert.deepEqual(errors,[]);
    console.log('Real Edge passed: final-day single start, 2-start combinations, SG/final bonus, invalid count, real current-day data, A1/A2, auto/scenario, 320/390/1440px.');
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
