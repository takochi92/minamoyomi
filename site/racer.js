/* Saved official results: display filters only, never prediction logic. */
(function () {
  'use strict';
  var source = document.getElementById('rd-data');
  if (!source) return;
  var data = JSON.parse(source.textContent), windowKey = '365', pageNo = 0, size = 30;
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (v) { return String(v == null ? '—' : v).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); };
  var pc = function (v,n) { return n ? (100*v/n).toFixed(1)+'%' : '—'; };
  var date = function (v) { return v ? v.slice(0,4)+'/'+v.slice(4,6)+'/'+v.slice(6,8) : '未保存'; };
  var labels = {'365':'直近1年','730':'直近2年','all':'保存全期間'};
  function table(headers, rows) {
    rows=rows.map(function(row){var column=0;return row.replace(/<(td|th)([^>]*)>([\s\S]*?)<\/\1>/g,function(all,tag,attrs,content){var label=headers[column]||'',lead=column===0?' data-rd-lead="true"':'';column++;return '<'+tag+attrs+' data-label="'+esc(label)+'"'+lead+'>'+content+'</'+tag+'>';});});
    var kind=headers.length===7&&headers[2]==='1着率'?' data-rd-kind="stats"':'';
    return '<div class="tbl-wrap rd-table-wrap"><table class="rd-table"'+kind+'><thead><tr>'+headers.map(function (h) {return '<th scope="col">'+esc(h)+'</th>';}).join('')+'</tr></thead><tbody>'+(rows.join('')||'<tr><td colspan="'+headers.length+'">該当する記録はありません</td></tr>')+'</tbody></table></div>';
  }
  function stats(groups,label) {
    return table(['区分','出走','1着率','2連対率','3連対率','平均ST (件)','F/L'],Object.keys(groups).sort().map(function(k){
      var m=groups[k], p=m.places,n=m.n;
      return '<tr><th>'+esc(label(k))+(n>0&&n<30?'<br><small>少数例</small>':'')+'</th>'+[n,pc(p[0],n),pc(p[0]+p[1],n),pc(p[0]+p[1]+p[2],n),m.st==null?'—':m.st.toFixed(2)+' ('+m.st_n+')',m.f+'/'+m.l].map(function(v){return '<td>'+esc(v)+'</td>';}).join('')+'</tr>';
    }));
  }
  function section(title,content,note) {return '<section class="panel rd-section"><h2>'+esc(title)+'</h2>'+content+(note?'<details class="rd-help"><summary>集計条件を確認</summary><p class="sub">'+esc(note)+'</p></details>':'')+'</section>';}
  function overview(w) {
    var m=w.total,p=m.places,n=m.n;
    $('rd-summary').innerHTML=[['出走数',n.toLocaleString('ja-JP'),'欠場・出遅れ返還を除く'],['1着率',pc(p[0],n),p[0]+'勝 / '+n+'走'],['2連対率',pc(p[0]+p[1],n),(p[0]+p[1])+'回 / '+n+'走'],['3連対率',pc(p[0]+p[1]+p[2],n),(p[0]+p[1]+p[2])+'回 / '+n+'走']].map(function(x){return '<div><span>'+x[0]+'</span><strong>'+x[1]+'</strong><small>'+x[2]+'</small></div>';}).join('');
    var losses=Object.keys(w.losses).map(function(k){var parts=k.split('コース・'),c=parts[0],decision=parts[1]||'決まり手不明',action={'差し':'差して勝利','まくり':'まくって勝利','まくり差し':'まくり差して勝利'}[decision]||'「'+decision+'」で勝利';return '<div class="rd-loss-row">'+(/^[2-6]$/.test(c)?'<span class="bt bt'+c+'">'+c+'</span>':'')+'<div><strong>'+esc(c+'コースが'+action)+'</strong><small>1コース'+w.inside_n+'走中、'+w.losses[k]+'回</small></div><b>'+pc(w.losses[k],w.inside_n)+'</b></div>';});
    var lossHtml=losses.length?'<div class="rd-loss-list">'+losses.slice(0,3).join('')+'</div>':'<p class="sub">勝者を確認できた負けレースはありません。</p>';
    if(losses.length>3)lossHtml+='<details class="rd-more"><summary>ほか'+(losses.length-3)+'パターンを見る</summary><div class="rd-loss-list">'+losses.slice(3).join('')+'</div></details>';
    $('rd-overview-detail').innerHTML='<h3>1着になったときの勝ち方</h3><div class="rd-decisions">'+Object.keys(m.kim).map(function(k){return '<div><span>'+esc(k)+'</span><b>'+m.kim[k]+'勝</b><small>'+pc(m.kim[k],n)+' / 全'+n+'走</small></div>';}).join('')+'</div><h3>1コースで負けたレース</h3><p class="sub">相手のコースと勝ち方を、多かった順に表示します。</p>'+lossHtml+'<p class="sub">割合は1コース全'+w.inside_n+'走に対するもの。事故等も含む結果で、負けた原因の断定ではありません。</p>';
  }
  function courses(w) {
    var bars='<p class="rd-legend"><span>● 1着</span><span>● 2着</span><span>● 3着</span><small>残りは4着以下・事故等</small></p>';
    for(var c=1;c<=6;c++){
      var m=w.course[c]||{n:0,places:[0,0,0]},p=m.places,n=m.n;
      bars+='<div class="rd-course-bar"><span class="bt bt'+c+'">'+c+'</span><div><div class="rd-bar" aria-hidden="true">'+p.slice(0,3).map(function(v,i){return '<i class="rd-place-'+(i+1)+'" style="width:'+(n?100*v/n:0)+'%"></i>';}).join('')+'</div><small>1着 '+pc(p[0],n)+' · 2着 '+pc(p[1],n)+' · 3着 '+pc(p[2],n)+'</small></div><b>'+n+'走</b></div>';
    }
    var kim=['逃げ','差し','まくり','まくり差し','抜き','恵まれ'];
    var wins=table(['コース','出走'].concat(kim),Object.keys(w.course).sort().map(function(c){var m=w.course[c];return '<tr><th>'+esc(c)+'コース</th><td>'+m.n+'</td>'+kim.map(function(k){return '<td>'+m.kim[k]+'勝<br><small>'+pc(m.kim[k],m.n)+'</small></td>';}).join('')+'</tr>';}));
    var remain=table(['コース','対象数','2着率','3着率','2・3着率'],Object.keys(w.remain).sort().map(function(c){var m=w.remain[c],p=m.places,n=m.n;return '<tr><th>'+esc(c)+'コース</th>'+[n,pc(p[1],n),pc(p[2],n),pc(p[1]+p[2],n)].map(function(v){return '<td>'+esc(v)+'</td>';}).join('')+'</tr>';}));
    $('course').innerHTML=section('進入コース別成績',bars+stats(w.course,function(c){return c+'コース';})+'<h3>コースごとの勝ち方</h3>'+wins,'艇番ではなく本番の進入コースで集計。勝ち方の率はそのコース全出走が分母です。')+section('艇番別成績',stats(w.frame,function(c){return c+'号艇';}))+section('1コースが逃げたときの残り方',remain,'この選手が2〜6コースに入り、1コースの選手が「逃げ」で勝ったレースが分母。対象数が少ない場合は変動が大きくなります。');
  }
  function changeWindow(key) {
    windowKey=key;
    var w=data.windows[key];
    document.querySelectorAll('[data-rd-window]').forEach(function(b){b.classList.toggle('on',b.dataset.rdWindow===key);b.setAttribute('aria-pressed',String(b.dataset.rdWindow===key));});
    $('rd-period-label').textContent=labels[key]+' · '+date(w.from)+'〜'+date(w.through)+'の保存分';
    overview(w);courses(w);
    $('venue').innerHTML=section('場別成績',stats(w.venue,function(j){return data.venues[j]||j;}),'各場での実測成績。少数例は変動が大きいため、出走数も確認してください。');
    $('exhibition').innerHTML=section('展示タイム順位別の成績',stats(w.exhibition,function(k){return k+'位';}),'6艇の展示タイムが揃ったレースだけ。同タイムは同順位（1位・1位・3位）。展示順位による因果効果ではありません。');
  }
  document.querySelectorAll('[data-rd-window]').forEach(function(b){b.addEventListener('click',function(){changeWindow(b.dataset.rdWindow);});});
  // All sections remain visible with JavaScript disabled; tab links remain addressable.
  var links=Array.from(document.querySelectorAll('.rd-tabs a'));
  function tab() {
    var key=location.hash.slice(1), known=links.some(function(a){return a.hash==='#'+key;});
    if(!known)key='overview';
    document.querySelectorAll('.rd-panel').forEach(function(p){p.hidden=p.id!==key;});
    links.forEach(function(a){var on=a.hash==='#'+key;a.classList.toggle('on',on);if(on)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');});
  }
  links.forEach(function(a){a.addEventListener('click',function(ev){ev.preventDefault();history.pushState(null,'',a.hash);tab();});});
  window.addEventListener('hashchange',tab);window.addEventListener('popstate',tab);tab();
  function historyRows() {
    var y=$('rd-year').value,v=$('rd-venue').value,c=$('rd-course').value;
    var rows=data.rows.filter(function(r){return (!y||r[0].slice(0,4)===y)&&(!v||r[1]===v)&&(!c||String(r[4])===c);});
    var pages=Math.max(1,Math.ceil(rows.length/size));pageNo=Math.max(0,Math.min(pageNo,pages-1));
    var visible=rows.slice(pageNo*size,(pageNo+1)*size);
    $('rd-history-count').textContent='該当 '+rows.length.toLocaleString('ja-JP')+'件 / 全'+data.rows.length.toLocaleString('ja-JP')+'件（保存全期間）';
    $('rd-history-table').innerHTML=table(['日付','場・R','艇番','進入コース','着順','ST','展示タイム','モーター','ボート','勝者の決まり手'],visible.map(function(r){return '<tr>'+[date(r[0]),(data.venues[r[1]]||r[1])+' '+r[2]+'R',r[3],r[4],r[5],r[6]==null?'—':r[7]+(r[6]/100).toFixed(2),r[8]?(r[8]/100).toFixed(2):'—',r[9],r[10],r[11]||'—'].map(function(v){return '<td>'+esc(v)+'</td>';}).join('')+'</tr>';}));
    $('rd-page').textContent=(pageNo+1)+' / '+pages;$('rd-prev').hidden=false;$('rd-next').hidden=false;$('rd-prev').disabled=pageNo===0;$('rd-next').disabled=pageNo>=pages-1;
  }
  ['rd-year','rd-venue','rd-course'].forEach(function(id){$(id).addEventListener('change',function(){pageNo=0;historyRows();});});
  $('rd-prev').addEventListener('click',function(){pageNo--;historyRows();});$('rd-next').addEventListener('click',function(){pageNo++;historyRows();});historyRows();
})();
