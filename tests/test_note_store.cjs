const assert = require('node:assert/strict');
const M = require('../site/note-store.js');
const note = text => ({name:'田頭 虎親',text,t:'20261025'});
const initial = M.empty(); initial.racer['5037']=note('差しを確認');
const phone = M.copy(initial); phone.motor['02-71']={text:'直線が良い',no:'71'};
const pc = M.copy(initial); pc.fav['5037']={name:'田頭 虎親',t:'20261025'};
function ops(a,b){return M.changes(a,b).map((o,i)=>({...o,id:String(i)}));}
let result = M.rebase(pc,ops(initial,phone));
assert.equal(result.conflicts.length,0);
assert.equal(result.data.motor['02-71'].text,'直線が良い');
assert.equal(result.data.fav['5037'].name,'田頭 虎親');

// The same memo edited on two devices must not silently overwrite either text.
phone.racer['5037']=note('スマホで変更'); pc.racer['5037']=note('PCで変更');
result=M.rebase(pc,ops(initial,phone));
assert.equal(result.conflicts.length,1);
assert.equal(result.conflicts[0].remote.text,'PCで変更');
assert.equal(result.conflicts[0].op.value.text,'スマホで変更');

// A remote deletion cannot be resurrected by an offline edit without a choice.
const deleted=M.empty(); result=M.rebase(deleted,ops(initial,phone));
assert.equal(result.conflicts.length,1);
assert.equal(result.conflicts[0].remote,null);

// A network response may be lost after a successful write. Replaying the
// complete sequence of keystrokes must acknowledge it without a false conflict.
const a=M.empty(), b=M.empty(), c=M.empty();b.racer['5037']=note('あ');c.racer['5037']=note('あいう');
const chain=ops(a,b).concat(ops(b,c).map(o=>({...o,id:'next'})));
result=M.rebase(c,chain);assert.equal(result.conflicts.length,0);assert.equal(result.acknowledged.length,2);
assert.deepEqual(result.data,c);

// Removing a favorite and a financial record propagates as an actual deletion.
const withRecords=M.empty();withRecords.fav['5037']={name:'田頭 虎親'};withRecords.bets=[{id:'bet1',date:'20261025',inv:800,ret:0}];
result=M.rebase(withRecords,ops(withRecords,M.empty()));
assert.deepEqual(result.data,M.empty());
assert.equal(result.conflicts.length,0);

// Importing a backup never duplicates a bet, sums amounts, or overwrites a
// conflicting existing memo. The guest copy itself remains unchanged.
const incoming=M.copy(withRecords);incoming.racer['5037']=note('旧端末');
const current=M.copy(withRecords);current.racer['5037']=note('アカウント側');
const imported=M.importGuest(current,incoming);
assert.equal(imported.data.bets.length,1);assert.equal(imported.data.bets[0].inv,800);
assert.equal(imported.conflicts.length,1);assert.equal(imported.data.racer['5037'].text,'アカウント側');
assert.equal(incoming.racer['5037'].text,'旧端末');

assert.throws(()=>M.normalize(JSON.parse('{"fav":{"__proto__":{"name":"bad"}}}')));
assert.throws(()=>M.normalize({bets:[{id:'b',date:'20261025',inv:-1}]}));
assert.throws(()=>M.normalize({bets:[{id:'b',date:'20261025',inv:1},{id:'b',date:'20261025',inv:1}]}));
assert.throws(()=>M.normalize({racer:{'1':{text:'x'.repeat(20001)}}}));
assert.deepEqual(M.inflate(M.flatten(initial)),initial);
console.log('Note model OK: independent merges, conflicting edits, deletions, lost response retry, safe imports, validation.');
