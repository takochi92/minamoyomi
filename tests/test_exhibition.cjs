const assert=require('node:assert/strict');
const {exhibitionSelection,exhibitionAsset}=require('../site/exhibition.js');
assert.deepEqual(exhibitionSelection('2026-10-26','04','1'),{date:'20261026',jcd:'04',rno:1});
for(const bad of ['20260230','20261301','oops'])assert.equal(exhibitionSelection(bad,'04',1),null);
assert.equal(exhibitionSelection('20261026','04',13),null);
assert.equal(exhibitionSelection('20261026','04','1.0'),null);
assert.ok(exhibitionAsset('data/exhibition/20261026/04-1.html'));
for(const bad of ['javascript:alert(1)','https://x/page.html','data/exhibition/../x.html','data/exhibition//x.html'])assert.ok(!exhibitionAsset(bad));
console.log('exhibition route/date/asset validation ok');
