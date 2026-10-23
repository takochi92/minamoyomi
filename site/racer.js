/* Read-only visual presentation of saved official results. */
(function () {
  'use strict';
  var source=document.getElementById('rd-data');if(!source)return;
  var data=JSON.parse(source.textContent),pageNo=0,size=30;
  var colors=['#59d8c7','#efb866','#eb858e','#89a8ec','#667986','#b497d8'];
  var kim=['逃げ','差し','まくり','まくり差し','抜き','恵まれ'];
  var $=function(id){return document.getElementById(id);};
  var esc=function(v){return String(v==null?'—':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});};
  var pc=function(v,n){return n?(100*v/n).toFixed(1)+'%':'—';};
  var date=function(v){return v?v.slice(0,4)+'/'+v.slice(4,6)+'/'+v.slice(6,8):'未保存';};
  function matrix(head,rows,css){return '<table class="rv-matrix '+(css||'')+'"><thead><tr>'+head.map(function(x){return '<th scope="col">'+esc(x)+'</th>';}).join('')+'</tr></thead><tbody>'+(rows.join('')||'<tr><td colspan="'+head.length+'">記録なし</td></tr>')+'</tbody></table>';}
  function heat(v,n){return ' style="background:rgba(89,216,199,'+(n ? 0.04+0.22*v/n : 0)+')"';}
  function section(title,body,note){return '<section class="panel rd-section"><h2>'+esc(title)+'</h2>'+body+(note?'<details class="rd-help"><summary>集計条件を確認</summary><p>'+esc(note)+'</p></details>':'')+'</section>';}
  function stats(groups,label){
    var rows=[],detail=[];
    Object.keys(groups).sort().forEach(function(k){var m=groups[k],p=m.places,n=m.n;
      rows.push('<tr><th scope="row">'+esc(label(k))+'<small>'+n+'走'+(n>0&&n<30?' · 少数':'')+'</small></th>'+[p[0],p[0]+p[1],p[0]+p[1]+p[2]].map(function(v){return '<td'+heat(v,n)+'><b>'+pc(v,n)+'</b></td>';}).join('')+'</tr>');
      detail.push('<tr><th scope="row">'+esc(label(k))+'</th><td>'+(m.st==null?'—':m.st.toFixed(2)+'<small>'+m.st_n+'走</small>')+'</td><td>'+m.f+'</td><td>'+m.l+'</td></tr>');
    });
    return matrix(['区分','1着','2連対','3連対'],rows)+'<p class="rv-caption">2連対＝1・2着 ／ 3連対＝1〜3着</p><details class="rv-details"><summary>平均ST・F・Lを見る</summary>'+matrix(['区分','平均ST','F','L'],detail)+'</details>';
  }
  function parts(w){
    var wins=w.course['1']?w.course['1'].places[0]:0;
    var values=['差し','まくり','まくり差し'].map(function(kind){return Object.keys(w.losses).reduce(function(sum,k){return sum+(k.split('コース・')[1]===kind?w.losses[k]:0);},0);});
    return [['1着',wins],['差しで敗戦',values[0]],['まくりで敗戦',values[1]],['まくり差しで敗戦',values[2]],['その他・確認不可',w.inside_n-wins-values.reduce(function(a,b){return a+b;},0)]];
  }
  function donut(items,n){
    var offset=0,arcs='',legend='';
    items.forEach(function(item,i){var amount=n?100*item[1]/n:0;
      if(n&&item[1])arcs+='<circle cx="50" cy="50" r="40" pathLength="100" fill="none" stroke="'+colors[i]+'" stroke-width="13" stroke-dasharray="'+amount+' '+(100-amount)+'" stroke-dashoffset="'+(-offset)+'"/>';
      offset+=amount;
      legend+='<li><i style="background:'+colors[i]+'"></i><span>'+esc(item[0])+'</span><b>'+item[1]+'回</b><small>'+pc(item[1],n)+'</small></li>';
    });
    return '<div class="rv-composition"><div class="rv-donut" role="img" aria-label="'+esc('1コース'+n+'走。'+items.map(function(x){return x[0]+x[1]+'回';}).join('、'))+'"><svg viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="40" fill="none" stroke="#263743" stroke-width="13"/>'+arcs+'</svg><div><small>1コース1着</small><strong>'+pc(items[0][1],n)+'</strong><span>'+n+'走</span></div></div><ul class="rv-legend">'+legend+'</ul></div>';
  }
  function losses(w){
    var rows=[],kinds=['差し','まくり','まくり差し','その他'];
    for(var c=2;c<=6;c++){
      var vals=kinds.map(function(kind){return Object.keys(w.losses).reduce(function(total,k){var pair=k.split('コース・'),yes=kind==='その他'?kinds.slice(0,3).indexOf(pair[1])<0:pair[1]===kind;return total+(pair[0]===String(c)&&yes?w.losses[k]:0);},0);});
      rows.push('<tr><th scope="row"><span class="bt bt'+c+'">'+c+'</span></th>'+vals.map(function(v){return '<td'+heat(v,w.inside_n)+'>'+v+'<small>回</small></td>';}).join('')+'</tr>');
    }
    return matrix(['相手','差し','まくり','まくり差し','その他'],rows,'rv-loss-matrix');
  }
  function bars(items,n){return '<div class="rv-bars">'+items.map(function(x,i){var ci=kim.indexOf(x[0]);return '<div class="rv-bar-row"><span>'+esc(x[0])+'</span><div class="rv-track"><i style="width:'+(n?100*x[1]/n:0)+'%;background:'+colors[ci<0?i%colors.length:ci]+'"></i></div><b>'+x[1]+'<small>回</small></b><em>'+pc(x[1],n)+'</em></div>';}).join('')+'</div>';}
  function overview(w){
    var m=w.total,p=m.places,n=m.n;
    $('rd-summary').innerHTML=[['出走数',n,'保存された出走'],['1着率',pc(p[0],n),p[0]+'勝'],['2連対率',pc(p[0]+p[1],n),(p[0]+p[1])+'回'],['3連対率',pc(p[0]+p[1]+p[2],n),(p[0]+p[1]+p[2])+'回']].map(function(x){return '<div><span>'+x[0]+'</span><strong>'+x[1]+'</strong><small>'+x[2]+'</small></div>';}).join('');
    var items=kim.map(function(k){return [k,m.kim[k]];}).sort(function(a,b){return b[1]-a[1];}),wins=items.reduce(function(sum,x){return sum+x[1];},0);
    $('rd-overview-detail').innerHTML='<h3>1コースの結果</h3>'+donut(parts(w),w.inside_n)+'<h3>負けた相手と勝ち方</h3>'+losses(w)+'<p class="rv-caption">本番の進入コース別。数値は回数。対象：1コース'+w.inside_n+'走。</p><h3>1着の決まり手</h3>'+bars(items,wins)+'<p class="rv-caption">決まり手を確認できた1着'+wins+'回の内訳。</p>';
  }
  function courses(w){
    var methods='';
    for(var c=1;c<=6;c++){
      var m=w.course[c]||{n:0,kim:{}},count=0;
      methods+='<div class="rv-method-row"><span class="bt bt'+c+'">'+c+'</span><div class="rv-track rv-stack">'+kim.map(function(k,i){var v=m.kim[k]||0;count+=v;return '<i style="width:'+(m.n?100*v/m.n:0)+'%;background:'+colors[i]+'" title="'+k+' '+v+'勝"></i>';}).join('')+'</div><b>'+count+'<small>勝</small></b></div>';
    }
    var legend='<p class="rv-swatches">'+kim.map(function(k,i){return '<span><i style="background:'+colors[i]+'"></i>'+k+'</span>';}).join('')+'</p>';
    var rows=Object.keys(w.remain).sort().map(function(c){var m=w.remain[c],n=m.n,p=m.places;return '<tr><th>'+esc(c)+'コース<small>'+n+'走</small></th><td>'+pc(p[1],n)+'</td><td>'+pc(p[2],n)+'</td><td>'+pc(p[1]+p[2],n)+'</td></tr>';});
    $('course').innerHTML=section('コース別成績',stats(w.course,function(c){return c+'コース';}),'本番の進入コース別。出走数が30未満の行には「少数」と表示。')+section('コースごとの勝ち方',legend+'<div class="rv-bars">'+methods+'</div>','棒全体を各コースの全出走としています。色のない部分は1着以外・決まり手未確認。')+section('艇番別成績',stats(w.frame,function(c){return c+'号艇';}))+section('1コースが逃げたときの残り方',matrix(['コース','2着','3着','2・3着'],rows),'自艇が外に入り、1コースの選手が「逃げ」で勝ったレースが分母。');
  }
  function changeWindow(key){
    var w=data.windows[key],labels={'90':'直近3か月','365':'直近1年','730':'直近2年','all':'保存全期間'};
    document.querySelectorAll('[data-rd-window]').forEach(function(b){var on=b.dataset.rdWindow===key;b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on));});
    $('rd-period-label').textContent=labels[key]+' · '+date(w.from)+'〜'+date(w.through)+'の保存分';
    overview(w);courses(w);
    $('venue').innerHTML=section('場別成績',stats(w.venue,function(j){return data.venues[j]||j;}),'各場での実測成績。出走数も確認してください。');
    $('exhibition').innerHTML=section('展示タイム順位別の成績',stats(w.exhibition,function(k){return k+'位';}),'6艇の展示タイムが揃ったレースだけ。同タイムは同順位（1位・1位・3位）。因果効果ではありません。');
  }
  document.querySelectorAll('[data-rd-window]').forEach(function(b){b.addEventListener('click',function(){changeWindow(b.dataset.rdWindow);});});
  var links=Array.from(document.querySelectorAll('.rd-tabs a'));
  var historyPromise=null;
  function loadHistory(){
    if(!data.history_url)return Promise.resolve();
    if(!historyPromise){
      $('rd-history-count').textContent='全出走結果を読み込んでいます…';
      historyPromise=fetch(data.root+data.history_url).then(function(r){if(!r.ok)throw Error('fetch');return r.json();}).then(function(rows){data.rows=rows;data.history_url=null;historyRows();}).catch(function(){historyPromise=null;$('rd-history-count').textContent='読み込めませんでした。全出走結果タブを開き直すと再試行します。';});
    }
    return historyPromise;
  }
  function tab(){var key=location.hash.slice(1);if(!links.some(function(a){return a.hash==='#'+key;}))key='overview';document.querySelectorAll('.rd-panel').forEach(function(p){p.hidden=p.id!==key;});links.forEach(function(a){var on=a.hash==='#'+key;a.classList.toggle('on',on);if(on)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');});if(key==='history')loadHistory();}
  links.forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();history.pushState(null,'',a.hash);tab();});});window.addEventListener('hashchange',tab);window.addEventListener('popstate',tab);tab();
  function historyRows(){
    var y=$('rd-year').value,v=$('rd-venue').value,c=$('rd-course').value;
    var rows=data.rows.filter(function(r){return (!y||r[0].slice(0,4)===y)&&(!v||r[1]===v)&&(!c||String(r[4])===c);});
    var pages=Math.max(1,Math.ceil(rows.length/size));pageNo=Math.max(0,Math.min(pageNo,pages-1));
    $('rd-history-count').textContent=data.history_url?'最新30件 / 全'+data.history_count.toLocaleString('ja-JP')+'件（全出走結果タブで読み込み）':'該当 '+rows.length.toLocaleString('ja-JP')+'件 / 全'+data.rows.length.toLocaleString('ja-JP')+'件';
    $('rd-history-table').innerHTML='<div class="rv-races">'+(rows.slice(pageNo*size,(pageNo+1)*size).map(function(r){
      var numeric=typeof r[5]==='number',place=String(r[5]),fields=[['艇番',r[3]],['進入',r[4]?r[4]+'コース':'—'],['ST',r[6]==null?'—':r[7]+(r[6]/100).toFixed(2)],['展示',r[8]?(r[8]/100).toFixed(2):'—'],['モーター',r[9]==null?'未保存':r[9]],['ボート',r[10]==null?'未保存':r[10]]];
      var meta=r[15]||{};
      return '<details class="rv-race"><summary><time>'+date(r[0])+'</time><span>'+esc(data.venues[r[1]]||r[1])+' '+r[2]+'R</span><b class="rv-finish rv-finish-'+(numeric?place:'other')+'">'+esc(place+(numeric?'着':''))+'</b><i>＋</i></summary>'+(meta.title?'<p>'+esc(meta.title)+' · '+esc(meta.race_name)+'</p>':'')+'<dl>'+fields.map(function(f){return '<div><dt>'+f[0]+'</dt><dd>'+esc(f[1])+'</dd></div>';}).join('')+'</dl><p>勝者の決まり手：'+esc(r[11]||'未確認')+' · 3連単払戻 '+(r[13]==null?'未保存':Number(r[13]).toLocaleString('ja-JP')+'円／100円')+'</p></details>';
    }).join('')||'<p class="rv-caption">該当する記録はありません。</p>')+'</div>';
    $('rd-page').textContent=(pageNo+1)+' / '+pages;$('rd-prev').hidden=false;$('rd-next').hidden=false;$('rd-prev').disabled=pageNo===0;$('rd-next').disabled=pageNo>=pages-1;
  }
  ['rd-year','rd-venue','rd-course'].forEach(function(id){$(id).addEventListener('change',function(){pageNo=0;historyRows();});});$('rd-prev').addEventListener('click',function(){pageNo--;historyRows();});$('rd-next').addEventListener('click',function(){pageNo++;historyRows();});historyRows();
})();
