const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function boot(query=''){
 const nodes=new Map(),messages={};let changedUrl=null;
 const config={date:'20261026',preview:true,raceBase:'',slugs:{'04':'heiwajima','05':'tamagawa'},records:[{date:'20261026',jcd:'04',rno:1,asset:'data/exhibition/20261026/04-1.html'}]};
 function node(id){if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,style:{},contentWindow:{},removeAttribute(k){delete this[k];}});return nodes.get(id);}
 const venue=node('ev-venue');venue.options=[{value:'04',textContent:'平和島'},{value:'05',textContent:'多摩川'}];
 Object.defineProperty(venue,'selectedIndex',{get(){return this.options.findIndex(o=>o.value===this.value);}});
 node('ev-config').textContent=JSON.stringify(config);
 const context={document:{getElementById:node},URLSearchParams,location:{search:query},history:{replaceState(a,b,url){changedUrl=url;}},window:{addEventListener(k,fn){messages[k]=fn;}},console};
 vm.runInNewContext(fs.readFileSync(require.resolve('../site/exhibition.js'),'utf8'),context);
 return{node,messages,get url(){return changedUrl;},submit(){node('ev-select').onsubmit({preventDefault(){}});}};
}
const ui=boot(),get=ui.node;
assert.equal(get('ev-frame').src,'data/exhibition/20261026/04-1.html?mode=watch');
assert.match(get('ev-back').href,/heiwajima-1\.html#tenji$/);
assert.equal(get('ev-review').href,'data/exhibition/20261026/04-1.html');
ui.messages.message({source:{},data:{kind:'teilog-exhibition-height',height:600}});assert.equal(get('ev-frame').style.height,undefined);
ui.messages.message({source:get('ev-frame').contentWindow,data:{kind:'teilog-exhibition-height',height:600}});assert.equal(get('ev-frame').style.height,'600px');
ui.messages.message({source:get('ev-frame').contentWindow,data:{kind:'teilog-exhibition-height',height:999999}});assert.equal(get('ev-frame').style.height,'600px');
get('ev-race').value='2';get('ev-race').onchange();
assert.equal(get('ev-frame').src,undefined);assert.ok(get('ev-view').hidden);
ui.submit();assert.match(get('ev-status').textContent,/未収録/);assert.equal(get('ev-frame').src,undefined);assert.match(ui.url,/rno=2/);
get('ev-date').value='2026-02-30';ui.submit();assert.ok(get('ev-back').hidden);assert.equal(get('ev-frame').src,undefined);
const deep=boot('?date=20261026&jcd=04&rno=12');assert.ok(deep.node('ev-view').hidden);assert.match(deep.node('ev-title').textContent,/12R/);
const invalid=boot('?date=20260230&jcd=04&rno=1');assert.ok(invalid.node('ev-view').hidden);assert.equal(invalid.node('ev-frame').src,undefined);
console.log('exhibition selector/deep-link/empty-state/frame-isolation checks ok (DOM double)');
