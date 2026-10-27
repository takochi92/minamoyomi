/* Display-only provisional class-period scores. */
function seasonRankPoints(kind, final=false) {
  const bonus={general:0,graded:1,sg:2}[kind];
  return [10,8,6,4,2,1].map((v,i)=>v+bonus+(final?(i<3?1:2):0));
}
function seasonCondition(p,target,tier,races) {
  const blocked = p.unknown || !['n','points','top2','top3','accident_min'].every(k=>Number.isInteger(p[k])&&p[k]>=0);
  if(blocked)return {state:'blocked',message:'計算条件が未確認のため保留'};
  if(!Number.isFinite(target)||target<0||target>12||!Array.isArray(races)||races.length>12||
      races.some(points=>!Array.isArray(points)||points.length!==6||points.some(v=>!Number.isInteger(v)||v<1||v>13)))
    return {state:'blocked',message:'目標または残り出走の着順点を確認してください'};
  const rest=races.length,total=p.n+rest,minimum=tier==='A1'?90:80;
  if(!total)return {state:'blocked',message:'出走数がありません'};
  const cents=Math.round(target*100);
  const needed=Math.max(0,Math.ceil((cents*total-100*p.points)/100));
  const top2Needed=Math.max(0,Math.ceil(3*total/10)-p.top2),top3Needed=Math.max(0,Math.ceil(4*total/10)-p.top3);
  const result={state:'goal',rest,total,needed,top2Needed,top3Needed};
  if(total<minimum)return {...result,state:'starts_short',message:`この${rest}走を加えても出走条件に${minimum-total}走不足`};
  if(p.accident_min*100>70*total)return {...result,state:'accident_block',message:'確認済み事故点だけで、残り完走後も事故率0.70超'};
  const qualifies=ranks=>ranks.reduce((s,rank,i)=>s+races[i][rank-1],0)>=needed&&
    ranks.filter(r=>r<=2).length>=top2Needed&&ranks.filter(r=>r<=3).length>=top3Needed;
  if(!rest)return {...result,state:needed===0&&top2Needed===0&&top3Needed===0?'met':'unmet'};
  if(!qualifies(Array(rest).fill(1)))return {...result,state:'impossible'};
  if(qualifies(Array(rest).fill(6)))return {...result,state:'safe'};
  if(rest===1){
    return {...result,bestAllowed:Math.max(...[1,2,3,4,5,6].filter(r=>qualifies([r])))};
  }
  if(rest===2){
    const passing=[];
    for(let a=1;a<=6;a++)for(let b=1;b<=6;b++)if(qualifies([a,b]))passing.push([a,b]);
    let boundary=passing.filter(v=>!passing.some(w=>w[0]>=v[0]&&w[1]>=v[1]&&(w[0]>v[0]||w[1]>v[1])));
    const unordered=races[0].every((v,i)=>v===races[1][i]);
    if(unordered)boundary=boundary.filter(v=>v[0]<=v[1]);
    return {...result,examples:boundary.slice(0,3),unordered};
  }
  return result;
}
if(typeof module!=='undefined')module.exports={seasonRankPoints,seasonCondition};
if(typeof document!=='undefined')(() => {
  const source=document.getElementById('sw-data');if(!source)return;
  const data=JSON.parse(source.textContent),by=id=>document.getElementById(id);
  const clean=x=>String(x??'').normalize('NFKC').toLowerCase().replace(/\s/g,'');
  const hit=(p,q)=>!q||clean([p.name,p.kana,p.toban,p.branch].join(' ')).includes(clean(q));
  function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function who(p){const a=el('a',p.name.replace(/\s/g,''),'sw-name');a.href=`../racer/${p.toban}.html`;return a;}
  function detail(lines){const d=el('details',undefined,'sw-card-note');d.append(el('summary','詳しく'));for(const line of lines)if(line)d.append(el('p',line));return d;}
  function conditionBlock(p,target,tier){
    const box=el('div',undefined,'sw-condition'),context=data.conditions_context||{},c=p.condition||{};
    const scenario=by('sw-mode').value==='scenario';
    const issues=[...(context.issues||[]),...(c.issues||[])];
    const base=c.live_results_added?`当日${c.live_results_added}走の確認結果を反映`:`${context.baseline_through||data.through}の結果まで`;
    let races,title;
    if(scenario){
      const count=Number(by('sw-remaining').value);
      if(!Number.isInteger(count)||count<1||count>12){box.append(el('p','仮定する残り走数は１〜12走で指定してください'));return box;}
      races=Array.from({length:count},(_,i)=>seasonRankPoints(by('sw-kind').value,by('sw-final').checked&&i===count-1));
      title=`期末まで残り${count}走と仮定`;
    }else{
      if(!c.programme_complete)issues.push('本日の出走予定を確認できていません。仮定モードで計算できます');
      races=(c.races||[]).map(r=>r.points);
      if(races.some(r=>!r))issues.push('残り出走の競走区分・着順点が未確認');
      title=context.last_day?`期末当日・確認できた残り${races.length}走`:`本日確認できた残り${races.length}走（期末全体は未確定）`;
    }
    const shortTitle=scenario?`残り${races.length}走と仮定`:context.last_day?`期末当日・残り${races.length}走`:`本日あと${races.length}走`;
    box.append(el('p',shortTitle,'sw-condition-title'));
    if(issues.length){box.append(el('strong','計算保留'),detail([...new Set(issues),title,base]));return box;}
    const result=seasonCondition(p,target,tier,races);
    let text=result.message||'';
    if(result.state==='goal')text=result.rest===1?`${result.bestAllowed}着以上が目安`:`合計${result.needed}点以上が必要`;
    if(result.state==='safe')text=result.rest===1?'6着でも目標以上':'全走6着でも目標以上';
    if(result.state==='impossible')text=result.rest===1?'1着でも目標に届かない':'全走1着でも目標に届かない';
    if(result.state==='met')text='現在の条件クリア（参考）';
    if(result.state==='unmet')text='現在は目標に未達';
    if(result.state==='starts_short')text=`出走条件 あと${Math.max(0,(tier==='A1'?90:80)-p.n)}走`;
    if(result.state==='accident_block')text='事故率条件に未達';
    if(result.state==='blocked')text='計算保留';
    box.append(el('strong',text));
    const notes=[title,result.message];
    if(result.rest>0&&result.needed!==undefined){
      box.append(el('p',`必要平均 ${ (result.needed/result.rest).toFixed(2)}点`,'sw-card-note'));
      notes.push(`必要な着順点 合計${result.needed}点 ／ １走平均${(result.needed/result.rest).toFixed(2)}点`);
      if(result.examples?.length)notes.push('組み合わせ例：'+result.examples.map(v=>result.unordered?`${v[0]}着＋${v[1]}着`:`１走目${v[0]}着→２走目${v[1]}着`).join(' ／ ')+(result.unordered?'（順不同）':''));
      if(result.top2Needed||result.top3Needed)notes.push(`連対率条件：２着以内あと${result.top2Needed}回・３着以内あと${result.top3Needed}回`);
    }
    if(!scenario&&c.races?.length)notes.push(c.races.map(r=>`${r.venue}${r.rno}R ${r.deadline}締切`).join(' ／ '));
    notes.push(base+' ／ 事故・欠場・同着なしの参考条件。級別確定ではありません。');box.append(detail(notes));
    return box;
  }
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
      const stat=el('div',undefined,'sw-score');stat.setAttribute('aria-label','参考勝率と目標');stat.append(el('strong',p.win.toFixed(2)),el('span',`目標 ${target.toFixed(2)}`,p.diff>=-.005?'dgood':'sub'));
      const nums=el('div',undefined,'sw-metrics');
      nums.append(el('span',`出走 ${p.n}走`),el('span',p.n<minimum?`出走条件 あと${minimum-p.n}走`:'出走条件クリア'));
      const issues=[];if(p.n<minimum)issues.push(`${tier}の出走条件まであと${minimum-p.n}回`);
      if(p.top2/p.n<.30||p.top3/p.n<.40)issues.push('連対率条件に未達');
      if(p.accident_min/p.n>.70)issues.push('確認済み事故点だけで事故率0.70超');
      if(p.unknown)issues.push(`計算条件未確認 ${p.unknown}走`);
      card.append(head,stat,nums);
      if(issues.length)card.append(detail(issues));
      card.append(conditionBlock(p,target,tier));
      list.append(card);
    }
    by('sw-count').textContent=`${rows.length.toLocaleString()}人 ／ ${Math.min(limit,rows.length)}人を表示・参考値です`;
    by('sw-more').hidden=limit>=rows.length;
  }
  for(const id of ['sw-target','sw-scope','sw-q','sw-sort','sw-mode','sw-remaining','sw-kind','sw-final'])by(id).addEventListener('input',()=>{
    by('sw-scenario').hidden=by('sw-mode').value!=='scenario';limit=20;scoreList();
  });
  by('sw-tier').addEventListener('change',()=>{const b=data.borders[by('sw-tier').value];by('sw-target').value=(b.win??b.previous_official??5.5).toFixed(2);limit=20;scoreList();});
  by('sw-more').addEventListener('click',()=>{limit+=20;scoreList();});
  scoreList();
})();
