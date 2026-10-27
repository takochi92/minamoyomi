const fs=require('fs'),path=require('path'),http=require('http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve('private/home-compact');
const server=http.createServer((req,res)=>{const p=path.resolve(root,'.'+req.url.split('?')[0]);if(!p.startsWith(root+path.sep))return res.writeHead(403).end();fs.readFile(p,(e,b)=>{if(e)return res.writeHead(404).end();res.setHeader('Content-Type',p.endsWith('.html')?'text/html; charset=utf-8':p.endsWith('.js')?'text/javascript':p.endsWith('.css')?'text/css':p.endsWith('.png')?'image/png':'application/octet-stream');res.end(b);});});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const b=await chromium.launch({channel:'msedge',headless:true});try{
const page=await b.newPage({viewport:{width:390,height:1000},colorScheme:'dark'}),errors=[];
page.on('pageerror',e=>errors.push(e.message));const origin='http://127.0.0.1:'+server.address().port;
await page.route('**/*',r=>r.request().url().startsWith(origin)?r.continue():r.abort());
await page.addInitScript(()=>localStorage.setItem('teilog_note_v1',JSON.stringify({racer:{},motor:{},fav:Object.fromEntries(Array.from({length:20},(_,i)=>[String(4000+i),{name:'確認選手'+i}])),bets:[],budget:0})));
await page.goto(origin+'/index.html');assert.equal(await page.locator('#fav-today').count(),0);
assert.equal(await page.getByRole('heading',{name:'今日出走するお気に入り'}).count(),0);
assert.ok(await page.locator('.grade-brief-row').count()>0);
assert.equal(await page.locator('.grade-brief-row').first().locator('img').getAttribute('alt'),'SG');
assert.ok(await page.locator('.grade-brief-row').first().evaluate(e=>e.getBoundingClientRect().height<90));
await page.locator('.grade-brief').screenshot({path:'private/home-compact/actual-grade-mobile.png'});
await page.goto(origin+'/grade-fixture.html');assert.equal(await page.locator('.grade-brief-row').count(),5);
for(const width of [320,390,1280]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.ok(await page.locator('.grade-brief-row img').evaluateAll(xs=>xs.every(x=>x.complete&&x.naturalWidth>0)));}
await page.setViewportSize({width:390,height:1000});await page.screenshot({path:'private/home-compact/all-grades-mobile.png',fullPage:true});
assert.deepEqual(errors,[]);console.log('Edge: 20 favorites do not add home card; real SG row compact; all 5 official icons load; 320/390/1280px passed.');
}finally{await b.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
