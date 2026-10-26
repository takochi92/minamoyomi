/* Local-only annotation/replay desk. Viewing speed never changes evidence time. */
function hullMidpoint(label) {
  return label && label.bow && label.stern
    ? [(label.bow[0] + label.stern[0]) / 2, (label.bow[1] + label.stern[1]) / 2] : null;
}
function canvasPoint(x, y, rect, width, height) {
  return [Math.max(0, Math.min(width - 1, (x - rect.left) * width / rect.width)),
    Math.max(0, Math.min(height - 1, (y - rect.top) * height / rect.height))];
}
function sourcePoint(p, zoom, offset) { return [(p[0] - offset[0]) / zoom, (p[1] - offset[1]) / zoom]; }
function frameDelay(a, b, speed) {
  const gap = b.time - a.time;
  if (![0.25, 0.5, 1].includes(speed) || !Number.isFinite(gap) || gap <= 0 || gap > 0.2) return null;
  return Math.max(16, gap * 1000 / speed);
}
function previewIntervals(bundle, boat, pairs, labels) {
  const frames = (bundle.clips || []).find(c => c.boat === boat)?.frames ||
    bundle.events.filter(e => e.boat === boat).flatMap(e => e.frames);
  const events = {};
  for (const name of ['A', 'B', 'C']) {
    const pair = pairs[boat + ':' + name], gate = bundle.gates[name];
    if (!pair || !gate) continue;
    const a = frames.find(f => f.index === pair.before), b = frames.find(f => f.index === pair.after);
    if (!a || !b || !(b.time > a.time && b.time - a.time <= .12)) continue;
    const la = labels[boat + ':' + a.index], lb = labels[boat + ':' + b.index];
    const ca = hullMidpoint(la), cb = hullMidpoint(lb);
    if (!ca || !cb || [la, lb].some(l => Math.hypot(l.bow[0] - l.stern[0], l.bow[1] - l.stern[1]) < 8)) continue;
    const axis = gate.axis === 'x' ? 0 : 1, other = 1 - axis;
    if (!(gate.direction === 1 ? ca[axis] < gate.value && cb[axis] >= gate.value : ca[axis] > gate.value && cb[axis] <= gate.value)) continue;
    const ratio = (gate.value - ca[axis]) / (cb[axis] - ca[axis]);
    const where = ca[other] + ratio * (cb[other] - ca[other]);
    if (where < gate.segment[0] || where > gate.segment[1]) continue;
    events[name] = a.time + ratio * (b.time - a.time);
  }
  const interval = (a, b) => Number.isFinite(events[a]) && Number.isFinite(events[b]) && events[b] > events[a]
    ? +(events[b] - events[a]).toFixed(1) : null;
  return { entry: interval('A', 'B'), exit: interval('B', 'C'), publication_ready: false };
}
function acceptDraft(value, bundle) {
  const compatible = value.bundle_digest === bundle.digest || (bundle.compatible_digests || []).includes(value.bundle_digest);
  if (value.kind !== 'turn-review-draft-v1' || !compatible) throw Error('違う映像・設定の下書きです');
  if (!value.labels || typeof value.labels !== 'object' || Array.isArray(value.labels)) throw Error('下書きの形式を確認してください');
  const keys = new Set([...bundle.events, ...(bundle.clips || [])].flatMap(e => e.frames.map(f => e.boat + ':' + f.index)));
  for (const [key, label] of Object.entries(value.labels)) {
    if (!keys.has(key) || !label || typeof label !== 'object' || Array.isArray(label)) throw Error('不明なコマです');
    for (const name of ['bow', 'stern']) {
      if (label[name] && (!Array.isArray(label[name]) || label[name].length !== 2 ||
        label[name].some((v, i) => !Number.isFinite(v) || v < 0 || v >= bundle.size[i]))) throw Error('測定点の位置が不正です');
    }
  }
  if (!value.pairs || typeof value.pairs !== 'object' || Array.isArray(value.pairs)) throw Error('前後コマの形式が不正です');
  for (const [key, pair] of Object.entries(value.pairs)) {
    const event = bundle.events.find(e => e.boat + ':' + e.gate === key);
    const clip = event && (bundle.clips || []).find(e => e.boat === event.boat);
    if (!event || !pair || typeof pair !== 'object' || Object.keys(pair).some(k =>
      !['before', 'after'].includes(k) || !(clip || event).frames.some(f => f.index === pair[k]))) throw Error('前後コマの指定が不正です');
  }
  return value;
}
if (typeof module !== 'undefined') module.exports = { hullMidpoint, canvasPoint, sourcePoint, frameDelay, previewIntervals, acceptDraft };
if (typeof document !== 'undefined') {
  const bundle = JSON.parse(document.getElementById('bundle').textContent);
  const $ = id => document.getElementById(id), canvas = $('canvas'), ctx = canvas.getContext('2d');
  let boat = 1, gate = 'A', pos = 12, point = 'bow', showProposal = false, labels = {}, pairs = {};
  let imageToken = 0, readyFrame = null, zoom = 1, offset = [0, 0], scene = 'turn';
  let playing = false, speed = 0.5, timer = null, runVersion = 0;
  const imageCache = new Map();
  function current() {
    if (scene === 'turn') {
      const clip = (bundle.clips || []).find(e => e.boat === boat);
      if (clip) return clip;
    }
    return bundle.events.find(e => e.boat === boat && e.gate === gate);
  }
  function frame() { pos = Math.min(pos, current().frames.length - 1); return current().frames[pos]; }
  function labelKey() { return boat + ':' + frame().index; }
  function playLabel() {
    $('play').textContent = playing ? 'Ⅱ 一時停止' : '▶ ゆっくり再生';
    $('play').setAttribute('aria-pressed', String(playing));
  }
  function stopPlayback(message) {
    playing = false; runVersion++;
    if (timer !== null) clearTimeout(timer);
    timer = null; playLabel();
    if (message) $('status').textContent = message;
  }
  function queueNext() {
    if (!playing || readyFrame !== frame().index || timer !== null) return;
    const frames = current().frames;
    if (pos >= frames.length - 1) { stopPlayback('再生終了。もう一度押すと先頭から再生します。'); return; }
    const delay = frameDelay(frames[pos], frames[pos + 1], speed);
    if (delay === null) { stopPlayback('コマの欠落・時刻の逆転があるため再生を停止しました。'); return; }
    const version = runVersion;
    timer = setTimeout(() => {
      timer = null;
      if (!playing || version !== runVersion) return;
      pos++; update();
    }, delay);
    // Prepare the next image, but never skip a frame if decoding takes longer.
    getImage(frames[pos + 1].index);
  }
  function startPlayback(fromBeginning = false) {
    stopPlayback();
    if (fromBeginning || pos >= current().frames.length - 1) pos = 0;
    playing = true; runVersion++; update();
  }
  function getImage(index) {
    if (!imageCache.has(index)) {
      const image = new Image(); image.src = bundle.images[index]; imageCache.set(index, image);
    }
    const image = imageCache.get(index);
    imageCache.delete(index); imageCache.set(index, image);
    while (imageCache.size > 4) imageCache.delete(imageCache.keys().next().value);
    return image;
  }
  function update() {
    const ev = current(), fr = frame();
    $('seek').max = ev.frames.length - 1; $('seek').value = pos;
    $('scene').value = scene; $('speed').value = String(speed); playLabel();
    $('clock').textContent = 'コマ ' + fr.index + ' ／ 映像内 ' + fr.time.toFixed(3) + '秒（参考時刻）';
    document.querySelectorAll('[data-boat]').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.boat === boat)));
    document.querySelectorAll('[data-gate]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.gate === gate && scene === 'gate')));
    document.querySelectorAll('[data-point]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.point === point)));
    $('proposal').setAttribute('aria-pressed', String(showProposal));
    const completed = Object.values(pairs).filter(p => p.before !== undefined && p.after !== undefined).length;
    $('progress').textContent = '前後コマの指定 ' + completed + ' / 18区間 ／ 艇首・艇尾の指定 ' + Object.values(labels).filter(hullMidpoint).length + 'コマ';
    const pair = pairs[boat + ':' + gate] || {};
    const times = previewIntervals(bundle, boat, pairs, labels);
    $('timing').textContent = boat + '号艇の参考タイム　入り ' + (times.entry === null ? '—' : times.entry.toFixed(1) + '秒') +
      ' ／ 出口 ' + (times.exit === null ? '—' : times.exit.toFixed(1) + '秒');
    $('status').textContent = playing ? 'ゆっくり再生中。位置を指定するときは一時停止してください。' :
      '指定する線 ' + gate + '：前 ' + (pair.before ?? '未指定') + ' ／ 後 ' + (pair.after ?? '未指定') + '　次は' + (point === 'bow' ? '艇首' : '艇尾') + 'をクリック';
    draw();
  }
  function draw() {
    const fr = frame(), token = ++imageToken, img = getImage(fr.index); readyFrame = null;
    function paint() {
      if (token !== imageToken) return;
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, 1280, 720);
      const box = fr.proposal, centre = box ? [box[0] + box[2] / 2, box[1] + box[3] / 2] : [640, 360];
      offset = zoom === 1 ? [0, 0] : [640 - centre[0] * zoom, 360 - centre[1] * zoom];
      ctx.setTransform(zoom, 0, 0, zoom, ...offset); ctx.drawImage(img, 0, 0, 1280, 720); readyFrame = fr.index;
      for (const [name, g] of Object.entries(bundle.gates)) {
        ctx.strokeStyle = { A: '#f1c66a', B: '#69e3c8', C: '#76b5ff' }[name]; ctx.lineWidth = 3 / zoom; ctx.beginPath();
        if (g.axis === 'x') { ctx.moveTo(g.value, g.segment[0]); ctx.lineTo(g.value, g.segment[1]); }
        else { ctx.moveTo(g.segment[0], g.value); ctx.lineTo(g.segment[1], g.value); }
        ctx.stroke();
      }
      if (showProposal && fr.proposal) {
        ctx.strokeStyle = '#ff887b'; ctx.strokeRect(...fr.proposal);
        const [x, y, w, h] = fr.proposal; dot([x + w / 2, y + h / 2], '#ff887b', 7);
      }
      const label = labels[labelKey()];
      if (label) {
        if (label.bow) dot(label.bow, '#6ee7d1', 6);
        if (label.stern) dot(label.stern, '#6ee7d1', 6);
        const mid = hullMidpoint(label);
        if (mid) { ctx.strokeStyle = '#6ee7d1'; ctx.beginPath(); ctx.moveTo(...label.bow); ctx.lineTo(...label.stern); ctx.stroke(); dot(mid, '#fff', 5); }
      }
      queueNext();
    }
    img.onerror = () => { if (token === imageToken) stopPlayback('画像を読み込めませんでした。再生を停止しました。'); };
    if (img.complete && img.naturalWidth) paint();
    else if (img.complete) stopPlayback('画像を読み込めませんでした。再生を停止しました。');
    else img.onload = paint;
  }
  function dot(p, color, r) { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(p[0], p[1], r / zoom, 0, Math.PI * 2); ctx.fill(); }
  for (let i = 1; i <= 6; i++) {
    const b = document.createElement('button'); b.textContent = i + '号艇'; b.dataset.boat = i;
    b.onclick = () => { stopPlayback(); boat = i; pos = 0; update(); }; $('boats').append(b);
  }
  for (const g of ['A', 'B', 'C']) {
    const b = document.createElement('button'); b.textContent = { A: 'A 進入線', B: 'B マーク横', C: 'C 出口線' }[g]; b.dataset.gate = g;
    b.onclick = () => { stopPlayback(); gate = g; scene = 'gate'; pos = 0; update(); }; $('gates').append(b);
  }
  $('play').onclick = () => { if (playing) stopPlayback('一時停止しました。'); else startPlayback(); };
  $('restart').onclick = () => startPlayback(true);
  $('speed').onchange = e => { const active = playing; stopPlayback(); speed = [0.25, 0.5, 1].includes(+e.target.value) ? +e.target.value : 0.5; if (active) startPlayback(); else update(); };
  $('scene').onchange = e => { stopPlayback(); scene = e.target.value === 'gate' ? 'gate' : 'turn'; pos = 0; update(); };
  $('seek').oninput = e => { stopPlayback(); pos = +e.target.value; update(); };
  $('prev').onclick = () => { stopPlayback(); pos = Math.max(0, pos - 1); update(); };
  $('next').onclick = () => { stopPlayback(); pos = Math.min(current().frames.length - 1, pos + 1); update(); };
  canvas.onclick = e => {
    if (playing) { stopPlayback('一時停止しました。艇首・艇尾を指定できます。'); return; }
    if (readyFrame !== frame().index) { $('status').textContent = '画像の読込完了を待ってください'; return; }
    const xy = sourcePoint(canvasPoint(e.clientX, e.clientY, canvas.getBoundingClientRect(), 1280, 720), zoom, offset);
    if (xy[0] < 0 || xy[1] < 0 || xy[0] >= 1280 || xy[1] >= 720) return;
    const key = labelKey(); labels[key] = { ...(labels[key] || {}), [point]: xy }; point = point === 'bow' ? 'stern' : 'bow'; update();
  };
  document.querySelectorAll('[data-point]').forEach(b => b.onclick = () => { stopPlayback(); point = b.dataset.point; update(); });
  document.querySelectorAll('[data-side]').forEach(b => b.onclick = () => { stopPlayback(); const key = boat + ':' + gate; pairs[key] = { ...(pairs[key] || {}), [b.dataset.side]: frame().index }; update(); });
  $('clear').onclick = () => { stopPlayback(); delete labels[labelKey()]; update(); };
  $('proposal').onclick = () => { stopPlayback(); showProposal = !showProposal; update(); };
  $('zoom').onclick = () => { stopPlayback(); zoom = zoom === 1 ? 4 : 1; $('zoom').textContent = zoom === 1 ? '４倍に拡大' : '全体に戻す'; update(); };
  $('export').onclick = () => {
    stopPlayback(); const reviewer = $('reviewer').value.trim();
    if (!reviewer) { $('status').textContent = '確認担当者を入力してください'; return; }
    const draft = { kind: 'turn-review-draft-v1', bundle_digest: bundle.digest, reviewer, reviewed_at: new Date().toISOString(), trajectory_checked: $('trajectory').checked, labels, pairs, publication_ready: false, source_clock: bundle.source_clock };
    const blob = new Blob([JSON.stringify(draft, null, 2)], { type: 'application/json' }), url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = 'heiwajima-review-' + Date.now() + '.json'; a.click(); URL.revokeObjectURL(url);
  };
  $('file').onchange = async e => {
    stopPlayback();
    try {
      const draft = acceptDraft(JSON.parse(await e.target.files[0].text()), bundle);
      stopPlayback();
      labels = draft.labels; pairs = draft.pairs || {}; $('reviewer').value = draft.reviewer || ''; $('trajectory').checked = !!draft.trajectory_checked; update();
    } catch (error) { $('status').textContent = error.message; }
  };
  if (document.addEventListener) document.addEventListener('visibilitychange', () => { if (document.hidden) stopPlayback('画面を離れたため一時停止しました。'); });
  update();
}
