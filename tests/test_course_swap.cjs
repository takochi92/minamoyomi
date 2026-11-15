// 進入の入れ替え：入れ替えたあとの数字が、選手ごとの「そのコースでの成績」になることを確かめる。
const assert = require('node:assert/strict');
const m = require('../site/course-swap.js');

// c[コース] = [出走, 1着, 2着, 3着, ST合計(秒), STの件数]
const boats = [
  {f:1,n:'A',k:1,c:{'1':[56,37,11,1,7.84,56],'4':[39,5,7,12,6.24,39]}},
  {f:2,n:'B',k:2,c:{'2':[36,7,9,5,5.04,36]}},
  {f:3,n:'C',k:3,c:{'3':[48,9,9,8,7.68,48]}},
  {f:4,n:'D',k:4,c:{'1':[27,14,4,2,3.96,27],'4':[33,3,3,7,4.62,33]}},
  {f:5,n:'E',k:6,c:{'6':[39,0,2,11,7.41,39]}},
  {f:6,n:'F',k:5,c:{'5':[44,1,11,10,0,0]}},
];
// 最初の並びは、保存されているコース（展示のあとは展示の進入）のまま
const start = m.initial(boats);
assert.deepEqual(start,[1,2,3,4,6,5]);
let rows = m.rows(boats,start);
assert.deepEqual(rows.map(r=>r.course),[1,2,3,4,5,6]);
assert.deepEqual(rows[0].stats,{n:56,win:66.1,top2:85.7,top3:87.5,st:0.14});   // 37/56, 48/56, 49/56, 7.84/56
assert.equal(rows[4].frame,6,'The boat colour follows the frame, not the course');
assert.equal(rows[4].stats.st,null,'No start timing on record: leave it blank');

// 1コースと4コースを入れ替える：それぞれ「入った先のコース」での成績になる
const swapped = start.slice(); [swapped[0],swapped[3]] = [swapped[3],swapped[0]];
rows = m.rows(boats,swapped);
assert.equal(rows[0].frame,4);
assert.deepEqual(rows[0].stats,{n:27,win:51.9,top2:66.7,top3:74.1,st:0.15});   // 14/27, 18/27, 20/27, 3.96/27
assert.equal(rows[3].frame,1);
assert.deepEqual(rows[3].stats,{n:39,win:12.8,top2:30.8,top3:61.5,st:0.16});   // 5/39, 12/39, 24/39, 6.24/39
assert.deepEqual(rows[1].stats,m.rows(boats,start)[1].stats,'Untouched boats keep their numbers');

// 走ったことのないコースは、数字を作らない
const far = start.slice(); [far[1],far[5]] = [far[5],far[1]];
rows = m.rows(boats,far);
assert.equal(rows[1].stats,null);
assert.equal(rows[5].stats,null);
assert.equal(m.stats([0,0,0,0,0,0]),null);
// 進入順にタップ：タップした艇が内側から入り、残りは元の並びのまま続く
assert.deepEqual(m.compose(start,[]),start);
assert.deepEqual(m.compose(start,[4]),[4,1,2,3,6,5]);
assert.deepEqual(m.compose(start,[4,1]),[4,1,2,3,6,5]);
assert.deepEqual(m.compose(start,[6,5,4,3,2,1]),[6,5,4,3,2,1]);
console.log('course swap: OK');
