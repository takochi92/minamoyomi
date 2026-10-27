/* Only the public offline explanation is cached. Never cache race pages,
   odds, notes, OAuth callbacks, API responses, or authenticated requests. */
'use strict';
const OFFLINE_CACHE = 'teilog-pwa-offline-v2';
self.addEventListener('install', event => {
  event.waitUntil(caches.open(OFFLINE_CACHE).then(cache =>
    cache.add(new Request('/offline', {cache:'reload'}))
  ).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key =>
    key.startsWith('teilog-pwa-offline-') && key !== OFFLINE_CACHE
  ).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== 'GET' || request.mode !== 'navigate' ||
      url.origin !== self.location.origin ||
      /^\/mynote(?:\.html)?\/?$/.test(url.pathname) ||
      url.searchParams.has('code') || url.searchParams.has('error') ||
      request.headers.has('Authorization')) return;
  event.respondWith(fetch(request, {cache:'no-store'}).catch(async () => {
    const cache = await caches.open(OFFLINE_CACHE);
    return await cache.match('/offline') || new Response(
      '通信できません。接続を確認して再読み込みしてください。',
      {status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}}
    );
  }));
});

self.addEventListener('push', event => {
  event.waitUntil((async () => {
    let message;try { message=event.data.json(); } catch (_) { return; }
    const day=new Date(Date.now()+9*3600000).toISOString().slice(0,10).replace(/-/g,'');
    if(!message || message.day!==day || message.tag!=='teilog-morning-'+day ||
      message.url!=='/mynote?morning='+day || typeof message.title!=='string' || typeof message.body!=='string')return;
    await self.registration.showNotification(message.title.slice(0,80),{
      body:message.body.slice(0,600),tag:message.tag,icon:'/img/pwa-192-v2.png',
      data:{url:message.url},renotify:false
    });
  })());
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const path=event.notification.data && event.notification.data.url;
  if(typeof path!=='string'||!/^\/mynote\?morning=\d{8}$/.test(path))return;
  event.waitUntil(self.clients.openWindow(new URL(path,self.location.origin).href));
});
