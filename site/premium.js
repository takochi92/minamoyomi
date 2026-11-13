(function () {
  'use strict';
  var periods = {week:'週', month:'月', year:'年'};
  function buckets(bets, period, now) {
    var anchor = new Date(Date.UTC(+now.slice(0,4), +now.slice(4,6)-1, +now.slice(6,8)));
    var rows = new Map();
    for (var offset = (period === 'week' ? 7 : period === 'month' ? 11 : 4); offset >= 0; offset--) {
      var d = new Date(anchor);
      if (period === 'week') d.setUTCDate(d.getUTCDate() - (d.getUTCDay() + 6) % 7 - 7 * offset);
      if (period === 'month') { d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() - offset); }
      if (period === 'year') d.setUTCFullYear(d.getUTCFullYear() - offset, 0, 1);
      var iso = d.toISOString().slice(0,10);
      rows.set(iso.slice(0,period === 'year' ? 4 : period === 'month' ? 7 : 10), {label:iso.slice(0,period === 'year' ? 4 : period === 'month' ? 7 : 10), net:0, count:0});
    }
    for (var b of bets) {
      if (!/^\d{8}$/.test(b.date) || b.date > now) continue;
      var key = b.date.replace(/^(....)(..)(..)$/, '$1-$2-$3');
      var date = new Date(key + 'T00:00:00Z');
      if (!Number.isFinite(+date) || date.toISOString().slice(0,10) !== key) continue;
      if (period === 'week') {
        date.setUTCDate(date.getUTCDate() - (date.getUTCDay()+6)%7);
        key = date.toISOString().slice(0,10);
      } else key = key.slice(0, period === 'month' ? 7 : 4);
      var row = rows.get(key);
      if (row) { row.net += (Number(b.ret)||0) - (Number(b.inv)||0); row.count++; }
    }
    return Array.from(rows.values());
  }
  if (typeof module !== 'undefined') { module.exports = {buckets:buckets}; return; }
  var root = document.querySelector('[data-premium-race], [data-premium-chart], [data-premium-plan]');
  if (!root) return;
  var account = window.TeiNoteAccount, box = root.querySelector('.premium-content');
  var preview = box.innerHTML, selected = 'month', epoch = 0, status, request;
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
  function evaluationNote() {
    var note=el('p','まわり足は今節の選手とモーターの組み合わせを評価。立ち上がりは平和島・福岡の出口側のタイムと通常展示を比べた指数です。総評は通常展示・直線・まわり足がそろった今節の走りを総合した評価です。');
    note.className='premium-evaluation-note';
    return note;
  }
  function drawRace(data) {
    if (!data || !data.rows.some(row => Object.keys(row.metrics).length)) {
      box.replaceChildren(el('p','このレースに対応する評価データはまだありません。'),evaluationNote());
      return;
    }
    var table=el('table'); table.className='premium-table';
    var header=table.createTHead().insertRow();
    ['号機'].concat(labels).forEach(function (label) { var th=el('th',label); th.scope='col'; header.append(th); });
    var body=table.createTBody();
    data.rows.sort((a,b)=>a.frame-b.frame).forEach(function (row) {
      var tr=body.insertRow(), name=tr.insertCell();
      name.append(el('strong',row.frame+'艇'),el('small',row.motor ? row.motor+'号' : '—'));
      metrics.forEach(function (metric) {
        var td=tr.insertCell(), score=row.metrics[metric];
        if (!score || !Number.isFinite(score.venue_delta) || !/^[SABCD]$/.test(score.grade)) { td.textContent='—'; return; }
        var grade=el('strong',score.grade); grade.dataset.grade=score.grade;
        var diff=score.venue_delta;
        var detail=(metric==='acceleration' || metric==='overall') && Number.isInteger(score.index)
          ? (score.index>0?'+':'')+score.index+'pt'
          : (diff>0?'+':'')+diff.toFixed(2)+'秒';
        td.append(grade,el('small',detail),el('small',score.runs+'走'));
      });
    });
    box.replaceChildren(el('p',data.through.replace(/^(....)(..)(..)$/, '$1/$2/$3')+'までの展示から集計・試験評価'),table,
      el('p','秒差は場内の中央値との差。立ち上がり・総評の指数はプラスほど良好。—は評価保留です。'),evaluationNote());
  }
  function chart() {
    if (!status?.member || !account.identity()) return;
    if (!account.state().ready) { box.replaceChildren(el('p','収支を読み込んでいます。')); return; }
    var now=dateFormat.format(new Date()).replace(/[^\d]/g,'');
    var series=buckets(account.data().bets,selected,now);
    var peak=Math.max(1,...series.map(row=>Math.abs(row.net)));
    var nav=el('div'); nav.className='premium-chart-controls';
    Object.keys(periods).forEach(function (period) {
      var b=button(periods[period],function(){selected=period;chart();box.querySelector('[aria-pressed="true"]')?.focus();});
      b.dataset.period=period; b.setAttribute('aria-pressed',String(period===selected)); nav.append(b);
    });
    var list=el('div'); list.className='premium-bars';
    series.forEach(function (row) {
      var line=el('div'), track=el('span'), bar=el('i');
      line.className='premium-bar';track.className='premium-bar-track';track.setAttribute('aria-hidden','true');
      bar.className=row.net<0?'negative':'positive';bar.style.width=100*Math.abs(row.net)/peak+'%';
      track.append(bar);line.append(el('span',row.label),track,el('strong',row.count ? price.format(row.net) : '—'));list.append(line);
    });
    box.replaceChildren(nav,el('p',selected==='week'?'直近8週・月曜始まり':selected==='month'?'直近12か月':'直近5年'),list);
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
        if (ticket===epoch && id===account.identity()) drawRace(result.evaluation);
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
      if (reason==='identity') { ++epoch; request=null; status=null; box.innerHTML=preview; load(); }
      else if (root.hasAttribute('data-premium-chart') && status?.member) chart();
    });
    // Recheck entitlements even when the page stays open after a cancellation or expiry.
    setInterval(function(){if(!document.hidden) load();},60000);
    document.addEventListener('visibilitychange',function(){if(!document.hidden) load();});
    load();
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();
})();
