/* Display-only provisional class-period scores. */
(() => {
  const source=document.getElementById('sw-data');if(!source)return;
  const data=JSON.parse(source.textContent),by=id=>document.getElementById(id);
  const clean=x=>String(x??'').normalize('NFKC').toLowerCase().replace(/\s/g,'');
  const hit=(p,q)=>!q||clean([p.name,p.kana,p.toban,p.branch].join(' ')).includes(clean(q));
  function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function who(p){const a=el('a',p.name.replace(/\s/g,''),'sw-name');a.href=`../racer/${p.toban}.html`;return a;}
  let limit=20;
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
    }).sort((a,b)=>{
      const order=by('sw-sort').value;
      return (order==='asc'?a.win-b.win:order==='near'?Math.abs(a.diff)-Math.abs(b.diff)||b.win-a.win:b.win-a.win)||a.toban.localeCompare(b.toban);
    });
    const list=by('sw-list');list.replaceChildren();
    for(const p of rows.slice(0,limit)){
      const card=el('article',undefined,'sw-card'),head=el('div',undefined,'sw-card-head');
      head.append(who(p),el('span',`${p.class||'級未確認'} · ${p.branch||'支部未確認'}`,'sub'));
      const stat=el('div',undefined,'sw-score');stat.setAttribute('aria-label','参考勝率と目標との差');stat.append(el('strong',p.win.toFixed(2)),el('span',`目標差 ${Math.abs(p.diff)<.005?'±0.00':(p.diff>0?'+':'')+p.diff.toFixed(2)}`,p.diff>=-.005?'dgood':'sub'));
      const nums=el('div',undefined,'sw-metrics');
      nums.append(el('span',`出走 ${p.n}回`),el('span',`2連対 ${(p.top2/p.n*100).toFixed(1)}%`),el('span',`3連対 ${(p.top3/p.n*100).toFixed(1)}%`));
      const issues=[];if(p.n<minimum)issues.push(`${tier}の出走条件まであと${minimum-p.n}回`);
      if(p.top2/p.n<.30||p.top3/p.n<.40)issues.push('連対率条件に未達');
      if(p.accident_min/p.n>.70)issues.push('確認済み事故点だけで事故率0.70超');
      if(p.unknown)issues.push(`計算条件未確認 ${p.unknown}走`);
      card.append(head,stat,nums);
      if(issues.length)card.append(el('p',issues.join(' ／ '),'sw-card-note'));
      list.append(card);
    }
    by('sw-count').textContent=`${rows.length.toLocaleString()}人 ／ ${Math.min(limit,rows.length)}人を表示・参考値です`;
    by('sw-more').hidden=limit>=rows.length;
  }
  for(const id of ['sw-target','sw-scope','sw-q','sw-sort'])by(id).addEventListener('input',()=>{limit=20;scoreList();});
  by('sw-tier').addEventListener('change',()=>{const b=data.borders[by('sw-tier').value];by('sw-target').value=(b.win??b.previous_official??5.5).toFixed(2);limit=20;scoreList();});
  by('sw-more').addEventListener('click',()=>{limit+=20;scoreList();});
  scoreList();
})();
