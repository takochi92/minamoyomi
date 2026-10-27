const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const events={},shown=[],opened=[];let closed=0;
const self={location:{origin:'https://teilog.com'},addEventListener:(t,f)=>events[t]=f,
 registration:{showNotification:async(t,o)=>shown.push({t,o})},clients:{openWindow:async u=>opened.push(u)}};
vm.runInNewContext(fs.readFileSync('site/sw.js','utf8'),{self,URL,Date,Response,Request,caches:{}});
const day=new Date(Date.now()+9*3600000).toISOString().slice(0,10).replace(/-/g,'');
async function push(x){let done;events.push({data:{json:()=>x},waitUntil:p=>done=p});await done;}
(async()=>{
 await push({title:'朝の出走',body:'選手A 4号艇',day,tag:'teilog-morning-'+day,url:'/mynote?morning='+day});
 assert.equal(shown.length,1);assert.equal(shown[0].o.renotify,false);
 for(const bad of [{day:'20000101'},{url:'https://evil.example'},{body:null},{tag:'other'}])await push({...shown[0].o,title:'x',day,url:'/mynote?morning='+day,...bad});
 assert.equal(shown.length,1);
 let done;events.notificationclick({notification:{close:()=>closed++,data:{url:'/mynote?morning='+day}},waitUntil:p=>done=p});await done;
 assert.equal(closed,1);assert.deepEqual(opened,['https://teilog.com/mynote?morning='+day]);
 events.notificationclick({notification:{close(){},data:{url:'https://evil.example'}},waitUntil(){throw Error('unsafe');}});
 console.log('Push worker: dated payload, private same-origin link, malformed payload rejection passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
