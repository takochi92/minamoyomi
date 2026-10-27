/* Public read-only lists. F0 never implies that leave has been served. */
(() => {
  'use strict';
  const node=document.getElementById('pi-data');if(!node)return;
  const data=JSON.parse(node.textContent),q=document.getElementById('pi-q'),filter=document.getElementById('pi-filter');
  const list=document.getElementById('pi-list'),count=document.getElementById('pi-count'),more=document.getElementById('pi-more');
  let limit=30;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const normalize=s=>String(s||'').normalize('NFKC').replace(/[\s\u3000]/g,'').toLowerCase();
  const date=s=>s?`${s.slice(0,4)}/${s.slice(4,6)}/${s.slice(6,8)}`:'未確認';
  const yen=n=>Number(n).toLocaleString('ja-JP')+'円';
  const gap=n=>n==null?'未確認':n===0?'基準額':(n>0?'+':'−')+yen(Math.abs(n));
  const name=r=>`<a class="pi-name" href="racer/${esc(r.toban)}.html">${esc(r.name)}<small>${esc(r.toban)}${r.branch?' ／ '+esc(r.branch):''}</small></a>`;
  const safeSource=u=>{try{const x=new URL(u);return x.protocol==='https:'&&['www.boatrace.jp','boatrace.jp','www.boatrace-tsu.com','www.boatrace-hamanako.jp','pic.omurakyotei.jp'].includes(x.hostname);}catch(_){return false;}};
  const leaveState=r=>r.leave_state||((r.rests||[]).some(s=>['scheduled','in_period','snapshot_unserved'].includes(s.status))?'unserved':'unknown');
  function fCard(r){
    let details='';const p=r.programme;
    if(p){const url=`https://www.boatrace.jp/owpc/pc/race/racelist?hd=${encodeURIComponent(p.date)}&jcd=${encodeURIComponent(p.jcd)}&rno=${encodeURIComponent(p.rno)}`;
      details+=`<p class="sub">出走表 ${date(p.date)}時点 ／ <a href="${esc(url)}" target="_blank" rel="noopener">公式出走表 ↗</a></p>`;}
    if(r.history_count)details+=`<p class="sub">保存F歴 ${r.history_count}件 ／ 最新 ${date(r.last_f)}（休みの未消化本数ではありません）</p>`;
    for(const rest of r.rests||[]){const status={scheduled:'休み予定の記載',in_period:'記載された休み期間内',ended_unverified:'記載期間終了・消化状況は未確認',snapshot_unserved:'未消化の記載あり（資料時点）',served_confirmed:'公式資料に消化済みの明示あり',stale_unverified:'古い資料・要再確認'}[rest.status]||'要確認';
      details+=`<div class="pi-rest"><b>${esc(status)}</b><p>${rest.days!=null?esc(rest.days)+'日 ／ ':''}${rest.start&&rest.end?date(rest.start)+'〜'+date(rest.end):'開始・終了日は未確認'}</p><small>資料 ${date(rest.document_date)} ／ ${esc(rest.venue)} ／ 確認 ${esc((rest.checked_at||'').slice(0,10))}</small>${safeSource(rest.source)?`<a href="${esc(rest.source)}" target="_blank" rel="noopener">公式資料 ↗</a>`:''}</div>`;}
    if(r.rollover)details+='<p class="sub">期初のF0表示と前期F歴あり。未消化かどうかは別確認です。</p>';
    const state=leaveState(r),label={unserved:'未消化',served:'消化済み',unknown:'消化未確認'}[state];
    const pending=(r.rests||[]).filter(s=>['scheduled','in_period','snapshot_unserved'].includes(s.status));
    const schedule=pending.filter(s=>s.start&&s.end).map(s=>`休み ${date(s.start)}〜${date(s.end)}`).join(' ／ ');
    const band=pending.length===1?pending.find(s=>s.days!=null||s.days_min!=null):null;
    const days=band?(band.days!=null?`${band.days}日`:`${band.days_min}〜${band.days_max}日`):'';
    return `<article class="pi-card"><div class="pi-line">${name(r)}<b class="pi-f-state pi-f-${state}">${r.f==null?'F本数未確認':'F'+r.f}・${label}${state==='unserved'?days:''}</b></div>${state==='unserved'?`<p class="pi-rest-plan">${schedule||'休み日程未確認'}</p>`:''}<details class="pi-source"><summary>確認日・出典</summary>${details}</details></article>`;
  }
  function prizeCard(r){const cutoff=data.cutoff||18;return `<article class="pi-card${r.rank===cutoff?' pi-border':''}${r.rank<=3?' pi-winner-'+r.rank:''}"><div class="pi-line"><span class="pi-rank">${r.rank<=3?['🥇','🥈','🥉'][r.rank-1]:r.rank+'位'}</span>${name(r)}<strong class="num">${yen(r.amount)}</strong></div><div class="pi-gaps"><span>${cutoff}位差 <b>${gap(r.gapBorder??r.gap18)}</b></span>${data.women?'':`<span>6位差 <b>${gap(r.gap6)}</b></span>`}</div></article>`;}
  function render(){const search=normalize(q.value),mode=filter.value;
    const cutoff=data.cutoff||18;
    const rows=(data.rows||[]).filter(r=>!search||normalize([r.name,r.kana,r.toban,r.branch].join(' ')).includes(search)).filter(r=>data.kind==='prizes'?mode==='top18'?r.rank<=cutoff:mode==='top6'?r.rank<=6:mode==='border'?r.rank>=cutoff-5&&r.rank<=cutoff+6:true:mode==='f'?r.f>0:mode==='f2'?r.f>=2:mode==='leave'?leaveState(r)==='unserved':mode==='served'?leaveState(r)==='served':mode==='rollover'?r.rollover:true);
    list.innerHTML=rows.slice(0,limit).map(data.kind==='prizes'?prizeCard:fCard).join('')||`<p class="sub">${data.kind==='prizes'?'該当する選手はいません。':'確認できた資料の中に該当する選手はいません。'}</p>`;
    count.textContent=`${rows.length}人 ／ ${Math.min(limit,rows.length)}人を表示`;more.hidden=rows.length<=limit;
  }
  q.addEventListener('input',()=>{limit=30;render();});filter.addEventListener('change',()=>{limit=30;render();});more.addEventListener('click',()=>{limit+=30;render();});render();
})();
