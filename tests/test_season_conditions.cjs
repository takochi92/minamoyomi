const {test}=require('node:test'),assert=require('node:assert/strict');
const {seasonRankPoints,seasonCondition}=require('../site/season.js');
const p=(extra={})=>({n:100,points:629,top2:40,top3:60,accident_min:0,unknown:0,...extra});
const general=seasonRankPoints('general');
test('one remaining start yields second or better using unrounded target arithmetic',()=>{
  const r=seasonCondition(p(),6.30,'A1',[general]);
  assert.equal(r.needed,8);assert.equal(r.bestAllowed,2);
  assert.equal(seasonCondition(p({points:630}),6.30,'A1',[general]).needed,7);
});
test('two starts produce required total and boundary combinations',()=>{
  const r=seasonCondition(p(),6.30,'A1',[general,general]);
  assert.equal(r.needed,14);assert.deepEqual(r.examples,[[1,4],[2,3]]);assert.equal(r.unordered,true);
});
test('SG and finals change the qualifying place; mixed races keep order',()=>{
  assert.deepEqual(seasonRankPoints('sg',true),[13,11,9,8,6,5]);
  assert.equal(seasonCondition(p({points:628}),6.30,'A1',[seasonRankPoints('sg',true)]).bestAllowed,3);
  assert.equal(seasonCondition(p(),6.30,'A1',[general,seasonRankPoints('sg',true)]).unordered,false);
});
test('minimum starts, ratios and accident lower bound prevent misleading success',()=>{
  assert.equal(seasonCondition(p({n:88}),6.3,'A1',[general]).state,'starts_short');
  const r=seasonCondition(p({points:1000,top2:30,top3:41}),6.3,'A1',[general]);
  assert.equal(r.bestAllowed,2);assert.equal(r.top2Needed,1);
  assert.equal(seasonCondition(p({accident_min:80}),6.3,'A1',[general]).state,'accident_block');
});
test('safe, impossible, zero-start and unknown states are explicit',()=>{
  assert.equal(seasonCondition(p({points:700}),6.3,'A1',[general]).state,'safe');
  assert.equal(seasonCondition(p({points:600}),6.3,'A1',[general]).state,'impossible');
  assert.equal(seasonCondition(p({points:630}),6.3,'A1',[]).state,'met');
  assert.equal(seasonCondition(p(),6.3,'A1',[]).state,'unmet');
  assert.equal(seasonCondition(p({unknown:1}),6.3,'A1',[general]).state,'blocked');
  assert.equal(seasonCondition(p(),NaN,'A1',[general]).state,'blocked');
});
test('all published one-start thresholds agree with direct integer score and ratio checks',()=>{
  for(let points=600;points<=650;points++)for(const kind of ['general','graded','sg'])for(const final of [false,true]){
    const source=p({points,top2:30,top3:40}),scores=seasonRankPoints(kind,final),r=seasonCondition(source,6.3,'A1',[scores]);
    const ranks=[1,2,3,4,5,6].filter(rank=>(points+scores[rank-1])*100>=630*101&&
      (source.top2+Number(rank<=2))*10>=3*101&&(source.top3+Number(rank<=3))*10>=4*101);
    if(!ranks.length)assert.equal(r.state,'impossible');else assert.equal(r.bestAllowed,Math.max(...ranks));
  }
});
