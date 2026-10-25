/* Only the public offline explanation is cached. Never cache race pages,
   odds, notes, OAuth callbacks, API responses, or authenticated requests. */
'use strict';
const OFFLINE_CACHE = 'teilog-pwa-offline-v1';
self.addEventListener('install', event => {
  event.waitUntil(caches.open(OFFLINE_CACHE).then(cache =>
    cache.add(new Request('/offline.html', {cache:'reload'}))
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
    return await cache.match('/offline.html') || new Response(
      '通信できません。接続を確認して再読み込みしてください。',
      {status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}}
    );
  }));
});
