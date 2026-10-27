export function jst(now=new Date()) {
 const s=new Date(now.getTime()+9*3600000).toISOString();
 return {day:s.slice(0,10).replace(/-/g,''),date:s.slice(0,10),hm:s.slice(11,16),hour:Number(s.slice(11,13))};
}
export function morningWindow(time) {
 return time.hm >= '07:30' && time.hm < '10:00';
}
export function validSubscription(s) {
 try {const u=new URL(s.endpoint);
 return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&!u.hash&&!!u.pathname.slice(1)&&
 /^(?:fcm\.googleapis\.com|updates\.push\.services\.mozilla\.com|web\.push\.apple\.com|[a-z0-9-]+\.notify\.windows\.com)$/.test(u.hostname)&&
 /^[A-Za-z0-9_-]{87,88}$/.test(s.keys.p256dh)&&/^[A-Za-z0-9_-]{22,24}$/.test(s.keys.auth);
 } catch {return false;}
}
export function matches(feed,device,now=new Date()) {
 const time=jst(now);if(feed?.date!==time.day)return [];
 const found=new Map();
 for(const [racer,frames] of Object.entries(device.rules||{})) {
  if(!/^\d{4}$/.test(racer)||!Array.isArray(frames)||frames.some(f=>!Number.isInteger(f)||f<1||f>6))continue;
  for(const r of feed.racers?.[racer]||[]) {
   if(!Array.isArray(r)||r.length!==5)continue;
   const [venue,rno,path,deadline,frame]=r;
   if(!Number.isInteger(frame)||!frames.includes(frame)||!Number.isInteger(rno)||rno<1||rno>12||
    !/^([01]\d|2[0-3]):[0-5]\d$/.test(deadline)||deadline<=time.hm||
    !new RegExp('^race/'+time.day+'/[a-z]+-'+rno+'\\.html$').test(path))continue;
   found.set(racer+':'+path,{racer,name:String(device.racer_names?.[racer]||racer).slice(0,30),venue:String(venue).slice(0,15),rno,path,deadline,frame});
  }
 }
 return [...found.values()].sort((a,b)=>(a.deadline+a.path+a.racer).localeCompare(b.deadline+b.path+b.racer));
}
export function payload(rows,day,kind='morning') {
 if(kind==='test')return {title:'艇ろぐの通知テスト',body:'この端末にテスト通知が届きました。朝の出走通知もこの端末で受け取れます。',day,tag:'teilog-test-'+day,url:'/mynote?morning='+day};
 const lines=rows.slice(0,4).map(r=>`${r.name} ${r.venue}${r.rno}R ${r.frame}号艇 ${r.deadline}`);
 if(rows.length>4)lines.push(`ほか${rows.length-4}件。タップで一覧`);
 return {title:`お気に入りの出走 ${rows.length}件`,body:lines.join('\n'),day,tag:'teilog-morning-'+day,url:'/mynote?morning='+day};
}
