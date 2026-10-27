/* Optional private account synchronization. Guest notes remain on this browser. */
(function () {
  'use strict';
  var M = window.TeiNoteModel, GUEST = 'teilog_note_v1', OPS = 'teilog_note_pending_v1:';
  var cfg = (window.SITE_CONFIG || {}).account || {};
  // Rollout gate for live OAuth checks. This controls visibility, not data access;
  // Google test-user restrictions and database RLS enforce access separately.
  var rolloutReady = !cfg.verificationOnly;
  if (cfg.verificationOnly) {
    try {
      if (new URL(location.href).searchParams.get('note-sync-check') === '1') sessionStorage.setItem('teilog_note_check_v1', '1');
      rolloutReady = sessionStorage.getItem('teilog_note_check_v1') === '1';
    } catch (_) { rolloutReady = false; }
  }
  var configured = !!(cfg.url && cfg.publishableKey && location.origin === 'https://teilog.com' && rolloutReady);
  var client = null, user = null, generation = 0, cloud = M.empty(), revision = 0;
  var data = M.empty(), callbacks = [], timer, flight = null, panel, counter = 0, guestBroken = false;
  var state = { configured: configured, ready: !configured, mode: 'guest', message: '', conflicts: [] };
  function clone(x) { return M.copy(x); }
  function guest() { return M.normalize(JSON.parse(localStorage.getItem(GUEST) || '{}')); }
  try { data = guest(); } catch (_) { guestBroken = true; state.ready = false; state.message = '端末の記録を読み込めません。元の保存データは変更していません。'; }
  function esc(x) { return String(x == null ? '' : x).replace(/[&<>"']/g, function (c) { return { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]; }); }
  function notify(reason) { draw(); callbacks.forEach(function (f) { f(reason || 'status'); }); }
  function prefix() { return OPS + user.id + ':'; }
  function pending() {
    if (!user) return [];
    var p = prefix(), out = [];
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (k && k.startsWith(p)) { var op = JSON.parse(localStorage.getItem(k)); if (op && op.id) out.push(op); }
    }
    return out.sort(function (a, b) { return a.at - b.at || a.id.localeCompare(b.id); });
  }
  function append(changes) {
    var added = [];
    try {
      changes.forEach(function (op) {
        op = clone(op); op.id = crypto.randomUUID(); op.at = Date.now() * 1000 + counter++ % 1000;
        localStorage.setItem(prefix() + op.id, JSON.stringify(op)); added.push(op.id);
      });
    } catch (e) { added.forEach(function (id) { localStorage.removeItem(prefix() + id); }); throw e; }
  }
  function remove(ids) { ids.forEach(function (id) { localStorage.removeItem(prefix() + id); }); }
  function setData(d, reason) {
    var next = M.normalize(d), changed = !M.same(M.flatten(next), M.flatten(data));
    data = next; notify(reason === 'identity' ? reason : changed ? (reason || 'data') : 'status');
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(function () { sync(); }, 900); }
  function save(before, after) {
    if (!state.ready) throw new Error('記録の読み込みが完了していません。');
    var next = M.normalize(after), changes = M.changes(before, next);
    if (!user) { localStorage.setItem(GUEST, JSON.stringify(next)); data = next; notify('saved'); return clone(data); }
    append(changes);
    data = M.overlay(cloud, pending()); state.message = '同期待ち'; notify('saved'); schedule();
    return clone(data);
  }
  function authError(e) {
    state.message = '同期できませんでした。未同期の変更はこの端末に残っています。通信を確認して「同期」を押してください。';
    // Do not expose server errors, tokens, or private payloads in the UI/logs.
    state.mode = 'error'; notify();
  }
  async function readRemote(force) {
    var uid = user.id;
    var r = await client.from('teilog_notes').select(force ? 'data,revision' : 'revision').eq('user_id', uid).maybeSingle();
    if (r.error) throw r.error;
    if (!force && (r.data ? r.data.revision : 0) !== revision) return readRemote(true);
    return { data: force ? M.normalize(r.data ? r.data.data : {}) : cloud, revision: r.data ? r.data.revision : 0 };
  }
  function conflictRows(conflicts) {
    var rows = {};
    conflicts.forEach(function (c) { rows[c.op.key] = { key: c.op.key, remote: c.remote, local: c.op.value }; });
    return Object.values(rows);
  }
  async function sync(force) {
    if (!client || !user) return;
    if (flight) return flight;
    var epoch = generation;
    flight = (async function () {
      try {
        for (var attempt = 0; attempt < 3; attempt++) {
          var r = await readRemote(force || !state.ready);
          if (epoch !== generation) return;
          cloud = r.data; revision = r.revision;
          var ops = pending(), merged = M.rebase(cloud, ops);
          if (merged.conflicts.length) {
            state.ready = true; state.mode = 'conflict'; state.message = '別の端末の変更と重なっています。両方を確認して選んでください。';
            state.conflicts = conflictRows(merged.conflicts); setData(M.overlay(cloud, ops)); return;
          }
          if (!ops.length || M.same(M.flatten(cloud), M.flatten(merged.data))) {
            remove(merged.acknowledged);
          } else {
            var w = await client.rpc('teilog_save_notes', { expected_revision: revision, note_data: merged.data, expected_user_id: user.id });
            if (epoch !== generation) return;
            if (w.error) { if (w.error.code === '40001') { force = true; continue; } throw w.error; }
            revision = Number(w.data); cloud = merged.data; remove(merged.acknowledged);
          }
          state.ready = true; state.mode = 'account'; state.conflicts = []; state.message = pending().length ? '同期待ち' : '同期済み';
          setData(M.overlay(cloud, pending()));
          if (pending().length) schedule();
          return;
        }
        throw new Error('Concurrent changes');
      } catch (e) { if (epoch === generation) authError(e); }
    })();
    try { await flight; } finally { if (epoch === generation) flight = null; }
  }
  async function changeUser(next) {
    var nextId = next && next.id;
    if ((user && user.id) === nextId) return;
    generation++; flight = null; clearTimeout(timer); user = next || null; cloud = M.empty(); revision = 0;
    state.conflicts = []; state.ready = !user; state.mode = user ? 'loading' : 'guest'; state.message = user ? 'ノートを読み込み中…' : '';
    var nextData = M.empty();
    if (!user) {
      try { nextData = guest(); guestBroken = false; }
      catch (_) { guestBroken = true; state.ready = false; state.message = '端末の記録を読み込めません。元の保存データは変更していません。'; }
    }
    setData(nextData, 'identity');
    if (user) await sync(true);
  }
  function exportData(value, name) {
    var url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 1)], { type:'application/json' }));
    var a = document.createElement('a'); a.href = url; a.download = name || 'teilog-note-backup.json'; a.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function importData(value) {
    var incoming = M.normalize(value);
    if (!state.ready) throw new Error('ノートの読み込みを待ってください。');
    if (user) {
      append(M.changes(M.empty(), incoming));
      data = M.overlay(cloud, pending()); notify('data'); schedule();
    } else {
      var merged = M.importGuest(data, incoming);
      if (merged.conflicts.length) throw new Error('同じ項目に違う記録があります。現在の記録をファイルに保存してから内容を確認してください。上書きはしていません。');
      save(data, merged.data); notify('data');
    }
  }
  function resolve(key, local) {
    var ops = pending(), sameKey = ops.filter(function (o) { return o.key === key; });
    if (!sameKey.length) return;
    var last = sameKey[sameKey.length - 1], cells = M.flatten(cloud);
    if (local) append([{ key:key, before:cells[key] == null ? null : cells[key], value:last.value }]);
    remove(sameKey.map(function (o) { return o.id; }));
    state.conflicts = state.conflicts.filter(function (c) { return c.key !== key; });
    setData(M.overlay(cloud, pending())); sync(true);
  }
  function label(c) {
    var kind = c.key.split(':')[0], v = c.local || c.remote || {};
    return ({racer:'選手メモ',motor:'モーターメモ',fav:'お気に入り',bet:'収支',budget:'予算'}[kind] || '記録') + ' ' + (v.name || v.date || '');
  }
  function describe(v) {
    if (v == null) return '削除';
    if (typeof v === 'number') return v.toLocaleString() + '円';
    return v.text || v.name || ((v.date || '') + ' 購入' + (v.inv || 0) + '円／払戻' + (v.ret || 0) + '円 ' + (v.memo || ''));
  }
  function draw() {
    if (!panel) return;
    var ownGuest = false;
    try { ownGuest = Object.keys(M.flatten(guest())).length > 1 || guest().budget > 0; } catch (_) {}
    panel.hidden = !configured && !state.message;
    if (panel.hidden) return;
    panel.innerHTML = '<div class="account-line"><h2>' + (user ? 'アカウントのノート' : 'ノートを端末間で共有') + '</h2>' +
      (user ? '<span class="sub account-user">' + esc(user.email || 'ログイン中') + '</span>' : '') + '</div>' +
      '<p class="sub account-status" role="status">' + esc(state.message || (configured ? 'Googleでログインすると、お気に入り・メモ・収支をスマホとPCで共有できます。登録せずにも使えます。' : '')) + '</p>' +
      (configured ? '<div class="account-actions">' + (user ?
        '<button type="button" data-account="sync">同期</button><button type="button" data-account="logout">ログアウト</button>' +
        (ownGuest && state.ready ? '<button type="button" data-account="import">この端末の記録を取り込む</button>' : '') :
        '<button type="button" data-account="login"' + (!client ? ' disabled' : '') + '>Googleでログイン</button>' +
        (state.mode === 'error' ? '<button type="button" data-account="reload">再読み込み</button>' : '')) + '</div>' : '') +
      (configured && !user ? '<p class="sub">ログインにはGoogleの認証情報を使い、記録はSupabaseに保存します。<a href="' + (window.SITE_ROOT || '') + 'about.html">プライバシーポリシー</a></p>' : '') +
      (user ? '<p class="sub">ログイン中の編集は、このアカウントに保存します。端末内の記録は勝手に取り込みません。</p>' : '') +
      state.conflicts.map(function (c) { return '<div class="account-conflict"><strong>' + esc(label(c)) + '</strong><div class="account-compare"><div><small>別の端末の記録</small><p>' + esc(describe(c.remote)) + '</p><button type="button" data-choice="remote" data-key="' + esc(c.key) + '">こちらを残す</button></div><div><small>この端末の変更</small><p>' + esc(describe(c.local)) + '</p><button type="button" data-choice="local" data-key="' + esc(c.key) + '">こちらを残す</button></div></div></div>'; }).join('') +
      (user ? '<details class="account-settings"><summary>アカウントの管理</summary><p class="sub">削除すると、このアカウントと同期済みの記録が消えます。必要な記録は先にファイルへ保存してください。</p><button type="button" data-account="delete">アカウントを削除</button></details>' : '') +
      (location.origin === 'https://teilog.com' ? '<details class="account-settings"><summary>旧URLでノートを使っていた方へ</summary><p class="sub"><a href="https://teilog.pages.dev/mynote" target="_blank" rel="noopener">旧ノートを開く</a> →「ファイルに保存」→ このページの「ファイルから読み込む」で引き継げます。記録した端末・ブラウザで操作してください。</p></details>' : '');
    panel.querySelectorAll('[data-account]').forEach(function (b) { b.addEventListener('click', function () { action(b.dataset.account); }); });
    panel.querySelectorAll('[data-choice]').forEach(function (b) { b.addEventListener('click', function () { try { resolve(b.dataset.key, b.dataset.choice === 'local'); } catch (e) { authError(e); } }); });
  }
  async function action(name) {
    var actionEpoch = generation, actionUser = user && user.id;
    try {
      if (name === 'reload') { location.reload(); }
      else if (name === 'login') {
        var r = await client.auth.signInWithOAuth({provider:'google',options:{redirectTo:'https://teilog.com/mynote'}});
        if (r.error) throw r.error;
      } else if (name === 'sync') await sync(true);
      else if (name === 'import') {
        if (confirm('このブラウザにあるメモ・お気に入り・収支を、ログイン中のアカウントへ取り込みます。元の記録も残します。続けますか？')) importData(guest());
      } else if (name === 'logout') {
        if (pending().length && !confirm('未同期の変更があります。この端末に保存してある変更は、同じアカウントで再ログインすると同期できます。今ログアウトしますか？')) return;
        if(window.TeiRaceNotifications) await window.TeiRaceNotifications.beforeSignOut();
        var out = await client.auth.signOut({scope:'local'});
        if (out.error) throw out.error;
        if (actionEpoch === generation) await changeUser(null);
      } else if (name === 'delete') {
        if (!confirm('このアカウントと同期済みのメモ・お気に入り・収支を完全に削除します。元に戻せません。削除しますか？')) return;
        var removed = await client.rpc('teilog_delete_own_account', {expected_user_id:actionUser});
        if (removed.error) throw removed.error;
        if (actionEpoch !== generation) return;
        remove(pending().map(function (o) { return o.id; }));
        await client.auth.signOut({scope:'local'}); await changeUser(null);
      }
    } catch (e) { authError(e); }
  }
  function loadSdk() {
    return new Promise(function (resolve, reject) {
      if (window.supabase) { resolve(); return; }
      var s = document.createElement('script'); s.src = (window.SITE_ROOT || '') + 'vendor/supabase-2.118.0.js';
      s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
    });
  }
  async function init() {
    var note = document.getElementById('note-app');
    if (note) { panel = document.createElement('section'); panel.className = 'panel note-account'; panel.id = 'note-account'; note.before(panel); draw(); }
    if (!configured) return;
    state.mode = 'loading'; state.message = 'ログイン状態を確認中…'; notify();
    try {
      var u = new URL(cfg.url);
      if (u.protocol !== 'https:' || !/^[a-z0-9-]+\.supabase\.co$/.test(u.hostname)) throw new Error('Invalid service URL');
      if (!cfg.publishableKey.startsWith('sb_publishable_')) {
        var claims = JSON.parse(atob(cfg.publishableKey.split('.')[1]));
        if (claims.role !== 'anon') throw new Error('A public key is required');
      }
      await loadSdk();
      client = window.supabase.createClient(cfg.url, cfg.publishableKey, {auth:{flowType:'pkce',storageKey:'teilog_auth_v1',persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
      client.auth.onAuthStateChange(function (event, session) {
        setTimeout(function () { changeUser(session && session.user).catch(authError); }, 0);
      });
      var session = await client.auth.getSession();
      if (session.error) throw session.error;
      if (session.data.session) await changeUser(session.data.session.user);
      else { state.ready = !guestBroken; state.mode = 'guest'; if (!guestBroken) state.message = ''; notify('identity'); }
      setInterval(function () { if (!document.hidden && user && state.mode !== 'conflict') sync(); }, 90000);
      window.addEventListener('online', function () { sync(true); });
      document.addEventListener('visibilitychange', function () { if (!document.hidden) sync(); });
      window.addEventListener('storage', function (e) {
        if (user && e.key && e.key.startsWith(prefix())) { if (state.ready) setData(M.overlay(cloud, pending())); schedule(); }
        else if (!user && e.key === GUEST) { try { setData(guest()); } catch (_) {} }
      });
      window.addEventListener('beforeunload', function (e) { if (user && pending().length) { e.preventDefault(); e.returnValue = ''; } });
    } catch (e) { state.ready = false; authError(e); }
  }
  async function notificationCall(name, args) {
    if (!client || !user || !state.ready) throw new Error('ログインと読み込みの完了が必要です。');
    var epoch=generation, uid=user.id, result;
    if(name==='read') result=await client.from('teilog_push_devices').select('id,subscription,rules,enabled,revision').eq('user_id',uid).eq('id',args.device_id).maybeSingle();
    else if(name==='save') result=await client.rpc('teilog_save_push',Object.assign({},args,{expected_user_id:uid}));
    else if(name==='test') result=await client.functions.invoke('favorite-morning',{body:{action:'test',device_id:args.device_id}});
    else throw new Error('未対応の通知操作です。');
    if(epoch!==generation || !user || user.id!==uid) throw new Error('ログイン状態が変わりました。');
    if(result.error){
      if(name==='test')throw new Error(result.error.context&&result.error.context.status===409?'本日のテスト通知は送信済みです。端末の通知設定を確認してください。':'テスト通知を送信できませんでした。通信と端末の通知設定を確認してください。');
      throw new Error('通知設定を保存できませんでした。通信を確認してページを読み直してください。');
    }
    return result.data;
  }
  window.TeiNoteAccount = { notificationCall:notificationCall, identity:function(){return user?user.id:null;}, data:function () { return clone(data); }, save:save, importData:importData,
    subscribe:function (f) { callbacks.push(f); }, state:function () { return Object.assign({}, state, {user:!!user}); }, exportData:exportData };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
