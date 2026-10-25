/* Display-only period watch: provisional scores and dated F records. */
(() => {
  const source=document.getElementById('sw-data');if(!source)return;
  const data=JSON.parse(source.textContent),by=id=>document.getElementById(id);
  const clean=x=>String(x??'').normalize('NFKC').toLowerCase().replace(/\s/g,'');
  const fmt=s=>s?`${s.slice(0,4)}/${s.slice(4,6)}/${s.slice(6)}`:'未取得';
  const hit=(p,q)=>!q||clean([p.name,p.kana,p.toban,p.branch].join(' ')).includes(clean(q));
  function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function who(p){const a=el('a',p.name.replace(/\s/g,''),'sw-name');a.href=`../racer/${p.toban}.html`;return a;}
  let limit=20,fLimit=20;
  function scoreList(){
    const tier=by('sw-tier').value,target=Number(by('sw-target').value),minimum=tier==='A1'?90:80;
    if(!Number.isFinite(target)||target<0||target>12){by('sw-count').textContent='目標勝率は0〜12で指定してください。';by('sw-list').replaceChildren();by('sw-more').hidden=true;return;}
    const scope=by('sw-scope').value;
    const rows=data.players.map(p=>({...p,diff:Math.round(p.win*100)/100-target})).filter(p=>{
      if(!hit(p,by('sw-q').value))return false;
      if(scope==='near')return Math.abs(p.diff)<=.30001;
      if(scope==='short')return p.n<minimum;
      if(scope==='keep')return p.class===tier&&Math.abs(p.diff)<=.30001;
      if(scope==='below')return p.class===tier&&p.diff<-.005;
      if(scope==='up')return (tier==='A1'?p.class!=='A1':!['A1','A2'].includes(p.class))&&p.diff>=-.30&&p.diff<=.30;
      return true;
    }).sort((a,b)=>scope==='all'?b.win-a.win:Math.abs(a.diff)-Math.abs(b.diff)||b.win-a.win);
    const list=by('sw-list');list.replaceChildren();
    for(const p of rows.slice(0,limit)){
      const card=el('article',undefined,'sw-card'),head=el('div',undefined,'sw-card-head');
      head.append(who(p),el('span',`現在 ${p.class||'未確認'} ／ ${p.branch||'支部未確認'}`,'sub'));
      const diff=Math.abs(p.diff)<.005?'目標と同値':`目標より${p.diff>0?'+':''}${p.diff.toFixed(2)}`;
      const stat=el('div',undefined,'sw-score');stat.append(el('strong',p.win.toFixed(2)),el('span',`参考勝率 ／ ${diff}`,p.diff>=-.005?'dgood':'sub'));
      const nums=el('div',undefined,'sw-metrics');
      nums.append(el('span',`出走 ${p.n}回`),el('span',`2連対 ${(p.top2/p.n*100).toFixed(1)}%`),el('span',`3連対 ${(p.top3/p.n*100).toFixed(1)}%`));
      const issues=[];if(p.n<minimum)issues.push(`${tier}の出走条件まであと${minimum-p.n}回`);
      if(p.top2/p.n<.30||p.top3/p.n<.40)issues.push('連対率条件に未達');
      if(p.accident_min/p.n>.70)issues.push('確認済み事故点だけで事故率0.70超');
      if(p.unknown)issues.push(`計算条件未確認 ${p.unknown}走`);
      const note=el('p',issues.join(' ／ ')||'参考値・級別は未確定','sw-card-note');
      card.append(head,stat,nums,note);list.append(card);
    }
    by('sw-count').textContent=`${rows.length.toLocaleString()}人 ／ ${Math.min(limit,rows.length)}人を表示・参考値です`;
    by('sw-more').hidden=limit>=rows.length;
  }
  function fList(){
    const scope=by('sw-f-scope').value;
    const end=new Date(`${data.f_period.through.slice(0,4)}-${data.f_period.through.slice(4,6)}-${data.f_period.through.slice(6)}T00:00:00Z`);end.setUTCDate(end.getUTCDate()-59);
    const since=end.toISOString().slice(0,10).replaceAll('-','');
    const rows=data.f_players.filter(p=>hit(p,by('sw-f-q').value)&&(scope==='all'||(scope==='f0'?p.f0:p.last_f>=since)));
    const list=by('sw-f-list');list.replaceChildren();
    for(const p of rows.slice(0,fLimit)){
      const card=el('article',undefined,'sw-card'),head=el('div',undefined,'sw-card-head');head.append(who(p),el('span',`${p.class||'級未確認'} ／ ${p.branch||'支部未確認'}`,'sub'));
      const title=el('strong',`対象期間の本番F ${p.events.length}回`,'sw-f-title');
      const observed=p.programme?`出走表F${p.programme.f}（${fmt(p.programme.date)} ${p.programme.rno}R時点）`:`${fmt(data.new_start)}以降の出走表待ち`;
      card.append(head,title,el('p',observed),el('p','休みの消化状況は未確認','sw-card-note'));
      if(p.current_f_known)card.append(el('p','今期のF発生記録もあります。最新の出走表を確認してください。','sw-card-note'));
      const details=el('details'),summary=el('summary',`F発生日を見る ／ 最新 ${fmt(p.last_f)}`);details.append(summary);
      for(const f of p.events){const a=el('a',`${fmt(f.date)} ${f.rno}R${f.final?'（優勝戦）':''}`,'sw-proof');a.href=`https://www.boatrace.jp/owpc/pc/race/raceresult?hd=${f.date}&jcd=${f.jcd}&rno=${f.rno}`;a.target='_blank';a.rel='noopener';details.append(a);}
      if(p.programme){const r=p.programme,a=el('a','F表記を公式出走表で確認 →','sw-proof');a.href=`https://www.boatrace.jp/owpc/pc/race/racelist?hd=${r.date}&jcd=${r.jcd}&rno=${r.rno}`;a.target='_blank';a.rel='noopener';details.append(a);}
      card.append(details);list.append(card);
    }
    by('sw-f-count').textContent=`${rows.length}人 ／ ${Math.min(fLimit,rows.length)}人を表示。F歴だけで未消化とは判定しません。`;
    by('sw-f-more').hidden=fLimit>=rows.length;
    if(!rows.length)list.append(el('p',data.f_preparing&&scope==='f0'?`${fmt(data.new_start)}以降の出走表取得後に照合を始めます。今は新期F0を確認できる時期ではありません。`:'該当する確認記録はありません。F休み未消化の選手がいないことを示すものではありません。','sub'));
  }
  for(const id of ['sw-target','sw-scope','sw-q'])by(id).addEventListener('input',()=>{limit=20;scoreList();});
  by('sw-tier').addEventListener('change',()=>{const b=data.borders[by('sw-tier').value];by('sw-target').value=(b.win??b.previous_official??5.5).toFixed(2);limit=20;scoreList();});
  by('sw-more').addEventListener('click',()=>{limit+=20;scoreList();});
  for(const id of ['sw-f-scope','sw-f-q'])by(id).addEventListener('input',()=>{fLimit=20;fList();});
  by('sw-f-more').addEventListener('click',()=>{fLimit+=20;fList();});
  scoreList();fList();
})();
