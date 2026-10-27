/* Authenticated, opt-in morning digest. No private endpoints in public data. */
(function(){
 'use strict';
 var A=window.TeiNoteAccount,root=document.getElementById('race-notifications');if(!A)return;
 async function stopNotifications(owner){
  var settings=(window.SITE_CONFIG||{}).notifications||{};
  if(settings.enabled&&owner&&A.identity()===owner){
   try{var deviceId=localStorage.getItem('teilog_push_device_v1:'+owner);
    if(deviceId){var old=await A.notificationCall('read',{device_id:deviceId});
     if(old&&old.enabled)await A.notificationCall('save',{device_id:deviceId,push_subscription:old.subscription,push_rules:old.rules,turn_on:false,expected_revision:old.revision});
    }
   }catch(_){} // A disconnected server must not prevent local unsubscription.
  }
  if('serviceWorker' in navigator){var r=await navigator.serviceWorker.getRegistration('/'),s=r&&await r.pushManager.getSubscription();if(s&&!await s.unsubscribe())throw new Error('端末の通知をオフにしてからログアウトしてください。');}
 }
 window.TeiRaceNotifications={beforeSignOut:()=>stopNotifications(A.identity())};
 var previousIdentity=A.identity();
 A.subscribe(function(){var next=A.identity();if(previousIdentity&&previousIdentity!==next)stopNotifications(previousIdentity).catch(()=>{});previousIdentity=next;});
 if(!root)return;
 var cfg=(window.SITE_CONFIG||{}).notifications||{},record=null,device,epoch=0,uid=null,busy=false,loaded=false,active=false,error='',notice='',draft={},todayFeed=null,favoritesVersion='';
 fetch('/fav-today.json',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>{todayFeed=d;draw();}).catch(()=>{});
 function node(tag,text){var e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
 function supported(){return window.isSecureContext&&'Notification' in window&&'serviceWorker' in navigator&&'PushManager' in window;}
 function id(){if(!device){var k='teilog_push_device_v1:'+A.identity();device=localStorage.getItem(k);if(!device){device=crypto.randomUUID();localStorage.setItem(k,device);}}return device;}
 function key(){return Uint8Array.from(atob(cfg.vapidPublicKey.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));}
 function check(e,u){if(epoch!==e||A.identity()!==u)throw new Error('ログイン状態が変わりました。');}
 async function registration(){await navigator.serviceWorker.register('/sw.js',{scope:'/',updateViaCache:'none'});return Promise.race([navigator.serviceWorker.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error('通知の準備が完了しませんでした。通信を確認して再度お試しください。')),20000))]);}
 async function save(on,sub,e,u){
  check(e,u);var revision=await A.notificationCall('save',{device_id:id(),push_subscription:sub,push_rules:draft,turn_on:on,expected_revision:record?record.revision:0});
  check(e,u);record={revision:revision,subscription:sub,rules:JSON.parse(JSON.stringify(draft)),enabled:on};active=on;
 }
 async function action(kind){
  if(busy||!loaded)return;busy=true;error='';notice='';var e=epoch,u=A.identity(),created=null;draw();
  try{
   if(kind==='off'){
    await save(false,record.subscription,e,u);
    var reg=await registration(),sub=await reg.pushManager.getSubscription();check(e,u);if(sub)await sub.unsubscribe();
   }else if(kind==='test'){
    await A.notificationCall('test',{device_id:id()});check(e,u);notice='テスト通知を送信しました。端末の通知を確認してください。同日のテスト送信は１回です。';
   }else if(kind==='save')await save(record.enabled,record.subscription,e,u);
   else{
    if(!Object.values(draft).some(x=>x.length))throw new Error('通知したい選手の枠番を選んでください。');
    var permission=Notification.permission==='default'?await Notification.requestPermission():Notification.permission;
    if(permission!=='granted')throw new Error('端末の通知が許可されていません。ブラウザの設定を確認してください。');
    check(e,u);var r=await registration();check(e,u);var s=await r.pushManager.getSubscription();check(e,u);
    if(!s){s=await r.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key()});created=s;}
    check(e,u);await save(true,s.toJSON(),e,u);
   }
  }catch(err){if(created)try{await created.unsubscribe();}catch(_){}if(e===epoch)error=err.message||'通知設定を保存できませんでした。';}
  finally{if(e===epoch){busy=false;draw();}}
 }
 function draw(){
  var notebook=document.getElementById('note-app');if(notebook&&A.state().ready&&root.nextElementSibling!==notebook)notebook.before(root);
  root.replaceChildren();root.append(node('h2','朝のお気に入り出走通知'));
  root.append(node('p','朝8時台を目安に、対象レースをまとめて通知します。対象がない日は通知しません。配信・端末の状態で遅れたり届かない場合があります。'));
  if(!A.state().user){root.append(node('p','お気に入りを保存したアカウントでログインしてください。'));return;}
  if(!supported()){root.append(node('p','このブラウザでは通知を利用できません。iPhone・iPadはホーム画面に追加した艇ろぐで確認してください。'));return;}
  var ready=cfg.enabled&&cfg.vapidPublicKey;
  root.append(node('p',ready?(record&&record.enabled&&active?'この端末の通知：オン':'この端末の通知：オフ'):'通知配信は準備中です。枠番の選択は試せますが、まだ保存・配信はできません。'));
  root.append(node('p','出走表の枠番（号艇）で選びます。実際の進入コースとは異なる場合があります。未選択の選手・枠番は通知しません。設定はこの端末用です。'));
  var favorites=A.data().fav||{},keys=Object.keys(favorites);
  if(!keys.length)root.append(node('p','選手ページの☆でお気に入りを登録してください。'));
  keys.forEach(function(t){
   var field=node('fieldset');field.className='push-racer';field.append(node('legend',favorites[t].name||t));
   [1,2,3,4,5,6].forEach(function(f){
    var label=node('label'),input=node('input');input.type='checkbox';input.checked=(draft[t]||[]).includes(f);input.disabled=busy;
    input.setAttribute('aria-label',(favorites[t].name||t)+' '+f+'号艇');
    input.addEventListener('change',function(){var a=new Set(draft[t]||[]);if(input.checked)a.add(f);else a.delete(f);draft[t]=Array.from(a).sort();draw();});
    label.append(input,document.createTextNode(f+'号艇'));field.append(label);
   });root.append(field);
  });
  if(todayFeed&&todayFeed.date===new Date(Date.now()+9*3600000).toISOString().slice(0,10).replace(/-/g,'')){
   var list=node('ul');root.append(node('h3','今日の通知条件に合う出走'));
   keys.forEach(function(t){(todayFeed.racers[t]||[]).forEach(function(r){
    if(!(draft[t]||[]).includes(r[4])||!/^race\/\d{8}\/[a-z]+-\d{1,2}\.html$/.test(r[2]))return;
    var li=node('li'),a=node('a',(favorites[t].name||t)+' '+r[0]+r[1]+'R '+r[4]+'号艇 '+r[3]+'締切');a.href='/'+r[2];li.append(a);list.append(li);
   });});root.append(list.childElementCount?list:node('p','選択中の条件に合う出走はありません。'));
  }
  if(error){var err=node('p',error);err.setAttribute('role','alert');root.append(err);}
  if(notice)root.append(node('p',notice));
  var buttons=node('div');buttons.className='push-buttons';
  [['on','この端末の通知をオン'],['save','選んだ枠番を保存'],['test','テスト通知を送る'],['off','この端末の通知をオフ']].forEach(function(x){
   var b=node('button',x[1]);b.type='button';b.disabled=busy||!ready||!loaded||!A.state().ready||(x[0]!=='on'&&!record)||(x[0]==='test'&&(!record||!record.enabled||!active));
   b.addEventListener('click',()=>action(x[0]));buttons.append(b);
  });root.append(buttons);if(busy)root.append(node('p','通知設定を確認しています…'));
 }
 async function load(){
  if(!A.state().ready){if(A.identity()!==uid){epoch++;record=null;draft={};device=null;uid=null;loaded=false;busy=false;}draw();return;}
  var next=A.identity(),version=JSON.stringify(A.data().fav||{});if(next===uid&&version===favoritesVersion){draw();return;}
  var sameUser=next===uid,previousDraft=sameUser?draft:{};favoritesVersion=version;
  uid=next;epoch++;record=null;device=null;draft=previousDraft;busy=false;loaded=false;error='';notice='';var e=epoch;draw();
  if(!next||!cfg.enabled||!cfg.vapidPublicKey)return;
  try{var data=await A.notificationCall('read',{device_id:id()});check(e,next);
   var reg=supported()&&await navigator.serviceWorker.getRegistration('/'),sub=reg&&await reg.pushManager.getSubscription();check(e,next);
   record=data;active=!!(sub&&data&&data.subscription.endpoint===sub.toJSON().endpoint&&Notification.permission==='granted');
   draft=Object.assign({},data?JSON.parse(JSON.stringify(data.rules)):{},previousDraft);loaded=true;draw();}
  catch(_){if(e===epoch){error='通知設定を読み込めません。再読み込みしてください。';draw();}}
 }
 window.TeiRaceNotifications={beforeSignOut:async function(){
  epoch++;busy=false;
  await stopNotifications(A.identity());
 }};
 A.subscribe(load);load();
})();
