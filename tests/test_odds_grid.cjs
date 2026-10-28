const assert=require('node:assert/strict'),G=require('../site/pick.js');
assert.equal(G.combos.length,120);assert.equal(new Set(G.combos).size,120);
for(const c of G.combos)assert.equal(new Set(c.split('-')).size,3);
assert.equal(G.combos[0],'1-2-3');assert.equal(G.combos.at(-1),'6-5-4');
assert.equal(G.fmt(123.4),'123.4');assert.equal(G.fmt(9999.9),'9999.9');
for(const v of [null,undefined,0,-1,NaN,Infinity,'13.5','<script>'])assert.equal(G.fmt(v),'—');
const values=G.combos.map((_,i)=>i+1.3),html=G.render(values,{selectable:true});
assert.equal((html.match(/data-c=/g)||[]).length,120);
for(const [i,c]of G.combos.entries())assert.ok(html.includes(`data-c="${c}" aria-label="${c}、${G.fmt(values[i])}倍"`));
for(let first=1;first<=6;first++){
 const h=G.render(values,{first,selectable:true});assert.equal((h.match(/data-c=/g)||[]).length,20);
 assert.equal((h.match(/class="og-second /g)||[]).length,5);
 for(const c of G.combos.filter(c=>c[0]===String(first)))assert.ok(h.includes(`data-c="${c}"`));
}
const selected=G.render(values,{first:1,selectable:true,selected:new Set(['1-2-3'])});
assert.ok(selected.includes('data-c="1-2-3" aria-label="1-2-3、1.3倍" aria-pressed="true"'));
const missing=G.render([],{first:1,selectable:true});assert.equal((missing.match(/ disabled/g)||[]).length,20);
assert.ok(!missing.includes('undefined'));assert.ok(!missing.includes('NaN'));
const removable=G.render([],{first:1,selectable:true,selected:new Set(['1-2-3'])});
assert.ok(removable.includes('data-c="1-2-3" aria-label="1-2-3、オッズ未取得" aria-pressed="true">'));
assert.equal((G.filters(3).match(/aria-pressed="true"/g)||[]).length,1);
console.log('Odds grid: all 120 mappings, 20 per winner, boat colours, decimal precision, missing-odds disabling and selected state passed');
