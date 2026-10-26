'use strict';
// Display only. No labels, inferred frames, interval calculation, or persistence.
function sceneFrames(clip, scene) {
  const ids = new Set(clip.scenes[scene] || []);
  const frames = clip.frames.filter(f => ids.has(f.index));
  if (!frames.length || frames.some((f, i) => !Number.isFinite(f.time) ||
      (i && (f.index !== frames[i-1].index + 1 || f.time <= frames[i-1].time || f.time - frames[i-1].time > .12)))) return [];
  return frames;
}
function watchPlan(bundle, boats, scene) {
  const gate = scene === 'turn' ? 'A' : scene;
  const rows = boats.map(boat => {
    const clip = bundle.clips.find(c => c.boat === boat);
    const frames = clip ? sceneFrames(clip, scene) : [];
    const anchor = bundle.anchors[boat + ':' + gate];
    const synced = anchor?.basis === 'two_review_mean' && Number.isFinite(anchor.time) &&
      anchor.source_sha256 === bundle.source.sha256 && frames.length &&
      anchor.time >= frames[0].time && anchor.time <= frames.at(-1).time;
    const origin = synced ? anchor.time : frames[0]?.time;
    return { boat, frames, synced: !!synced, origin };
  });
  if (!rows.length || rows.some(r => !r.frames.length)) return { rows, ticks: [], reason: 'この場面の連続コマがありません。' };
  if (rows.length > 1 && rows.some(r => !r.synced)) return { rows, ticks: [], reason: '同期未確認の艇があります。１艇を選ぶと単独で閲覧できます。' };
  const start = Math.max(...rows.map(r => r.frames[0].time - r.origin));
  const end = Math.min(...rows.map(r => r.frames.at(-1).time - r.origin));
  if (end < start) return { rows, ticks: [], reason: '共通して収録された範囲がありません。' };
  const times = rows.flatMap(r => r.frames.map(f => f.time-r.origin)).filter(t => t >= start && t <= end);
  const ticks = [...new Set([start, ...times, end])].sort((a,b) => a-b)
    .filter((t,i,a) => !i || t-a[i-1] > 1e-7);
  return { rows, ticks, reason: '' };
}
function frameAt(row, relative) {
  const target = row.origin + relative;
  // Show the actual frame at/before the requested PTS, never synthesize one.
  let lo = 0, hi = row.frames.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo+hi)/2);
    if (row.frames[mid].time <= target + 1e-7) lo = mid; else hi = mid-1;
  }
  return row.frames[lo];
}
if (typeof module !== 'undefined') module.exports = { sceneFrames, watchPlan, frameAt };
if (typeof document !== 'undefined') {
  const $ = id => document.getElementById(id);
  const bundle = JSON.parse($('watch-bundle').textContent);
  let selected = [bundle.clips[0].boat], scene = 'turn', speed = .5;
  let plan, pos = 0, playing = false, timer = null, version = 0;
  const cache = new Map(), cards = new Map();
  function stop(message) {
    playing = false; version++;
    clearTimeout(timer); timer = null;
    $('play').textContent = '▶ 再生'; $('play').setAttribute('aria-pressed', 'false');
    if (message) $('status').textContent = message;
  }
  function image(index) {
    if (!cache.has(index)) {
      const promise = new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => { cache.delete(index); reject(Error('画像を読み込めません。「画像を再読込」でやり直せます。')); };
        img.src = bundle.images[index];
      });
      cache.set(index, promise);
      while (cache.size > 24) cache.delete(cache.keys().next().value);
    }
    return cache.get(index);
  }
  function createCard(row) {
    const card = document.createElement('section'); card.className = 'card';
    const header = document.createElement('header'), title = document.createElement('h2');
    const tag = document.createElement('span'); tag.className = 'boat-tag b' + row.boat; tag.textContent = row.boat;
    title.append(tag, document.createTextNode(row.boat + '号艇'));
    const sync = document.createElement('span'); sync.className = 'sync' + (row.synced ? '' : ' missing');
    sync.textContent = row.synced ? '固定線で同期' : '同期未確認';
    const zoom = document.createElement('button'); zoom.textContent = '拡大'; zoom.dataset.action = 'zoom';
    const solo = document.createElement('button'); solo.textContent = 'この艇だけ'; solo.dataset.action = 'solo';
    solo.onclick = () => { selected = [row.boat]; rebuild(); };
    const canvas = document.createElement('canvas'); [canvas.width, canvas.height] = bundle.size;
    canvas.setAttribute('aria-label', row.boat + '号艇の展示映像');
    const clock = document.createElement('small');
    header.append(title, sync, zoom, solo); card.append(header, canvas, clock); $('grid').append(card);
    const state = { canvas, clock, scale: 1, center: [bundle.size[0]/2, bundle.size[1]/2] };
    cards.set(row.boat, state);
    zoom.onclick = () => { stop(); state.scale = state.scale === 1 ? 2 : 1; zoom.textContent = state.scale === 1 ? '拡大' : '全体'; render(); };
    canvas.onclick = e => {
      stop();
      if (state.scale === 1) { render(); return; }
      const rect = canvas.getBoundingClientRect(), [w,h] = bundle.size;
      state.center = [state.center[0] + ((e.clientX-rect.left)/rect.width-.5)*w/state.scale,
        state.center[1] + ((e.clientY-rect.top)/rect.height-.5)*h/state.scale];
      state.center = state.center.map((v,i) => Math.max(0,Math.min(bundle.size[i],v)));
      render();
    };
  }
  function rebuild() {
    stop(); pos = 0; cache.clear(); cards.clear(); $('grid').replaceChildren();
    plan = watchPlan(bundle, selected, scene);
    $('grid').dataset.count = String(selected.length);
    for (const row of plan.rows) createCard(row);
    for (const b of $('boats').children) b.setAttribute('aria-pressed', String(selected.includes(+b.dataset.boat)));
    for (const id of ['play','restart','prev','next','seek']) $(id).disabled = !plan.ticks.length;
    render();
  }
  async function render() {
    const token = ++version;
    clearTimeout(timer); timer = null;
    $('seek').max = Math.max(0, plan.ticks.length-1); $('seek').value = pos;
    $('position').textContent = plan.ticks.length ? `${pos+1} / ${plan.ticks.length}` : '—';
    $('status').textContent = plan.reason || '画像を読み込んでいます…';
    // Remove stale frames immediately, including when a replacement fails to load.
    for (const {canvas,clock} of cards.values()) {
      const ctx = canvas.getContext('2d'); ctx.resetTransform(); ctx.clearRect(0,0,canvas.width,canvas.height); clock.textContent = '';
    }
    const relative = plan.ticks[pos];
    const chosen = plan.rows.map(row => ({ row, frame: frameAt(row, Number.isFinite(relative) ? relative : row.frames[0]?.time-row.origin) }));
    try {
      const loaded = await Promise.all(chosen.map(({frame}) => frame ? image(frame.index) : Promise.resolve(null)));
      if (token !== version) return;
      chosen.forEach(({row,frame},i) => {
        if (!frame || !loaded[i]) return;
        const {canvas,clock,scale,center} = cards.get(row.boat), ctx = canvas.getContext('2d');
        ctx.setTransform(scale,0,0,scale,canvas.width/2-center[0]*scale,canvas.height/2-center[1]*scale);
        ctx.drawImage(loaded[i],0,0,...bundle.size);
        for (const [name,g] of Object.entries(bundle.gates)) {
          ctx.strokeStyle = { A:'#f1c66a',B:'#69e3c8',C:'#76b5ff' }[name]; ctx.lineWidth = 3/scale; ctx.beginPath();
          if (g.axis === 'x') { ctx.moveTo(g.value,g.segment[0]); ctx.lineTo(g.value,g.segment[1]); }
          else { ctx.moveTo(g.segment[0],g.value); ctx.lineTo(g.segment[1],g.value); }
          ctx.stroke();
        }
        clock.dataset.pts = frame.pts;
        clock.dataset.frame = frame.index;
        const delta = frame.time - row.origin;
        clock.textContent = row.synced ? `基準線の ${Math.abs(delta).toFixed(2)}秒${delta < 0 ? '前' : '後'}（映像内）` : `コマ ${row.frames.indexOf(frame)+1} / ${row.frames.length}`;
      });
      $('status').textContent = plan.reason || (playing ? 'スロー再生中' : '再生・コマ送りで向きの変化を確認できます。');
      if (playing) {
        if (pos >= plan.ticks.length-1) { stop('再生終了。再生ボタンで先頭から見られます。'); return; }
        const delay = (plan.ticks[pos+1]-plan.ticks[pos])*1000/speed;
        timer = setTimeout(() => { if (token !== version || !playing) return; pos++; render(); }, Math.max(1,delay));
        // Bounded next-frame prefetch; no skipped frames on slow connections.
        for (const row of plan.rows) image(frameAt(row,plan.ticks[pos+1]).index).catch(() => {});
      }
    } catch (error) {
      if (token === version) stop(error.message);
    }
  }
  for (const clip of bundle.clips) {
    const b = document.createElement('button'); b.dataset.boat = clip.boat;
    const tag = document.createElement('span'); tag.className = 'boat-tag b'+clip.boat; tag.textContent = clip.boat;
    b.append(tag,document.createTextNode(clip.boat+'号艇'));
    b.onclick = () => {
      if (selected.includes(clip.boat)) { if (selected.length === 1) return; selected = selected.filter(n => n !== clip.boat); }
      else selected = [...selected,clip.boat].sort((a,b) => a-b);
      rebuild();
    };
    $('boats').append(b);
  }
  $('all').onclick = () => { selected = bundle.clips.map(c => c.boat); rebuild(); };
  $('single').onclick = () => { selected = [selected[0]]; rebuild(); };
  $('scene').onchange = e => { scene = e.target.value; rebuild(); };
  $('speed').onchange = e => { const active = playing; stop(); speed = [.25,.5,1].includes(+e.target.value) ? +e.target.value : .5; playing = active; render(); updatePlay(); };
  function updatePlay() { $('play').textContent = playing ? 'Ⅱ 停止' : '▶ 再生'; $('play').setAttribute('aria-pressed',String(playing)); }
  $('play').onclick = () => { const active = playing; stop(); playing = !active; if (playing && pos >= plan.ticks.length-1) pos = 0; updatePlay(); render(); };
  $('restart').onclick = () => { stop(); pos = 0; render(); };
  $('prev').onclick = () => { stop(); pos = Math.max(0,pos-1); render(); };
  $('next').onclick = () => { stop(); pos = Math.min(plan.ticks.length-1,pos+1); render(); };
  $('seek').oninput = e => { stop(); pos = Math.max(0,Math.min(plan.ticks.length-1,+e.target.value)); render(); };
  $('retry').onclick = () => { stop(); cache.clear(); render(); };
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop('画面を離れたため一時停止しました。'); else render(); });
  window.addEventListener('pagehide', () => stop());
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => {
    window.parent.postMessage({kind:'teilog-exhibition-height',height:Math.ceil(document.querySelector('main').getBoundingClientRect().height+4)},'*');
  }).observe(document.querySelector('main'));
  rebuild();
}
