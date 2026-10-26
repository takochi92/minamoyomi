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
if (typeof module !== 'undefined') module.exports = { exhibitionSelection, exhibitionAsset };
if (typeof document !== 'undefined') {
  const $ = id => document.getElementById(id), config = JSON.parse($('ev-config').textContent);
  const venues = $('ev-venue'), dates = $('ev-date'), races = $('ev-race');
  let lastAsset = null;
  function show(selection, updateUrl) {
    $('ev-view').hidden = true; $('ev-frame').removeAttribute('src'); lastAsset = null;
    if ($('ev-review')) $('ev-review').hidden = true;
    if (!selection) { $('ev-status').textContent = '日付・場・レース番号を確認してください。'; $('ev-back').hidden = true; return; }
    const { date, jcd, rno } = selection;
    dates.value = date.slice(0, 4) + '-' + date.slice(4, 6) + '-' + date.slice(6, 8); venues.value = jcd; races.value = String(rno);
    $('ev-title').textContent = venues.options[venues.selectedIndex].textContent + ' ' + rno + 'R';
    $('ev-back').href = config.raceBase + 'race/' + date + '/' + config.slugs[jcd] + '-' + rno + '.html#tenji'; $('ev-back').hidden = false;
    const row = config.records.find(r => r.date === date && r.jcd === jcd && r.rno === rno && exhibitionAsset(r.asset));
    if (!row) $('ev-status').textContent = 'このレースは未収録です。現在は平和島で検証しています。';
    else {
      lastAsset = row.asset; const url = row.asset + '?mode=watch';
      $('ev-frame').src = url; $('ev-open').href = url; $('ev-view').hidden = false;
      if ($('ev-review')) { $('ev-review').href = row.asset; $('ev-review').hidden = false; }
      $('ev-status').textContent = config.preview ? '確認用の映像です。計測結果は照合中のため、正式タイムは未掲載です。' : '収録した映像を表示しています。';
    }
    if (updateUrl) { try { const params = new URLSearchParams(selection); history.replaceState(null, '', '?' + params.toString()); } catch (_) {} }
  }
  $('ev-select').onsubmit = event => { event.preventDefault(); show(exhibitionSelection(dates.value, venues.value, races.value), true); };
  for (const control of [venues, dates, races]) control.onchange = () => {
    $('ev-view').hidden = true; $('ev-frame').removeAttribute('src'); lastAsset = null;
    $('ev-back').hidden = true;
    if ($('ev-review')) $('ev-review').hidden = true;
    $('ev-status').textContent = '「映像を見る」を押すと、選択したレースを表示します。';
  };
  const query = new URLSearchParams(location.search);
  show(exhibitionSelection(query.get('date') || config.date, query.get('jcd') || '04', query.get('rno') || '1'), false);
  window.addEventListener('message', event => {
    if (!lastAsset || event.source !== $('ev-frame').contentWindow || event.data?.kind !== 'teilog-exhibition-height') return;
    const height = event.data.height;
    if (Number.isFinite(height) && height >= 300 && height <= 1600) $('ev-frame').style.height = Math.ceil(height) + 'px';
  });
}
