const {test} = require('node:test');
const assert = require('node:assert/strict');
const {watchPlan, frameAt, sceneFrames} = require('../tools/turn_watch/watch.js');
function source() {
  const clips = [1,2].map(boat => ({boat, frames:[0,1,2,3].map(i => ({index:boat*10+i,pts:boat*100+i*10,time:boat*10+i/10})),
    scenes:{turn:[0,1,2,3].map(i=>boat*10+i),A:[boat*10,boat*10+1,boat*10+2],B:[],C:[]}}));
  return {clips,source:{sha256:'a'},anchors:{'1:A':{time:10.1,basis:'two_review_mean',source_sha256:'a'},
    '2:A':{time:20.15,basis:'two_review_mean',source_sha256:'a'}}};
}
test('aligns different PTS clocks to reviewed gates and shows only actual previous frames', () => {
  const b=source(), p=watchPlan(b,[1,2],'turn');
  assert.equal(p.reason,''); assert.ok(p.ticks.length>3);
  assert.ok(Math.abs(p.ticks[0]+.1)<1e-7);
  assert.equal(frameAt(p.rows[0],0).index,11);
  assert.equal(frameAt(p.rows[1],0).index,21);
  assert.equal(frameAt(p.rows[1],.05).index,22);
  assert.ok(p.ticks.at(-1)<=.15+1e-7);
});
test('missing or mismatched anchors block comparison but allow single-boat review', () => {
  const b=source(); b.anchors['2:A'].source_sha256='wrong';
  assert.equal(watchPlan(b,[1,2],'turn').ticks.length,0);
  const single=watchPlan(b,[2],'turn');
  assert.ok(single.ticks.length); assert.equal(single.rows[0].synced,false);
  assert.equal(frameAt(single.rows[0],0).index,20);
});
test('does not fall back to another scene or bridge missing/reversed frames', () => {
  const b=source(); assert.equal(watchPlan(b,[1],'B').ticks.length,0);
  b.clips[0].frames[2].time+=1;
  assert.deepEqual(sceneFrames(b.clips[0],'turn'),[]);
});
test('scene windows and tick stepping preserve original frames including unequal intervals', () => {
  const b=source(); b.clips[1].frames[2].time+=.01;
  const p=watchPlan(b,[1,2],'A');
  for (const row of p.rows) for (const t of p.ticks) {
    const f=frameAt(row,t);
    assert.ok(row.frames.includes(f));
    assert.ok(f.time<=row.origin+t+1e-7);
  }
});
