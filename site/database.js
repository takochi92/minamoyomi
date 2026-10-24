/* Public official results. No prediction tickets or ROI are recomputed here. */
(function(){
'use strict';
var node=document.getElementById('db-data');if(!node)return;
var data=JSON.parse(node.textContent),rows=[],page=0,size=30,request=0;
var $=function(id){return document.getElementById(id);};
var params=new URLSearchParams(typeof location==='undefined'?'':location.search);
[['month',data.months],['venue',Object.keys(data.venues)],['day',Array.from({length:31},function(_,i){return String(i+1).padStart(2,'0');})],['race',Array.from({length:12},function(_,i){return String(i+1);})]].forEach(function(pair){var value=params.get(pair[0]);if(pair[1].indexOf(value)>=0)$('db-'+pair[0]).value=value;});
var esc=function(x){return String(x==null?'—':x).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});};
function player(e){return '<a href="../racer/'+esc(e[1])+'.html">'+esc(e[10]||data.names[e[1]]||e[1])+'</a>';}
function fields(e){return [['艇番',e[0]],['進入',e[2]?e[2]+'コース':'未確認'],['展示',e[6]?(e[6]/100).toFixed(2):'未保存'],['モーター',e[8]==null?'未保存':e[8]],['ボート',e[9]==null?'未保存':e[9]]].map(function(x){return '<div><dt>'+x[0]+'</dt><dd>'+esc(x[1])+'</dd></div>';}).join('');}
function meeting(r){var m=r[12]||{};if(!m.title||!m.day)return '';var d=new Date(Date.UTC(+r[0].slice(0,4),+r[0].slice(4,6)-1,+r[0].slice(6)));d.setUTCDate(d.getUTCDate()-m.day+1);return r[1]+'|'+d.toISOString().slice(0,10)+'|'+m.title;}
function meetings(){var current=$('db-meeting').value,venue=$('db-venue').value,found={};rows.forEach(function(r){var key=meeting(r);if(key&&(!venue||r[1]===venue))found[key]=(data.venues[r[1]]||r[1])+' · '+(r[12]||{}).title+' · 初日推定'+key.split('|')[1];});$('db-meeting').innerHTML='<option value="">すべての開催</option>'+Object.keys(found).sort().map(function(k){return '<option value="'+esc(k)+'">'+esc(found[k])+'</option>';}).join('');$('db-meeting').value=Object.prototype.hasOwnProperty.call(found,current)?current:'';}
function summarize(selected){
 var n=selected.length,pays=selected.filter(function(r){return r[9]!=null;}).map(function(r){return r[9];}).sort(function(a,b){return a-b;}),count=[0,0,0,0,0,0],kim={},combos={};
 selected.forEach(function(r){r[11].forEach(function(e){if(e[5]===1&&e[2]>=1&&e[2]<=6)count[e[2]-1]++;});kim[r[3]||'未確認']=(kim[r[3]||'未確認']||0)+1;if(r[8])combos[r[8]]=(combos[r[8]]||0)+1;});
 var pc=function(v,d){return d?(100*v/d).toFixed(1)+'%':'—';},median=pays.length?(pays[Math.floor((pays.length-1)/2)]+pays[Math.floor(pays.length/2)])/2:null;
 var cards=[['対象レース',n.toLocaleString('ja-JP'),'現在の絞り込み結果'],['イン1着',pc(count[0],n),count[0]+'回 / '+n+'レース'],['万舟の割合',pc(pays.filter(function(p){return p>=10000;}).length,pays.length),'払戻確認 '+pays.length+'件が分母'],['配当の中央値',median==null?'—':median.toLocaleString('ja-JP')+'円','3連単・100円あたり']];
 var bars=count.map(function(v,i){return '<div class="db-course-bar"><span class="bt bt'+(i+1)+'">'+(i+1)+'</span><div class="rv-track"><i style="width:'+(n?Math.min(100,100*v/n):0)+'%"></i></div><b>'+pc(v,n)+'</b><small>'+v+'回</small></div>';}).join('');
 var table=function(obj,denom){return '<table class="rv-matrix"><thead><tr><th>区分</th><th>回数</th><th>割合</th></tr></thead><tbody>'+Object.keys(obj).sort(function(a,b){return obj[b]-obj[a];}).slice(0,12).map(function(k){return '<tr><th>'+esc(k)+'</th><td>'+obj[k]+'</td><td>'+pc(obj[k],denom)+'</td></tr>';}).join('')+'</tbody></table>';};
 var comboN=Object.keys(combos).reduce(function(s,k){return s+combos[k];},0);
 var bins={'1,000円未満':0,'1,000〜4,990円':0,'5,000〜9,990円':0,'1万〜99,990円':0,'10万円以上':0},labels=Object.keys(bins);
 pays.forEach(function(p){bins[labels[p<1000?0:p<5000?1:p<10000?2:p<100000?3:4]]++;});
 $('db-analysis').innerHTML='<section class="panel rd-section"><h2>絞り込んだレースの傾向</h2><div class="rd-summary db-summary">'+cards.map(function(c){return '<div><span>'+c[0]+'</span><strong>'+c[1]+'</strong><small>'+c[2]+'</small></div>';}).join('')+'</div><details class="rv-details"><summary>コース・決まり手・配当・出目を比較</summary><h3>1着の進入コース</h3><div class="rv-bars">'+bars+'</div><p class="sub">対象'+n+'レースが分母。同着は各コースに計上し、進入不明は除外するため合計が100%にならない場合があります。</p><h3>勝者の決まり手</h3>'+table(kim,n)+'<h3>3連単配当の分布</h3>'+table(bins,pays.length)+'<p class="sub">払戻確認'+pays.length+'件が分母。未保存を0円に含めません。</p><h3>3連単の出目 上位12組</h3>'+table(combos,comboN)+'<p class="sub">組番確認'+comboN+'件が分母。配当・結果の絞り込みも適用した過去の集計です。将来の的中率や予想の回収率ではありません。</p></details></section>';
}
function render(){
 var venue=$('db-venue').value,day=$('db-day').value,race=$('db-race').value,min=+$('db-payout').value,type=$('db-type').value,meet=$('db-meeting').value,grade=$('db-grade').value,method=$('db-method').value,course=$('db-course').value;
 var selected=rows.filter(function(r){var meta=r[12]||{},label=(meta.race_name||'').replace(/\s/g,'');return (!venue||r[1]===venue)&&(!day||r[0].slice(6)===day)&&(!race||String(r[2])===race)&&(!meet||meeting(r)===meet)&&(!grade||(grade==='unknown'?!meta.grade:meta.grade===grade))&&(!method||r[3]===method)&&(!course||r[11].some(function(e){return e[5]===1&&String(e[2])===course;}))&&(!min||r[9]>=min)&&(!type||(type==='fl'?r[11].some(function(e){return e[4]==='F'||e[4]==='L';}):type==='tie'?r[11].filter(function(e){return e[5]===1;}).length>1:/優勝/.test(label)&&!/準/.test(label)));});
 summarize(selected);
 var pages=Math.max(1,Math.ceil(selected.length/size));page=Math.max(0,Math.min(page,pages-1));
 $('db-count').textContent='該当 '+selected.length.toLocaleString('ja-JP')+'件 ／ この月の保存 '+rows.length.toLocaleString('ja-JP')+'件';
 $('db-races').innerHTML=selected.slice(page*size,(page+1)*size).map(function(r){var meta=r[12]||{},pay=r[9]==null?'払戻未保存':Number(r[9]).toLocaleString('ja-JP')+'円';
 var boats=r[11].map(function(e){return '<tr><th>'+esc(e[5])+(typeof e[5]==='number'?'着':'')+'</th><td><span class="bt bt'+e[0]+'">'+e[0]+'</span></td><td>'+player(e)+'<details><summary>展示・機器番号</summary><dl class="db-facts">'+fields(e)+'</dl></details></td><td>'+esc(e[3]==null?'未保存':e[4]+(e[3]/100).toFixed(2))+'</td></tr>';}).join('');
 return '<details class="panel db-term db-race"><summary><b>'+r[0].slice(0,4)+'/'+r[0].slice(4,6)+'/'+r[0].slice(6)+' '+esc(data.venues[r[1]]||r[1])+' '+r[2]+'R</b><span>'+esc(r[8]||'組番未保存')+' · '+pay+'</span></summary>'+(meta.title?'<p>'+esc(meta.title)+'<small> · '+esc(meta.race_name)+'</small></p>':'')+'<table class="rv-matrix db-race-boats"><thead><tr><th>着</th><th>艇</th><th>選手</th><th>ST</th></tr></thead><tbody>'+boats+'</tbody></table><p class="sub">決まり手 '+esc(r[3]||'未確認')+' · 風 '+esc(r[4])+' '+esc(r[5])+'m · 波 '+esc(r[6])+'cm'+(r[7]?' · 進入固定':'')+'</p><p class="sub">3連単払戻 '+pay+'（100円あたり）'+(r[10]==null?'':' · '+esc(r[10])+'番人気')+'</p></details>';
 }).join('')||'<section class="panel"><p>該当する保存結果はありません。未取得日もあるため、非開催・該当なしとは断定しません。</p></section>';
 $('db-page').textContent=(page+1)+' / '+pages;$('db-prev').disabled=page===0;$('db-next').disabled=page>=pages-1;
}
async function load(){var token=++request;rows=[];page=0;$('db-count').textContent='選んだ月の結果を読み込んでいます…';$('db-races').innerHTML='';$('db-analysis').innerHTML='';$('db-prev').disabled=$('db-next').disabled=true;
 try{var response=await fetch('../data/database/races/'+$('db-month').value+'.json');if(!response.ok)throw Error('fetch');var result=await response.json();if(token!==request)return;rows=result;meetings();render();}catch(e){if(token===request)$('db-count').textContent='読み込めませんでした。月を選び直すと再試行します。';}
}
['db-venue','db-day','db-race','db-payout','db-type','db-meeting','db-grade','db-method','db-course'].forEach(function(id){$(id).addEventListener('change',function(){page=0;if(id==='db-venue')meetings();render();});});$('db-month').addEventListener('change',load);$('db-prev').addEventListener('click',function(){page--;render();});$('db-next').addEventListener('click',function(){page++;render();});if(data.months.length)load();else $('db-count').textContent='保存ファイルはまだありません。';
})();
