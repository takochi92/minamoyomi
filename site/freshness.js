/* Check PUBLIC data while visible. Never store race responses or reload edits. */
(function () {
  'use strict';
  var box = document.getElementById('page-freshness');
  if (!box) return;
  var status = box.querySelector('[data-fresh-status]'), button = box.querySelector('button');
  var revision = box.dataset.revision || '', source = box.dataset.source;
  var edited = false, busy = false, newer = false;
  function safeToReload() {
    var active = document.activeElement;
    if (edited || document.hidden || (active && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName))) return false;
    var account = window.TeiNoteAccount && window.TeiNoteAccount.state();
    return !account || ((!account.configured || account.ready) &&
      (!account.user || (account.mode === 'account' && account.message === '同期済み')));
  }
  function label(message) {
    var text = message + (revision ? '（表示中 ' + revision.slice(11, 16) + '時点）' : '');
    if (status.textContent !== text) status.textContent = text;
  }
  function reload() { location.reload(); }
  button.addEventListener('click', reload);
  document.addEventListener('input', function (event) {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) edited = true;
  });
  document.addEventListener('change', function (event) {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) edited = true;
  });
  async function check() {
    if (document.hidden || busy || !source) return;
    busy = true;
    var controller = new AbortController(), timer = setTimeout(function () { controller.abort(); }, 8000);
    try {
      var url = new URL(source, location.href);
      if (url.origin !== location.origin) return;
      url.searchParams.set('fresh', String(Date.now()));
      var response = await fetch(url.href, {cache:'no-store',signal:controller.signal});
      if (!response.ok) throw Error('unavailable');
      var data = await response.json(), at = box.dataset.key ? (data.races || {})[box.dataset.key] : data.updated_at;
      if (typeof at === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(at) && (!revision || at > revision)) {
        newer = true;
        label('新しい情報があります。更新してください');
        button.textContent = '最新情報を表示';
        if (safeToReload()) {
          // A CDN serving an older HTML document must not cause a reload loop.
          var key = 'teilog_public_refresh:' + url.pathname + ':' + (box.dataset.key || ''), permit = true;
          try {
            permit = sessionStorage.getItem(key) !== at;
            if (permit) sessionStorage.setItem(key, at);
          } catch (_) { permit = false; }
          if (permit) reload();
        }
      } else if (!newer) {
        var age = revision ? Date.now() - new Date(revision + '+09:00').getTime() : 0;
        label(age > 600000 ? '公開データに10分以上更新がありません' : '公開済みの最新データを確認しました');
      }
    } catch (_) {
      if (!newer) label('更新を確認できません。通信状態をご確認ください');
    } finally { clearTimeout(timer); busy = false; }
  }
  label('最新データを確認中');
  document.addEventListener('visibilitychange', function () { if (!document.hidden) check(); });
  window.addEventListener('pageshow', check);
  window.addEventListener('online', check);
  setInterval(check, 60000);
  check();
})();
