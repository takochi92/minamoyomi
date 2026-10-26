function exhibitionSelection(date, jcd, rno) {
  const compact = String(date).replace(/-/g, '');
  if (!/^\d{8}$/.test(compact) || !/^(0[1-9]|1\d|2[0-4])$/.test(String(jcd)) || !/^(?:[1-9]|1[0-2])$/.test(String(rno))) return null;
  const y = +compact.slice(0, 4), m = +compact.slice(4, 6), d = +compact.slice(6, 8), stamp = new Date(Date.UTC(y, m - 1, d));
  if (stamp.getUTCFullYear() !== y || stamp.getUTCMonth() !== m - 1 || stamp.getUTCDate() !== d) return null;
  return { date: compact, jcd: String(jcd), rno: +rno };
}
function exhibitionAsset(asset) {
  return typeof asset === 'string' && /^data\/exhibition\/[A-Za-z0-9_/-]+\.html$/.test(asset) && !asset.includes('..') && !asset.includes('//');
}
function officialExhibitionUrl(value, selection) {
  try {
    const u = new URL(value), q = u.searchParams;
    return selection.jcd === '04' && u.origin === 'https://front.player.boatrace-cdn.jp' && u.pathname === '/player/vod' && !u.hash && !u.username && !u.password &&
      [...q.keys()].length === 7 && q.get('service') === 'boatcast' && q.get('stadium') === '04heiwajima' && q.get('raceType') === 'exhibition' &&
      q.get('raceDate') === selection.date && q.get('raceNumber') === String(selection.rno).padStart(2, '0') && q.get('autoplay') === '0' && q.get('bitrate') === 'low';
  } catch (_) { return false; }
}
function exhibitionReferenceTable(reference) {
  const boats = reference?.boats;
  if (!Array.isArray(boats) || boats.length !== 6 || new Set(boats.map(b=>b.boat)).size !== 6 ||
      boats.some(b=>!Number.isInteger(b.boat) || b.boat < 1 || b.boat > 6 || typeof b.name !== 'string' ||
        ['entry','exit'].some(k=>!Number.isFinite(b[k]) || b[k] <= 0 || b[k] > 30))) return '';
  const esc = s => s.replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  return '<table class="ev-times"><thead><tr><th>選手</th><th>入り<small>A→B</small></th><th>出口<small>B→C</small></th></tr></thead><tbody>' +
    [...boats].sort((a,b)=>a.boat-b.boat).map(b=>`<tr><th><span class="bt bt${b.boat}">${b.boat}</span><span>${esc(b.name)}</span></th><td>${b.entry.toFixed(1)}<small>秒</small></td><td>${b.exit.toFixed(1)}<small>秒</small></td></tr>`).join('') + '</tbody></table>';
}
if (typeof module !== 'undefined') module.exports = { exhibitionSelection, exhibitionAsset, officialExhibitionUrl, exhibitionReferenceTable };
if (typeof document !== 'undefined') {
  const $ = id => document.getElementById(id), config = JSON.parse($('ev-config').textContent);
  const venues = $('ev-venue'), dates = $('ev-date'), races = $('ev-race');
  let lastAsset = null;
  const buttons = document.querySelectorAll ? [...document.querySelectorAll('[data-ev-race]')] : [];
  function clearResearch() {
    $('ev-reference').hidden = true; $('ev-times').innerHTML = '';
    $('ev-source-wrap').hidden = true; $('ev-source').removeAttribute('href');
    $('ev-audit').textContent = 'このレースは未測定です。別レースの数値や推定値で補っていません。';
  }
  function show(selection, updateUrl) {
    clearResearch();
    $('ev-view').hidden = true; $('ev-frame').removeAttribute('src'); lastAsset = null;
    if ($('ev-review')) $('ev-review').hidden = true;
    if (!selection) { $('ev-status').textContent = '日付・場・レース番号を確認してください。'; $('ev-back').hidden = true; return; }
    const { date, jcd, rno } = selection;
    dates.value = date.slice(0, 4) + '-' + date.slice(4, 6) + '-' + date.slice(6, 8); venues.value = jcd; races.value = String(rno);
    $('ev-title').textContent = venues.options[venues.selectedIndex].textContent + ' ' + rno + 'R';
    $('ev-back').href = config.raceBase + 'race/' + date + '/' + config.slugs[jcd] + '-' + rno + '.html#tenji'; $('ev-back').hidden = false;
    for (const button of buttons) button.setAttribute('aria-pressed', String(+button.dataset.evRace === rno));
    const research = (config.research || []).find(r=>r.date === date && r.jcd === jcd && r.rno === rno && officialExhibitionUrl(r.official_url, selection));
    if (research) {
      if (research.source_state !== 'unavailable') {
        $('ev-source').href = research.official_url; $('ev-source-wrap').hidden = false;
      }
      const table = exhibitionReferenceTable(research.reference);
      if (table) {
        $('ev-times').innerHTML = table; $('ev-reference').hidden = false;
        const difference = research.reference.max_review_difference_seconds;
        $('ev-audit').textContent = '６艇・18通過点を２人の別AI担当が照合。' +
          (Number.isFinite(difference) ? '通過時刻の最大差は' + difference.toFixed(3) + '秒。' : '') + '同一レース内の一致であり、実走精度の保証ではありません。';
      }
    }
    const row = config.records.find(r => r.date === date && r.jcd === jcd && r.rno === rno && exhibitionAsset(r.asset));
    if (!row) $('ev-status').textContent = research?.source_state === 'unavailable' ? '公式映像の登録を現在確認できません。保存済みの参考値がある場合のみ表示します。' : research ?
      ($('ev-reference').hidden ? '参考タイムは未測定です。公式展示映像を別タブで確認できます。' : '艇首方式の測定サンプルです。正式タイムではありません。') :
      'このレースは未収録です。現在は平和島で検証しています。';
    else {
      lastAsset = row.asset; const url = row.asset + '?mode=watch';
      $('ev-frame').src = url; $('ev-open').href = url; $('ev-view').hidden = false;
      if ($('ev-review')) { $('ev-review').href = row.asset; $('ev-review').hidden = false; }
      $('ev-status').textContent = config.preview ? '確認用の映像です。計測結果は照合中のため、正式タイムは未掲載です。' : '収録した映像を表示しています。';
    }
    if (updateUrl) { try { const params = new URLSearchParams(selection); history.replaceState(null, '', '?' + params.toString()); } catch (_) {} }
  }
  $('ev-select').onsubmit = event => { event.preventDefault(); show(exhibitionSelection(dates.value, venues.value, races.value), true); };
  for (const button of buttons) button.onclick = () => show(exhibitionSelection(dates.value, venues.value, button.dataset.evRace), true);
  for (const control of [venues, dates, races]) control.onchange = () => {
    clearResearch();
    for (const button of buttons) button.setAttribute('aria-pressed','false');
    $('ev-view').hidden = true; $('ev-frame').removeAttribute('src'); lastAsset = null;
    $('ev-back').hidden = true;
    if ($('ev-review')) $('ev-review').hidden = true;
    $('ev-status').textContent = '「表示する」かレース番号を押してください。';
  };
  const query = new URLSearchParams(location.search);
  show(exhibitionSelection(query.get('date') || config.date, query.get('jcd') || '04', query.get('rno') || '1'), false);
  window.addEventListener('message', event => {
    if (!lastAsset || event.source !== $('ev-frame').contentWindow || event.data?.kind !== 'teilog-exhibition-height') return;
    const height = event.data.height;
    if (Number.isFinite(height) && height >= 300 && height <= 1600) $('ev-frame').style.height = Math.ceil(height) + 'px';
  });
}
