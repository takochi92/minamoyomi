// Exercise the real application with a DOM double. Not a layout test.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function boot(open=false){
 const nodes=new Map(),calls=[];
 const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',open:false,setAttribute(){},addEventListener(){}});return nodes.get(id);};
 const summary={races:1,hits:0,invest:100,return:0};
 const demo={'stats.json':{all:summary,last30:summary,last7:summary,days:[],best:[]},'model_report.json':JSON.parse(fs.readFileSync(require.resolve('../site/data/model_report.json'),'utf8'))};
 const window={__ROUTE__:'stats',__OPEN_LOGIC__:open,__DEMO__:demo,SITE_CONFIG:{}};
 const context={window,document:{querySelector:node,querySelectorAll:()=>[]},location:{hash:''},console:{...console,error(e){throw e;}},
  setInterval(){throw Error('demo should not poll');}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../site/app.js'),'utf8'),context);
 return {node,demo,calls};
}
(async()=>{
 // Evidence is loaded only after opening its details, independent of stats rendering.
 const a=boot(),get=a.node;
 await new Promise(r=>setImmediate(r));
 assert.match(get('#app').innerHTML,/実績と根拠/);
 assert.equal(get('#logic-body').innerHTML,'');
 get('#logic-details').open=true;await get('#logic-details').ontoggle();
 assert.match(get('#logic-body').innerHTML,/予想の根拠/);
 assert.match(get('#logic-body').innerHTML,/過去|検証/);
 get('#logic-body').innerHTML='retained';await get('#logic-details').ontoggle();
 assert.equal(get('#logic-body').innerHTML,'retained');
 const old=boot(true);await new Promise(r=>setImmediate(r));
 assert.equal(old.node('#logic-details').open,true);
 assert.match(old.node('#logic-body').innerHTML,/予想の根拠/);
 console.log('Combined stats/evidence lazy loading and old-URL auto-open checks passed (DOM double).');
})().catch(e=>{console.error(e);process.exitCode=1;});
