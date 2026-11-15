/* Public read-only lists. F0 never implies that leave has been served. */
(() => {
  'use strict';
  const node=document.getElementById('pi-data');if(!node)return;
  const sortSel=document.getElementById('pi-sort');
  const data=JSON.parse(node.textContent),q=document.getElementById('pi-q'),filter=document.getElementById('pi-filter');
  const list=document.getElementById('pi-list'),count=document.getElementById('pi-count'),more=document.getElementById('pi-more');
  let limit=30;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const normalize=s=>String(s||'').normalize('NFKC').replace(/[\s\u3000]/g,'').toLowerCase();
  const date=s=>s?`${s.slice(0,4)}/${s.slice(4,6)}/${s.slice(6,8)}`:'未確認';
  const yen=n=>Number(n).toLocaleString('ja-JP')+'円';
  const gap=n=>n==null?'未確認':n===0?'基準額':(n>0?'+':'−')+yen(Math.abs(n));
  const name=r=>`<a class="pi-name" href="racer/${esc(r.toban)}">${esc(r.name)}<small>${esc(r.toban)}${r.branch?' ／ '+esc(r.branch):''}</small></a>`;
  const safeSource=u=>{try{const x=new URL(u);return x.protocol==='https:'&&['www.boatrace.jp','boatrace.jp','www.boatrace-tsu.com','www.boatrace-hamanako.jp','pic.omurakyotei.jp'].includes(x.hostname);}catch(_){return false;}};
  const leaveRaw=r=>r.leave_state||((r.rests||[]).some(s=>['scheduled','in_period','snapshot_unserved'].includes(s.status))?'unserved':'unknown');
  // 未＝公式の未消化 または 結果から確実。済＝公式の消化済み または 結果からの推定
  const leaveState=r=>({unserved_sure:'unserved',served_estimated:'served'}[leaveRaw(r)]||leaveRaw(r));
  const WHY={unserved:'公式資料に未消化の記載あり',served:'公式資料に消化済みの明示あり',unknown:'確認できない',
    unserved_sure:'Fのあと、必要な日数ぶん続けて休んだ時期がない（確実）',served_estimated:'Fのあと、必要な日数ぶん続けて休んだ時期がある（推定）'};
  function mark(r){const raw=leaveRaw(r),st=leaveState(r),why=WHY[raw]||'';const t={unserved:'未',served:'済',unknown:'—'}[st];
    const rest=r.rest||{};
    const sub=raw==='served_estimated'?'<small class="pi-mark-est">推</small>':'';
    const back=raw==='served_estimated'&&rest.back?`<small class="pi-mark-date">${date(rest.back).slice(5)}復帰</small>`:'';
    const inner=`<b class="pi-mark pi-mark-${st}" title="${esc(why)}">${t}${sub}</b>${back}`;
    const src=(r.rests||[]).find(x=>safeSource(x.source));
    return src&&(raw==='unserved'||raw==='served')?`<a href="${esc(src.source)}" target="_blank" rel="noopener" aria-label="${esc(why)}（公式資料）">${inner}</a>`:inner;}
  function fTable(rows){
    if(!rows.length)return'';
    return `<table class="pi-ftable"><thead><tr><th scope="col">選手</th><th scope="col" class="r">F</th><th scope="col" class="r">休み</th></tr></thead><tbody>${
      rows.map(r=>`<tr><td>${name(r)}</td><td class="r num"><b>${r.f==null?'—':'F'+esc(r.f)}</b></td><td class="r">${mark(r)}</td></tr>`).join('')}</tbody></table>`;}
  const kana=r=>normalize(r.kana||r.name);
  function sorted(rows){const m=sortSel?sortSel.value:'f';const by={
      f:(a,b)=>(b.f??-1)-(a.f??-1)||kana(a).localeCompare(kana(b),'ja'),
      kana:(a,b)=>kana(a).localeCompare(kana(b),'ja'),
      toban:(a,b)=>String(a.toban).localeCompare(String(b.toban))}[m]||(()=>0);
    return rows.slice().sort(by);}
  function prizeCard(r){
    const cutoff=data.cutoff||18,difference=r.gapBorder??r.gap18,inside=r.rank<=cutoff;
    const position=r.rank===cutoff?`現在の${cutoff}位ライン`:inside?'現在ライン内':'現在ライン外';
    const distance=difference==null?'差額未確認':difference<0?`あと${yen(-difference)}でラインと同額`:difference>0?`${cutoff}位より${yen(difference)}上`:'基準額';
    return `<article class="pi-card${r.rank===cutoff?' pi-border':''}${r.rank<=3?' pi-winner-'+r.rank:''}"><div class="pi-line"><span class="pi-rank">${r.rank<=3?`<span class="pi-rank-metal pi-metal-${r.rank}" aria-label="${r.rank}位"><span>${r.rank}</span></span>`:r.rank+'位'}</span>${name(r)}<strong class="num">${yen(r.amount)}</strong></div><div class="pi-standing ${inside?'pi-standing-in':'pi-standing-out'}"><span>${position}</span><b>${distance}</b></div><details class="pi-source"><summary>差額の詳細</summary><div class="pi-gaps"><span>${cutoff}位差 <b>${gap(difference)}</b></span>${data.women?'':`<span>6位差 <b>${gap(r.gap6)}</b></span>`}</div></details></article>`;
  }
  function render(){const search=normalize(q.value),mode=filter.value;
    const cutoff=data.cutoff||18;
    const rows=(data.rows||[]).filter(r=>data.kind==='prizes'||!(r.rollover||r.f===0)).filter(r=>!search||normalize([r.name,r.kana,r.toban,r.branch].join(' ')).includes(search)).filter(r=>data.kind==='prizes'?mode==='top18'?r.rank<=cutoff:mode==='top6'?r.rank<=6:mode==='border'?r.rank>=cutoff-5&&r.rank<=cutoff+6:true:mode==='f'?r.f>0:mode==='f2'?r.f>=2:mode==='leave'?leaveState(r)==='unserved':mode==='served'?leaveState(r)==='served':true);
    if(data.kind==='prizes')list.innerHTML=rows.slice(0,limit).map(prizeCard).join('')||'<p class="sub">該当する選手はいません。</p>';
    else list.innerHTML=fTable(sorted(rows).slice(0,limit))||'<p class="sub">確認できた資料の中に該当する選手はいません。</p>';
    count.textContent=`${rows.length}人 ／ ${Math.min(limit,rows.length)}人を表示`;more.hidden=rows.length<=limit;
  }
  if(sortSel)sortSel.addEventListener('change',()=>{limit=30;render();});
  q.addEventListener('input',()=>{limit=30;render();});filter.addEventListener('change',()=>{limit=30;render();});more.addEventListener('click',()=>{limit+=30;render();});render();
})();
