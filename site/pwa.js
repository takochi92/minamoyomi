(function () {
  'use strict';
  if (location.origin !== 'https://teilog.com') return;
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', {scope:'/',updateViaCache:'none'}).catch(function () {});
    });
  }
  var pending, banner, action, timer, shown = false, paused = false, completed = false;
  var button = document.getElementById('install-app'), status = document.getElementById('install-status');
  var UNTIL = 'teilog_install_later_v1', DONE = 'teilog_installed_v1', SEEN = 'teilog_install_seen_v1';
  var mode = window.matchMedia('(display-mode: standalone)');
  function read(storage, key) { try { return window[storage].getItem(key); } catch (_) { return null; } }
  function write(storage, key, value) { try { window[storage].setItem(key, String(value)); } catch (_) {} }
  function standalone() { return mode.matches || navigator.standalone === true; }
  function installed() { return completed || standalone() || read('localStorage', DONE) === '1'; }
  function hide() {
    clearTimeout(timer);
    if (banner) { banner.remove(); banner = null; action = null; }
  }
  function postpone(days) {
    paused = true; write('localStorage', UNTIL, Date.now() + days * 86400000); hide();
  }
  function showInstalled() {
    completed = true; write('localStorage', DONE, '1'); hide();
    if (button) button.hidden = true;
    if (status) status.textContent = 'ホーム画面から起動しています。';
  }
  function editing() {
    var el = document.activeElement;
    return el && (!banner || !banner.contains(el)) && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  }
  function eligible() {
    var url = new URL(location.href), path = url.pathname.replace(/\.html$/, '').replace(/\/$/, '');
    var mobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || (/Macintosh/i.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
    return !installed() && !paused && !shown && !document.hidden && !editing() &&
      !document.querySelector('dialog[open], [aria-modal="true"]:not([hidden])') &&
      path !== '/install' && path !== '/offline' &&
      !url.searchParams.has('code') && !url.searchParams.has('error') && !/access_token=/.test(url.hash) &&
      !(Number(read('localStorage', UNTIL)) > Date.now()) && !read('sessionStorage', SEEN) &&
      (mobile || !!pending);
  }
  function position() {
    if (!banner) return;
    var header = document.querySelector('.top');
    banner.style.top = Math.max(8, Math.ceil(header ? header.getBoundingClientRect().bottom : 0) + 8) + 'px';
  }
  function paintAction() {
    if (!action) return;
    action.textContent = pending ? '追加する' : '追加方法';
    action.href = '/install';
  }
  function offer() {
    if (!eligible()) return;
    shown = true; write('sessionStorage', SEEN, '1');
    banner = document.createElement('aside');
    banner.id = 'pwa-install-banner'; banner.className = 'pwa-install-banner';
    banner.setAttribute('aria-label', '艇ろぐをホーム画面に追加');
    banner.innerHTML = '<img src="/img/pwa-192-v2.png" width="46" height="46" alt="">' +
      '<div class="pwa-install-copy"><strong>艇ろぐをホーム画面に追加</strong><span>アイコンから、すぐに開けます</span></div>' +
      '<a class="pwa-install-action" href="/install">追加方法</a>' +
      '<button class="pwa-install-close" type="button" aria-label="追加の案内を閉じる">×</button>';
    action = banner.querySelector('.pwa-install-action'); paintAction();
    action.addEventListener('click', function (event) {
      if (pending) { event.preventDefault(); requestInstall(); }
      else { event.preventDefault(); postpone(30); location.assign('/install'); }
    });
    banner.querySelector('.pwa-install-close').addEventListener('click', function () { postpone(30); });
    document.body.appendChild(banner); position();
    requestAnimationFrame(function () { if (banner) banner.classList.add('pwa-install-visible'); });
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(offer, 2800); }
  async function requestInstall() {
    if (!pending) return;
    var prompt = pending; pending = null; hide();
    if (button) button.hidden = true;
    try {
      // Keep prompt() directly inside the click gesture; never open it automatically.
      await prompt.prompt(); var choice = await prompt.userChoice;
      postpone(choice.outcome === 'accepted' ? 90 : 30);
      if (status) status.textContent = choice.outcome === 'accepted' ? '追加が完了したら、ホーム画面の「艇ろぐ」から開けます。' : 'あとからブラウザのメニューでも追加できます。';
    } catch (_) {
      postpone(30);
      if (status) status.textContent = '下の手順でブラウザのメニューから追加してください。';
      else location.assign('/install');
    }
  }
  if (standalone()) showInstalled();
  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault(); pending = event;
    // A new browser install offer also handles a previously uninstalled app.
    if (!standalone()) { completed = false; write('localStorage', DONE, '0'); }
    if (button && !installed()) button.hidden = false;
    if (banner) paintAction(); else schedule();
  });
  if (button) button.addEventListener('click', requestInstall);
  window.addEventListener('appinstalled', function () {
    pending = null; showInstalled();
    if (status) status.textContent = '追加しました。ホーム画面の「艇ろぐ」から開けます。';
  });
  if (mode.addEventListener) mode.addEventListener('change', function () { if (standalone()) showInstalled(); });
  window.addEventListener('resize', position);
  window.addEventListener('scroll', position, { passive: true });
  document.addEventListener('focusin', function () { if (editing()) hide(); });
  document.addEventListener('focusout', function () { if (!shown) schedule(); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) schedule(); });
  schedule();
})();
