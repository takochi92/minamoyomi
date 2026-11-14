(function () {
  'use strict';
  var periods = {week:'週', month:'月', year:'年'};
  function dateKey(date) { return date.toISOString().slice(0,10).replaceAll('-',''); }
  function chartData(bets, period, now, offset) {
    var start=new Date(Date.UTC(+now.slice(0,4),+now.slice(4,6)-1,+now.slice(6,8)));
    if (period==='week') start.setUTCDate(start.getUTCDate()-(start.getUTCDay()+6)%7+7*offset);
    if (period==='month') { start.setUTCDate(1); start.setUTCMonth(start.getUTCMonth()+offset); }
    if (period==='year') start.setUTCFullYear(start.getUTCFullYear()+offset,0,1);
    var end=new Date(start);
    if (period==='week') end.setUTCDate(end.getUTCDate()+7);
    if (period==='month') end.setUTCMonth(end.getUTCMonth()+1);
    if (period==='year') end.setUTCFullYear(end.getUTCFullYear()+1);
    var buckets=new Map();
    for(var d=new Date(start);d<end;) {
      var key=dateKey(d);
      buckets.set(period==='year'?key.slice(0,6):key,{key:key,net:0,total:0});
      if(period==='year') d.setUTCMonth(d.getUTCMonth()+1); else d.setUTCDate(d.getUTCDate()+1);
    }
    var inv=0, ret=0, count=0;
    for(var b of bets) {
      if(!/^\d{8}$/.test(b.date) || b.date>now) continue;
      var date=new Date(b.date.replace(/^(....)(..)(..)$/,'$1-$2-$3')+'T00:00:00Z');
      if(!Number.isFinite(+date) || dateKey(date)!==b.date) continue;
      var row=buckets.get(period==='year'?b.date.slice(0,6):b.date);
      if(!row) continue;
      var spent=Number(b.inv)||0, returned=Number(b.ret)||0;
      inv+=spent; ret+=returned; count++; row.net+=returned-spent;
    }
    var total=0, latest=-1;
    var rows=Array.from(buckets.values(),function(row,i){
      total+=row.net;row.total=total;
      if(row.key<=(period==='year'?now.slice(0,6)+'01':now)) latest=i;
      return row;
    });
    return {rows:rows,inv:inv,ret:ret,count:count,total:total,start:dateKey(start),latest:latest};
  }
  if (typeof module !== 'undefined') { module.exports = {chartData:chartData}; return; }
  var root = document.querySelector('[data-premium-race], [data-premium-chart], [data-premium-plan]');
  if (!root) return;
  var account = window.TeiNoteAccount, box = root.querySelector('.premium-content');
  var preview = box.innerHTML, selected = 'month', offset = 0, epoch = 0, status, request;
  var dateFormat = new Intl.DateTimeFormat('ja-JP', {timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'});
  var price = new Intl.NumberFormat('ja-JP', {style:'currency',currency:'JPY',signDisplay:'exceptZero'});
  var metrics = ['exhibition','straight','turn','acceleration','overall'];
  var labels = ['展示','伸び','まわり足','立ち上がり','総評'];
  function el(tag, text) {
    var x = document.createElement(tag);
    if (text !== undefined) x.textContent = text;
    return x;
  }
  function button(text, fn) {
    var b = el('button',text); b.className='premium-action'; b.type='button'; b.onclick=fn; return b;
  }
  function link(text, path) {
    var a=el('a',text); a.href=path; a.className='premium-link'; return a;
  }
  function checkout(action, amount) {
    return async function (ev) {
      var btn=ev.currentTarget; btn.disabled=true;
      try {
        var result=await account.premiumCall(action, {amount:amount});
        var url=new URL(result.url);
        if (url.protocol!=='https:' || !['checkout.stripe.com','billing.stripe.com'].includes(url.hostname)) throw Error('Unknown payment page');
        location.assign(url.href);
      } catch (_) {
        btn.disabled=false;
        var error=box.querySelector('.premium-error') || el('p');
        error.className='premium-error'; error.setAttribute('role','status');
        error.textContent='決済ページを開けませんでした。少し待ってからもう一度お試しください。';
        box.append(error);
      }
    };
  }
  function plan(state) {
    var finished=new URLSearchParams(location.search).get('checkout')==='done';
    box.replaceChildren();
    if (!account.identity()) {
      box.append(el('p','マイノートでログインすると、会員状況を確認できます。'),link('ログインへ','/mynote#note-account'));
    } else if (state?.member) {
      box.append(el('p',state.owner ? 'オーナー権限でプレミアムをご利用中です。' : state.tester ? 'プレミアムの試用中です。' : 'プレミアム会員です。'),link('収支グラフを開く','/mynote#premium-chart'));
    } else if (finished) {
      box.append(el('p','会員状態の反映を確認しています。'),button('会員状態を確認',function(){load();}));
    } else if (!state?.checkout) {
      box.append(el('p','申込の受付は準備中です。'));
    }
    if (state?.checkout && !state.member && state.amount) {
      box.append(el('p','月額'+Number(state.amount).toLocaleString('ja-JP')+'円・自動更新'),button('月額プランを申し込む',checkout('checkout',state.amount)));
    }
    if (state?.testCheckout) box.append(button('テスト決済を開く',checkout('checkout',state.amount)));
    if (state?.manage) box.append(button('支払い方法・解約',checkout('portal')));
  }
  function drawRace(data, reason) {
    if (!data || !data.rows.some(row => Object.keys(row.metrics).length)) {
      var why = reason==='snapshot_late' ? '評価データの更新が遅れています。復旧までしばらくお待ちください。'
        : reason==='new_motors' ? 'モーターが入れ替わったばかりのため、評価はデータがそろうまで保留しています。'
        : 'このレースに対応する評価データはまだありません。';
      box.replaceChildren(el('p',why));
      return;
    }
    var table=el('table'); table.className='premium-table'; table.setAttribute('aria-label','モーター試験評価');
    var header=table.createTHead().insertRow();
    ['号機'].concat(labels).forEach(function (label) {
      var th=el('th'); th.scope='col';
      if(label==='立ち上がり') th.append('立ち',el('wbr'),'上がり');
      else if(label==='まわり足') th.append('まわり',el('wbr'),'足');
      else th.textContent=label;
      header.append(th);
    });
    var body=table.createTBody();
    data.rows.sort((a,b)=>a.frame-b.frame).forEach(function (row) {
      var tr=body.insertRow(), name=el('th');
      name.scope='row';
      name.append(el('strong',row.frame+'艇'),el('small',row.motor ? row.motor+'号' : '—'));
      tr.append(name);
      metrics.forEach(function (metric) {
        var td=tr.insertCell(), score=row.metrics[metric];
        if (!score || !/^[SABCD]$/.test(score.grade)) {
          td.textContent='—'; td.setAttribute('aria-label','評価保留'); return;
        }
        var grade=el('strong',score.grade); grade.dataset.grade=score.grade;
        td.append(grade);
      });
    });
    var date=el('p',data.through.replace(/^(....)(..)(..)$/, '$1/$2/$3')+'時点 · 試験評価');
    date.className='premium-rating-date';
    box.replaceChildren(date,table);
  }
  function plot(canvas, data, period) {
    var width=Math.floor(canvas.getBoundingClientRect().width);
    if(!width) return;
    var height=184, scale=Math.min(window.devicePixelRatio || 1,3);
    canvas.width=width*scale;canvas.height=height*scale;
    var ctx=canvas.getContext('2d');
    if(!ctx) return;
    ctx.scale(scale,scale);
    var colors=getComputedStyle(canvas);
    var muted=colors.getPropertyValue('--ink2'), line=colors.getPropertyValue('--line');
    var peak=Math.max(100,...data.rows.flatMap(row=>[Math.abs(row.net),Math.abs(row.total)]));
    var step=Math.pow(10,Math.floor(Math.log10(peak)));
    var limit=Math.ceil(peak/step)*step;
    var axis=new Intl.NumberFormat('ja-JP',{notation:'compact',maximumFractionDigits:1});
    var tickLabel=value=>axis.format(value)+'円';
    ctx.font='11px sans-serif';
    var right=width-Math.ceil(ctx.measureText(tickLabel(-limit)).width)-10;
    var left=5, top=10, bottom=158, zero=(top+bottom)/2;
    var slot=(right-left)/data.rows.length;
    var x=i=>left+(i+.5)*slot;
    var y=v=>zero-v/limit*(zero-top);
    ctx.textBaseline='middle';
    [limit,0,-limit].forEach(function(v){
      var at=y(v);ctx.strokeStyle=line;ctx.lineWidth=v===0?1.5:1;
      ctx.beginPath();ctx.moveTo(left,at);ctx.lineTo(right,at);ctx.stroke();
      ctx.fillStyle=muted;ctx.fillText(tickLabel(v),right+6,at);
    });
    data.rows.forEach(function(row,i){
      if(row.net) {
        ctx.fillStyle=row.net>0?'#4bb6a8':'#ef8a88';
        var barWidth=Math.max(2,Math.min(slot*.62,16));
        ctx.fillRect(x(i)-barWidth/2,Math.min(zero,y(row.net)),barWidth,Math.abs(y(row.net)-zero));
      }
      var label=period==='week'?'月火水木金土日'[i]:
        period==='month'?(i===0 || (i+1)%10===0?i+1+'日':''):
        (i%3===0 || i===11?i+1+'月':'');
      if(label){
        ctx.fillStyle=muted;ctx.textAlign='center';
        ctx.fillText(label,Math.max(12,x(i)),bottom+15);
      }
    });
    if(data.latest<0) return;
    ctx.strokeStyle='#7bc7ff';ctx.lineWidth=2;ctx.lineJoin='round';
    ctx.beginPath();ctx.moveTo(left,zero);
    data.rows.slice(0,data.latest+1).forEach(function(row,i){ctx.lineTo(x(i),y(row.total));});
    ctx.stroke();
    var last=data.rows[data.latest];
    ctx.fillStyle='#7bc7ff';ctx.beginPath();ctx.arc(x(data.latest),y(last.total),3,0,2*Math.PI);ctx.fill();
  }
  var chartObserver;
  function chart() {
    if (!status?.member || !account.identity()) return;
    if (chartObserver) chartObserver.disconnect();
    if (!account.state().ready) { box.replaceChildren(el('p','収支を読み込んでいます。')); return; }
    var now=dateFormat.format(new Date()).replace(/[^\d]/g,'');
    var period=selected, data=chartData(account.data().bets,period,now,offset);
    var nav=el('div'); nav.className='premium-chart-controls';
    Object.keys(periods).forEach(function (period) {
      var b=button(periods[period],function(){selected=period;offset=0;chart();box.querySelector('[aria-pressed="true"]')?.focus();});
      b.dataset.period=period; b.setAttribute('aria-pressed',String(period===selected)); nav.append(b);
    });
    var start=data.start, year=+start.slice(0,4), month=+start.slice(4,6), day=+start.slice(6);
    var heading=selected==='year'?year+'年':selected==='month'?year+'年'+month+'月':month+'月'+day+'日からの週';
    var range=el('div');range.className='premium-chart-range';
    function shift(text,label,direction) {
      var b=button(text,function(){
        offset+=direction;chart();
        (box.querySelector('[data-shift="'+direction+'"]:not(:disabled)') ||
          box.querySelector('[data-shift]:not(:disabled)'))?.focus();
      });
      b.dataset.shift=direction;b.setAttribute('aria-label',label);b.disabled=direction>0 && offset===0;return b;
    }
    range.append(shift('‹','前の'+periods[selected],-1),el('strong',heading),shift('›','次の'+periods[selected],1));
    var total=el('strong',price.format(data.total));total.dataset.sign=data.total<0?'negative':'positive';
    var headline=el('div');headline.className='premium-chart-total';headline.append(el('span','期間収支'),total);
    var stats=el('div');stats.className='premium-chart-stats';
    var yen=new Intl.NumberFormat('ja-JP',{style:'currency',currency:'JPY'});
    [['購入',yen.format(data.inv)],['払戻',yen.format(data.ret)],['記録',data.count+'件']].forEach(function(item){
      var stat=el('span');stat.append(el('small',item[0]),el('strong',item[1]));stats.append(stat);
    });
    box.replaceChildren(nav,range,headline);
    if(data.count) {
      var canvas=el('canvas');canvas.className='premium-chart-plot';canvas.setAttribute('role','img');
      canvas.setAttribute('aria-label',heading+'の累計収支 '+price.format(data.total)+'。棒は期間内の増減を表示します。');
      var legend=el('p','累計収支');legend.className='premium-chart-legend';
      box.append(canvas,legend);
      plot(canvas,data,period);
      if(typeof ResizeObserver!=='undefined') {
        var width=canvas.clientWidth;
        chartObserver=new ResizeObserver(function(){
          if(canvas.clientWidth!==width){width=canvas.clientWidth;plot(canvas,data,period);}
        });
        chartObserver.observe(canvas);
      }
    } else box.append(el('p','この期間の記録はありません。'));
    box.append(stats);
  }
  async function load() {
    if (root.hasAttribute('data-premium-race') && root.closest('.tabp').hidden) return;
    var id=account.identity();
    if (!id) {
      status=null; box.innerHTML=preview;
      if (root.hasAttribute('data-premium-plan') && account.state().mode !== 'loading') plan(null);
      return;
    }
    if (request?.id === id) return;
    var ticket=++epoch;
    request={id:id,ticket:ticket};
    try {
      var state=await account.premiumCall('status');
      if (ticket!==epoch || id!==account.identity()) return;
      var unchanged = JSON.stringify(state) === JSON.stringify(status);
      status=state;
      if (unchanged && root.hasAttribute('data-premium-plan')) return;
      if (root.hasAttribute('data-premium-plan')) plan(state);
      else if (!state.member) box.innerHTML=preview;
      else if (root.hasAttribute('data-premium-chart')) chart();
      else {
        var ds=root.dataset;
        var result=await account.premiumCall('race',{date:ds.date,venue:ds.venue,race:Number(ds.race)});
        if (ticket===epoch && id===account.identity()) drawRace(result.evaluation, result.reason);
      }
    } catch (_) {
      if (ticket!==epoch) return;
      status=null; box.innerHTML=preview;
      box.append(button('もう一度確認',function(){load();}));
    } finally {
      if (request?.ticket === ticket) request=null;
    }
  }
  function init() {
    if (root.hasAttribute('data-premium-race')) {
      var tab=root.closest('.tabp');
      new MutationObserver(function(){if(!tab.hidden) load();}).observe(tab,{attributes:true,attributeFilter:['hidden']});
    }
    account.subscribe(function(reason) {
      if (reason==='identity') { if(chartObserver) chartObserver.disconnect(); offset=0; ++epoch; request=null; status=null; box.innerHTML=preview; load(); }
      else if (root.hasAttribute('data-premium-chart') && status?.member) chart();
    });
    // Recheck entitlements even when the page stays open after a cancellation or expiry.
    setInterval(function(){if(!document.hidden) load();},60000);
    document.addEventListener('visibilitychange',function(){if(!document.hidden) load();});
    load();
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();
})();
