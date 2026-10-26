const assert=require('node:assert/strict');
const {hullMidpoint,canvasPoint,sourcePoint,acceptDraft}=require('../tools/turn_review/review.js');
assert.deepEqual(hullMidpoint({bow:[10,20],stern:[30,40]}),[20,30]);
assert.equal(hullMidpoint({bow:[10,20]}),null);
// Mobile canvas coordinates must refer to the original image, not CSS pixels.
assert.deepEqual(canvasPoint(170,110,{left:10,top:20,width:320,height:180},1280,720),[640,360]);
assert.deepEqual(canvasPoint(-20,999,{left:0,top:0,width:320,height:180},1280,720),[0,719]);
assert.deepEqual(sourcePoint([640,360],4,[-2560,-1000]),[800,340]);
const bundle={digest:'abc',size:[1280,720],events:[{boat:1,gate:'A',frames:[{index:10},{index:11}]}]};
const draft={kind:'turn-review-draft-v1',bundle_digest:'abc',labels:{'1:10':{bow:[50,60],stern:[90,70]}},pairs:{'1:A':{before:10,after:11}}};
assert.deepEqual(acceptDraft(draft,bundle),draft);
assert.throws(()=>acceptDraft({...draft,bundle_digest:'stale'},bundle));
assert.throws(()=>acceptDraft({...draft,labels:{'1:10':{bow:[9999,60]}}},bundle));
assert.throws(()=>acceptDraft({...draft,labels:{'2:10':{bow:[50,60]}}},bundle));
assert.throws(()=>acceptDraft({...draft,pairs:{'1:A':{after:99}}},bundle));
assert.throws(()=>acceptDraft({...draft,pairs:{'1:A':null}},bundle));
console.log('turn review math/import checks ok (not a browser render test)');
