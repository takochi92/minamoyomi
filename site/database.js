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
function render(){
 var venue=$('db-venue').value,day=$('db-day').value,race=$('db-race').value,min=+$('db-payout').value,type=$('db-type').value;
 var selected=rows.filter(function(r){var meta=r[12]||{},label=(meta.race_name||'').replace(/\s/g,'');return (!venue||r[1]===venue)&&(!day||r[0].slice(6)===day)&&(!race||String(r[2])===race)&&(!min||r[9]>=min)&&(!type||(type==='fl'?r[11].some(function(e){return e[4]==='F'||e[4]==='L';}):type==='tie'?r[11].filter(function(e){return e[5]===1;}).length>1:/優勝/.test(label)&&!/準/.test(label)));});
 var pages=Math.max(1,Math.ceil(selected.length/size));page=Math.max(0,Math.min(page,pages-1));
 $('db-count').textContent='該当 '+selected.length.toLocaleString('ja-JP')+'件 ／ この月の保存 '+rows.length.toLocaleString('ja-JP')+'件';
 $('db-races').innerHTML=selected.slice(page*size,(page+1)*size).map(function(r){var meta=r[12]||{},pay=r[9]==null?'払戻未保存':Number(r[9]).toLocaleString('ja-JP')+'円';
 var boats=r[11].map(function(e){return '<tr><th>'+esc(e[5])+(typeof e[5]==='number'?'着':'')+'</th><td><span class="bt bt'+e[0]+'">'+e[0]+'</span></td><td>'+player(e)+'<details><summary>展示・機器番号</summary><dl class="db-facts">'+fields(e)+'</dl></details></td><td>'+esc(e[3]==null?'未保存':e[4]+(e[3]/100).toFixed(2))+'</td></tr>';}).join('');
 return '<details class="panel db-term db-race"><summary><b>'+r[0].slice(0,4)+'/'+r[0].slice(4,6)+'/'+r[0].slice(6)+' '+esc(data.venues[r[1]]||r[1])+' '+r[2]+'R</b><span>'+esc(r[8]||'組番未保存')+' · '+pay+'</span></summary>'+(meta.title?'<p>'+esc(meta.title)+'<small> · '+esc(meta.race_name)+'</small></p>':'')+'<table class="rv-matrix db-race-boats"><thead><tr><th>着</th><th>艇</th><th>選手</th><th>ST</th></tr></thead><tbody>'+boats+'</tbody></table><p class="sub">決まり手 '+esc(r[3]||'未確認')+' · 風 '+esc(r[4])+' '+esc(r[5])+'m · 波 '+esc(r[6])+'cm'+(r[7]?' · 進入固定':'')+'</p><p class="sub">3連単払戻 '+pay+'（100円あたり）'+(r[10]==null?'':' · '+esc(r[10])+'番人気')+'</p></details>';
 }).join('')||'<section class="panel"><p>該当する保存結果はありません。未取得日もあるため、非開催・該当なしとは断定しません。</p></section>';
 $('db-page').textContent=(page+1)+' / '+pages;$('db-prev').disabled=page===0;$('db-next').disabled=page>=pages-1;
}
async function load(){var token=++request;rows=[];page=0;$('db-count').textContent='選んだ月の結果を読み込んでいます…';$('db-races').innerHTML='';$('db-prev').disabled=$('db-next').disabled=true;
 try{var response=await fetch('../data/database/races/'+$('db-month').value+'.json');if(!response.ok)throw Error('fetch');var result=await response.json();if(token!==request)return;rows=result;render();}catch(e){if(token===request)$('db-count').textContent='読み込めませんでした。月を選び直すと再試行します。';}
}
['db-venue','db-day','db-race','db-payout','db-type'].forEach(function(id){$(id).addEventListener('change',function(){page=0;render();});});$('db-month').addEventListener('change',load);$('db-prev').addEventListener('click',function(){page--;render();});$('db-next').addEventListener('click',function(){page++;render();});if(data.months.length)load();else $('db-count').textContent='保存ファイルはまだありません。';
})();
