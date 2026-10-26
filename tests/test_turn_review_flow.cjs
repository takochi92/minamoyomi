// Event-flow checks with a small DOM/canvas double. Not a browser layout test.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function boot(pending=false){
 const nodes=new Map(),all=[],blobs=[],images=[];
 class Element{
  constructor(){this.dataset={};this.children=[];this.value='';this.checked=false;this.textContent='';this.attrs={};this.files=[];all.push(this);}
  append(e){this.children.push(e);}setAttribute(k,v){this.attrs[k]=v;}click(){if(this.onclick)this.onclick({});}
  getBoundingClientRect(){return{left:0,top:0,width:320,height:180};}
  getContext(){return new Proxy({}, {get:()=>()=>{},set:()=>true});}
 }
 const document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement(){return new Element();},
  querySelectorAll(selector){const key=selector.match(/\[data-(.*?)\]/)[1];return all.filter(n=>n.dataset[key]!==undefined);}};
 const frames=Array.from({length:25},(_,i)=>({index:i,time:i/30,proposal:[700,300,80,40]}));
 const bundle={digest:'fixture',size:[1280,720],source_clock:'browser_capture_clock_unverified',gates:{A:{axis:'x',value:500,segment:[400,600]}},
  events:Array.from({length:6},(_,i)=>['A','B','C'].map(g=>({boat:i+1,gate:g,frames}))).flat(),images:Object.fromEntries(frames.map(f=>[f.index,'test-image']))};
 document.getElementById('bundle').textContent=JSON.stringify(bundle);
 for(const p of ['bow','stern']){const e=new Element();e.dataset.point=p;}
 for(const p of ['before','after']){const e=new Element();e.dataset.side=p;}
 class Image{constructor(){this.complete=!pending;this.naturalWidth=pending?0:1280;images.push(this);}set src(v){this._src=v;}}
 const context={document,Image,Blob,URL:{createObjectURL(b){blobs.push(b);return'blob:test';},revokeObjectURL(){}},console};
 vm.runInNewContext(fs.readFileSync(require.resolve('../tools/turn_review/review.js'),'utf8'),context);
 return{document,all,blobs,images,bundle};
}
(async()=>{
 const ui=boot(),get=id=>ui.document.getElementById(id),canvas=get('canvas');
 canvas.onclick({clientX:100,clientY:100});canvas.onclick({clientX:120,clientY:100});
 ui.all.find(e=>e.dataset.side==='before').click();get('next').click();ui.all.find(e=>e.dataset.side==='after').click();
 get('reviewer').value='reviewer-1';get('trajectory').checked=true;get('export').click();
 let draft=JSON.parse(await ui.blobs.at(-1).text());
 assert.deepEqual(draft.labels['1:12'],{bow:[400,400],stern:[480,400]});
 assert.deepEqual(draft.pairs['1:A'],{before:12,after:13});
 assert.equal(draft.publication_ready,false);assert.equal(draft.source_clock,'browser_capture_clock_unverified');
 get('zoom').click();canvas.onclick({clientX:160,clientY:90});get('export').click();
 draft=JSON.parse(await ui.blobs.at(-1).text());assert.deepEqual(draft.labels['1:13'].bow,[740,320]);
 ui.all.find(e=>e.dataset.boat===2).click();canvas.onclick({clientX:160,clientY:90});get('export').click();
 draft=JSON.parse(await ui.blobs.at(-1).text());assert.ok(draft.labels['2:0']);assert.ok(draft.labels['1:12']);
 const delayed=boot(true),delayedCanvas=delayed.document.getElementById('canvas');
 delayedCanvas.onclick({clientX:100,clientY:100});
 assert.match(delayed.document.getElementById('status').textContent,/読込完了/);
 delayed.document.getElementById('reviewer').value='reviewer';delayed.document.getElementById('export').click();
 assert.deepEqual(JSON.parse(await delayed.blobs.at(-1).text()).labels,{});
 console.log('turn review click/zoom/frame/export/loading checks ok (DOM double; browser layout unverified)');
})().catch(error=>{console.error(error);process.exitCode=1;});
