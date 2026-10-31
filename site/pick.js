/* Shared boat-colour odds grid. Node export also verifies all 120 mappings. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.TeiOddsGrid=factory();
})(typeof window==='undefined'?this:window,function(){
  const frames=[1,2,3,4,5,6],combos=[];
  for(const a of frames)for(const b of frames)for(const c of frames)if(a!==b&&b!==c&&a!==c)combos.push(`${a}-${b}-${c}`);
  const valid=v=>typeof v==='number'&&Number.isFinite(v)&&v>0;
  const fmt=v=>valid(v)?v.toFixed(1):'—';
  const badge=n=>`<span class="bt bt${n}">${n}</span>`;
  function filters(first){
    return `<div class="odds-first-label">1着を選ぶ</div><div class="odds-first" role="group" aria-label="1着の艇を選ぶ">${frames.map(n=>`<button type="button" data-odds-first="${n}" aria-label="${n}号艇を1着にする" aria-pressed="${first===n}">${badge(n)}</button>`).join('')}<button type="button" data-odds-first="0" aria-pressed="${first===0}">全艇</button></div>`;
  }
  function render(odds,{first=0,selected=new Set(),selectable=false,trend=null}={}){
    return frames.filter(a=>!first||a===first).map(a=>`<section class="og" data-first="${a}" style="--og-lane:var(--b${a});--og-lane-ink:var(--b${a}i)"><h3 class="og-h">${badge(a)}<span>1着</span><small>2着 → 3着 ／ オッズ</small></h3>${frames.filter(b=>b!==a).map(b=>`<div class="og-group"><div class="og-second bt${b}"><b>${b}</b><small>2着</small></div><div class="og-options">${combos.map((c,i)=>({c,i})).filter(x=>x.c.startsWith(a+'-'+b+'-')).map(({c,i})=>{
      const n=Number(c.slice(-1)),on=selected.has(c),available=valid(odds?.[i]);
      const label=c+'、'+(available?fmt(odds[i])+'倍':'オッズ未取得');
      const body=`<span class="og-third">${badge(n)}</span><b class="num og-price">${fmt(odds?.[i])}${available?'<small>倍</small>':''}</b>${trend?`<span class="og-trend">${trend(i)}</span>`:`<span class="og-state" aria-hidden="true">${on?'✓':selectable&&available?'+':''}</span>`}`;
      return selectable?`<button type="button" class="og-r pk${on?' on':''}" data-c="${c}" aria-label="${label}" aria-pressed="${on}"${available||on?'':' disabled'}>${body}</button>`:`<div class="og-r${on?' mine':''}" aria-label="${label}">${body}</div>`;
    }).join('')}</div></div>`).join('')}</section>`).join('');
  }
  return {combos:Object.freeze(combos),valid,fmt,filters,render};
});

/* 買い目を選ぶだけで合成オッズと配分が出る（レースページ）
 * オッズはページに載っている締切前のオッズ。ライブオッズが動いていれば、そちらで自動更新する。
 * 初期選択は空。採用予想はボタンを押したときだけ入れる。
 */
(() => {
  if(typeof window==='undefined')return;
  const R = window.__RACE__, box = document.getElementById("pick");
  if (!R || !box) return;
  const G=window.TeiOddsGrid,COMBOS=G.combos;
  let odds = R.odds, at = R.odds_at, budget = 1000, first = window.matchMedia('(max-width:720px)').matches?1:0, selectionOpen=false;
  const sel = new Set();   // 買い目は入れず、使う人が選ぶ
  const bt = (n) => `<span class="bt bt${n}">${n}</span>`;
  const f1 = G.fmt;
  const yen = (v) => "¥" + Math.round(v).toLocaleString("ja-JP");

  function alloc(list) {           // 100円単位で、どれが当たっても払戻がそろう配分
    const inv = list.map((o) => 1 / o), s = inv.reduce((a, b) => a + b, 0);
    const units = inv.map((x) => Math.max(1, Math.round((budget * x) / s / 100)));
    return units.map((u) => u * 100);
  }

  function render(focus) {
    if (!odds) { box.hidden = true; return; }
    const previous=box.querySelector('.pk-selection');if(previous)selectionOpen=previous.open;
    box.hidden = false;
    const chosen = COMBOS.map((c, i) => ({ c, o: odds[i], p: R.p3 ? R.p3[i] : null })).filter((x) => sel.has(x.c) && G.valid(x.o));
    const pending=chosen.length!==sel.size;
    const s = pending?0:chosen.reduce((a, x) => a + 1 / x.o, 0), comp = s ? 1 / s : null;
    const al = chosen.length&&!pending ? alloc(chosen.map((x) => x.o)) : [];
    const tot = al.reduce((a, b) => a + b, 0), minRet = al.length ? Math.min(...chosen.map((x, i) => al[i] * x.o)) : 0;
    const mk = chosen.reduce((a, x) => a + 0.75 / x.o, 0);
    const grid=G.render(odds,{first,selected:sel,selectable:true});
    const rows = chosen.map((x, i) => `<tr><td><span class="combo">${x.c.split("-").map(bt).join('<span class="sep">-</span>')}</span></td><td class="r num" data-label="オッズ">${f1(x.o)}倍</td><td class="r num" data-label="配分">${pending?'—':yen(al[i])}</td><td class="r num" data-label="当たれば">${pending?'—':yen(al[i] * x.o)}</td></tr>`).join("");
    box.innerHTML = `<h2>3連単オッズ <small>${at ? at + "時点" : ""}・タップで買い目を選択</small></h2>
      <details class="pk-selection"${selectionOpen?' open':''}><summary>選択中 ${sel.size}点 · ${pending?'未取得あり':comp?'合成 '+comp.toFixed(2)+'倍':'配分を見る'}</summary>
      <div class="tiles"><div class="tile ${comp && comp < 5 ? "warn" : ""}"><small>合成オッズ</small><b>${comp ? comp.toFixed(2) + "倍" : "-"}</b></div>
      <div class="tile"><small>点数</small><b>${sel.size}点</b></div><div class="tile"><small>的中の目安（オッズから）</small><b>${chosen.length&&!pending ? Math.round(mk * 100) + "%" : "-"}</b></div>
      <div class="tile"><label class="pk-budget-label" for="pk-budget">予算（円）</label><input id="pk-budget" type="number" step="100" min="100" value="${budget}" inputmode="numeric"></div></div>
      ${rows ? `<p class="pk-allocation-total sub">配分合計 <b>${pending?'—':yen(tot)}</b></p><div class="tbl-wrap"><table class="pk-alloc"><thead><tr><th>3連単</th><th class="r">オッズ</th><th class="r">配分${pending?'':`（計${yen(tot)}）`}</th><th class="r">当たれば</th></tr></thead><tbody>${rows}</tbody></table></div>${pending?'':`<p class="sub">どれが当たっても ${yen(minRet)} 以上。</p>`}` : '<p class="sub">表から買いたい目を選んでください。</p>'}
      <div class="pk-actions"><button type="button" class="btn" id="pk-clear">選択をクリア</button>${R.bets.length?'<button type="button" class="btn" id="pk-reco">採用予想を選ぶ</button>':''}</div></details>
      ${pending?'<p class="sub" role="status">選択した買い目に未取得のオッズがあります。計算は取得後に再開します。</p>':''}
      ${G.filters(first)}<div class="ogrid${first?' one':''}">${grid}</div><p class="sub odds-key">艇番は白・黒・赤・青・黄・緑。✓は選択中、—はオッズ未取得。</p>`;
    box.querySelectorAll('[data-odds-first]').forEach(b=>b.addEventListener('click',()=>{first=Number(b.dataset.oddsFirst);render('[data-odds-first="'+first+'"]');}));
    box.querySelectorAll(".pk").forEach((b) => b.addEventListener("click", () => { const c = b.dataset.c; sel.has(c) ? sel.delete(c) : sel.add(c); render('[data-c="'+c+'"]'); }));
    const bi = box.querySelector("#pk-budget");
    if (bi) bi.addEventListener("change", () => { budget = Math.max(100, Math.round((+bi.value || 1000) / 100) * 100); render(); });
    const cl = box.querySelector("#pk-clear"); if (cl) cl.onclick = () => { sel.clear(); render(); };
    const rc = box.querySelector("#pk-reco"); if (rc) rc.onclick = () => { sel.clear(); R.bets.forEach((c) => {if(G.valid(odds[COMBOS.indexOf(c)]))sel.add(c);}); render('#pk-reco'); };
    if(focus)box.querySelector(focus)?.focus({preventScroll:true});
  }
  // ライブオッズが届いたら差し替え
  window.addEventListener("liveodds", (e) => { odds = e.detail.o3; at = e.detail.t; render(); });
  render();
})();
