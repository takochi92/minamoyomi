// @deno-types="npm:@types/web-push@3.6.4"
import webpush from 'web-push';
import {timingSafeEqual} from 'node:crypto';
import {Buffer} from 'node:buffer';
import {jst,matches,payload,validSubscription} from './logic.mjs';

const base=Deno.env.get('SUPABASE_URL')!,service=Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const cors={'Access-Control-Allow-Origin':'https://teilog.com','Access-Control-Allow-Headers':'authorization,apikey,content-type,x-client-info','Access-Control-Allow-Methods':'POST,OPTIONS','Vary':'Origin'};
const reply=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status,headers:{...cors,'Content-Type':'application/json'}});
async function rest(path:string,method='GET',data?:unknown){
 const r=await fetch(base+'/rest/v1/'+path,{method,headers:{apikey:service,Authorization:'Bearer '+service,'Content-Type':'application/json'},
  body:data===undefined?undefined:JSON.stringify(data),redirect:'error',signal:AbortSignal.timeout(15000)});
 if(!r.ok)throw Error('Database unavailable');const text=await r.text();return text?JSON.parse(text):null;
}
const rpc=(name:string,data={})=>rest('rpc/'+name,'POST',data);
function equal(a:string,b:string){return a.length===64&&b.length===64&&timingSafeEqual(Buffer.from(a),Buffer.from(b));}

Deno.serve(async req=>{
 if(req.method==='OPTIONS')return new Response(null,{headers:cors});
 if(req.method!=='POST')return reply({error:'Method not allowed'},405);
 try{
  const job=req.headers.get('x-job-key')||'',authorization=req.headers.get('authorization')||'';
  if(!/^[a-f0-9]{64}$/.test(job)&&!authorization.startsWith('Bearer '))return reply({error:'Authentication required'},401);
  let userId:string|null=null;
  if(!job){
   const r=await fetch(base+'/auth/v1/user',{headers:{apikey:service,Authorization:authorization},signal:AbortSignal.timeout(10000)});
   if(!r.ok)return reply({error:'Authentication required'},401);userId=(await r.json()).id;
  }
  let runtime=await rpc('teilog_push_runtime');
  if(job&&!equal(job,runtime.job_key||''))return reply({error:'Authentication required'},401);
  const body=await req.json();
  if(body.action==='bootstrap'&&job){
   if(!runtime.vapid){await rpc('teilog_push_init_keys',{key_data:webpush.generateVAPIDKeys()});runtime=await rpc('teilog_push_runtime');}
   return reply({ready:!!runtime.vapid,publicKey:runtime.vapid.publicKey});
  }
  if(!runtime.enabled||!runtime.vapid)return reply({error:'通知配信は準備中です。'},503);
  const now=new Date(),time=jst(now),kind=body.action==='test'?'test':'morning';
  if(kind==='test'&&!userId)return reply({error:'Authentication required'},401);
  if(kind==='morning'&&(!job||body.action!=='morning'))return reply({error:'Not allowed'},403);
  if(kind==='morning'&&(time.hour<8||time.hour>=10))return reply({skipped:'outside morning window'});
  const summary={sent:0,failed:0,skipped:0};
  async function send(device:any,rows:any[]){
   if(!device.enabled||!validSubscription(device.subscription)){summary.skipped++;return;}
   if(!await rpc('teilog_claim_push',{target_device:device.id,target_day:time.date,expected_revision:device.revision,target_kind:kind})){summary.skipped++;return;}
   let status='failed';
   try{
    const current=await rest('teilog_push_devices?select=enabled,revision&id=eq.'+device.id);
    if(!current[0]?.enabled||current[0].revision!==device.revision){summary.skipped++;return;}
    await webpush.sendNotification(device.subscription,JSON.stringify(payload(rows,time.day,kind)),{
     vapidDetails:{subject:'https://teilog.com',...runtime.vapid},TTL:kind==='test'?120:Math.min(3600,(10-time.hour)*3600-Number(time.hm.slice(3))*60),timeout:10000});
    status='sent';summary.sent++;
   }catch(error:any){summary.failed++;if([404,410].includes(error?.statusCode)){
    status='expired';await rest('teilog_push_devices?id=eq.'+device.id+'&revision=eq.'+device.revision,'PATCH',{enabled:false,revision:device.revision+1});
   }}finally{
    await rest(`teilog_push_deliveries?device_id=eq.${device.id}&day=eq.${time.date}&kind=eq.${kind}`,'PATCH',{status});
   }
  }
  if(kind==='test'){
   if(!/^[a-f0-9-]{36}$/.test(body.device_id||''))return reply({error:'Invalid device'},400);
   const devices=await rest('teilog_push_devices?id=eq.'+body.device_id+'&user_id=eq.'+userId+'&limit=1');
   if(!devices[0]?.enabled)return reply({error:'先にこの端末の通知をオンにしてください。'},400);
   await send(devices[0],[]);
   return reply(summary,summary.failed?502:summary.sent?200:409);
  }
  const feedResponse=await fetch('https://teilog.com/fav-today.json',{cache:'no-store',signal:AbortSignal.timeout(10000)});
  if(!feedResponse.ok)throw Error('Programme unavailable');const feed=await feedResponse.json();
  if(feed.date!==time.day)return reply({error:'Programme not current'},503);
  let cursor='';const started=Date.now();
  while(Date.now()-started<75000){
   const devices=await rest('teilog_push_devices?enabled=eq.true&order=id&limit=100'+(cursor?'&id=gt.'+cursor:''));
   if(!devices.length)break;cursor=devices.at(-1).id;
   for(let i=0;i<devices.length&&Date.now()-started<75000;i+=5)await Promise.all(devices.slice(i,i+5).map((d:any)=>{const rows=matches(feed,d,now);return rows.length?send(d,rows):Promise.resolve(summary.skipped++);}));
   if(devices.length<100)break;
  }
  await rpc('teilog_push_finish',{summary});return reply(summary);
 }catch(_){return reply({error:'通知処理を完了できませんでした。時間をおいて再度確認してください。'},500);}
});
