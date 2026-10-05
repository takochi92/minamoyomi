// マイノート：収支表・選手メモ・モーターメモ。この端末のブラウザの中だけに保存（サーバーには送らない）。
(function () {
  var KEY = "teilog_note_v1";
  var ROOT = window.SITE_ROOT || "";

  function load() {
    var d = null;
    try { d = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { d = null; }
    d = d && typeof d === "object" ? d : {};
    d.racer = d.racer || {}; d.motor = d.motor || {}; d.bets = d.bets || []; d.budget = d.budget || 0;
    return d;
  }
  var D = load(), okStore = true;
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(D)); okStore = true; } catch (e) { okStore = false; }
    document.querySelectorAll("[data-store-warn]").forEach(function (el) { el.hidden = okStore; });
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function yen(n) { return (n < 0 ? "-" : "") + "¥" + Math.abs(Math.round(n)).toLocaleString("ja-JP"); }
  function num(v) { var n = parseInt(String(v || "").replace(/[^\d]/g, ""), 10); return isNaN(n) ? 0 : n; }
  function today() { var n = new Date(Date.now() + (new Date().getTimezoneOffset() + 540) * 60000); return n.getFullYear() + ("0" + (n.getMonth() + 1)).slice(-2) + ("0" + n.getDate()).slice(-2); }
  function jd(d) { return d ? (+d.slice(4, 6)) + "/" + (+d.slice(6, 8)) : ""; }
  function debounce(fn, ms) { var t; return function () { var a = arguments, s = this; clearTimeout(t); t = setTimeout(function () { fn.apply(s, a); }, ms); }; }
  var warn = '<p class="sub" data-store-warn hidden style="color:var(--accent)">このブラウザでは保存できませんでした（プライベートモードなど）。</p>';

  function memoBox(kind, key, label, extra) {
    var cur = (kind === "racer" ? D.racer[key] : D.motor[key]) || {};
    return '<label class="nb-memo"><span class="sub">' + esc(label) + '</span><textarea rows="2" data-kind="' + kind + '" data-key="' + esc(key) + '" data-extra="' + esc(JSON.stringify(extra || {})) + '" placeholder="気づいたことを書いておく（例：ターンが流れる、伸びがいい）">' + esc(cur.text || "") + "</textarea></label>";
  }
  function bindMemos(root) {
    root.querySelectorAll("textarea[data-kind]").forEach(function (ta) {
      ta.addEventListener("input", debounce(function () {
        var kind = ta.dataset.kind, key = ta.dataset.key, ex = {};
        try { ex = JSON.parse(ta.dataset.extra || "{}"); } catch (e) { }
        var box = kind === "racer" ? D.racer : D.motor, v = ta.value.trim();
        if (v) { box[key] = Object.assign({}, box[key] || {}, ex, { text: v, t: today() }); } else { delete box[key]; }
        save(); marks();
      }, 400));
    });
  }

  // 出走表の名前の横に「メモ」印
  function marks() {
    document.querySelectorAll("tr[data-toban]").forEach(function (tr) {
      var has = (D.racer[tr.dataset.toban] || {}).text || (D.motor[tr.dataset.motor] || {}).text;
      var cell = tr.children[1], m = cell && cell.querySelector(".nb-mark");
      if (has && cell && !m) { cell.insertAdjacentHTML("beforeend", ' <a class="pill nb-mark" href="#mynote">メモ</a>'); }
      if (!has && m) m.remove();
    });
  }

  function betRow(b, withRace) {
    var pl = (b.ret || 0) - (b.inv || 0);
    return '<tr data-id="' + b.id + '"><td class="num">' + jd(b.date) + "</td>" + (withRace ? "<td>" + esc(b.venue || "") + (b.rno ? " " + b.rno + "R" : "") + "</td>" : "") +
      "<td>" + esc([b.venue ? b.venue + (b.rno ? " " + b.rno + "R" : "") : "", b.memo || ""].filter(Boolean).join(" ")) + '</td><td class="r num">' + yen(b.inv || 0) + '</td><td class="r"><input class="nb-ret num" inputmode="numeric" value="' + (b.ret || "") + '" placeholder="0" aria-label="払戻"></td>' +
      '<td class="r num ' + (pl > 0 ? "plus" : pl < 0 ? "minus" : "") + '">' + yen(pl) + '</td><td class="r"><button class="nb-del" type="button" aria-label="削除">×</button></td></tr>';
  }
  function bindBetRows(root, after) {
    root.querySelectorAll("tr[data-id]").forEach(function (tr) {
      var b = D.bets.filter(function (x) { return x.id === tr.dataset.id; })[0];
      if (!b) return;
      tr.querySelector(".nb-ret").addEventListener("change", function (ev) { b.ret = num(ev.target.value); save(); after(); });
      tr.querySelector(".nb-del").addEventListener("click", function () { D.bets = D.bets.filter(function (x) { return x !== b; }); save(); after(); });
    });
  }
  function addBet(o) { o.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6); D.bets.push(o); save(); }

  // ---- レースページ
  function racePanel(el) {
    var ds = el.dataset;
    function draw() {
      var mine = D.bets.filter(function (b) { return b.date === ds.date && b.jcd === ds.jcd && +b.rno === +ds.rno; });
      var boats = Array.prototype.map.call(document.querySelectorAll("tr[data-toban]"), function (tr) { return tr.dataset; });
      var memo = boats.map(function (b) {
        var mno = (b.motor || "").split("-")[1];
        return '<details class="nb-boat"' + ((D.racer[b.toban] || {}).text ? " open" : "") + '><summary><span class="bt b' + b.frame + '">' + b.frame + "</span> " + esc(b.name) + (mno ? ' <span class="sub">' + mno + "号機</span>" : "") + "</summary>" +
          memoBox("racer", b.toban, "選手メモ（" + b.name + "）", { name: b.name }) +
          ((D.motor[b.motor] || {}).text ? '<p class="sub nb-mref">' + esc(mno) + "号機のメモ：" + esc(D.motor[b.motor].text) + "</p>" : "") + "</details>";
      }).join("");
      el.innerHTML = '<h2>選手メモ <small>この端末だけに保存・<a href="' + ROOT + 'mynote.html">マイノートへ</a></small></h2>' + warn +
        (memo ? memo + '<p class="sub" style="margin:0">モーターのメモは<a href="' + ROOT + 'motor.html">モーター一覧</a>で書けます。</p>' : "");
      bindMemos(el); marks();
    }
    el.hidden = false; draw();
  }

  // ---- 選手ページ
  function racerPanel(el) {
    el.innerHTML = '<h2>選手メモ <small>この端末だけに保存・<a href="' + ROOT + 'mynote.html">一覧へ</a></small></h2>' + warn + memoBox("racer", el.dataset.toban, "", { name: el.dataset.name });
    el.hidden = false; bindMemos(el);
  }

  // ---- マイノート（一覧）
  function notePage(el) {
    var venues = {};
    try { venues = JSON.parse(el.dataset.venues || "{}"); } catch (e) { }
    function sum(list) { var i = 0, r = 0; list.forEach(function (b) { i += b.inv || 0; r += b.ret || 0; }); return { inv: i, ret: r, pl: r - i, roi: i ? r / i : null, n: list.length }; }
    function tiles(s, label) {
      return '<div class="nb-tiles"><div><small>' + label + '購入</small><b class="num">' + yen(s.inv) + '</b></div><div><small>払戻</small><b class="num">' + yen(s.ret) + '</b></div><div><small>収支</small><b class="num ' + (s.pl > 0 ? "plus" : s.pl < 0 ? "minus" : "") + '">' + yen(s.pl) + '</b></div><div><small>回収率</small><b class="num">' + (s.roi == null ? "-" : Math.round(s.roi * 100) + "%") + "</b></div></div>";
    }
    var curYm = today().slice(0, 6), sel = "";
    var slugs = {};
    try { slugs = JSON.parse(el.dataset.slugs || "{}"); } catch (e) { }
    function shiftYm(ym, k) { var y = +ym.slice(0, 4), m = +ym.slice(4) - 1 + k; y += Math.floor(m / 12); m = ((m % 12) + 12) % 12; return y + ("0" + (m + 1)).slice(-2); }
    function short(n) { var a = Math.abs(n); return (n > 0 ? "+" : n < 0 ? "-" : "") + (a >= 10000 ? (a / 10000).toFixed(a >= 100000 ? 0 : 1) + "万" : a.toLocaleString("ja-JP")); }
    function calendar(ym, bets) {
      var y = +ym.slice(0, 4), m = +ym.slice(4), first = new Date(y, m - 1, 1).getDay(), days = new Date(y, m, 0).getDate();
      var byD = {};
      bets.forEach(function (b) { if ((b.date || "").slice(0, 6) === ym) (byD[b.date] = byD[b.date] || []).push(b); });
      var h = ["日", "月", "火", "水", "木", "金", "土"].map(function (w, i) { return '<div class="cal-h' + (i === 0 ? " sun" : i === 6 ? " sat" : "") + '">' + w + "</div>"; }).join("");
      for (var i = 0; i < first; i++) h += '<div class="cal-d empty"></div>';
      var td = today();
      for (var d = 1; d <= days; d++) {
        var key = ym + ("0" + d).slice(-2), L = byD[key], s = L ? sum(L) : null;
        h += '<button type="button" class="cal-d' + (key === sel ? " on" : "") + (key === td ? " today" : "") + (s ? (s.pl > 0 ? " win" : s.pl < 0 ? " lose" : " even") : "") + '" data-day="' + key + '"><span class="cal-n">' + d + "</span>" +
          (s ? '<span class="cal-v num">' + short(s.pl) + "</span>" : "") + "</button>";
      }
      return '<div class="cal">' + h + "</div>";
    }
    function draw() {
      var ym = curYm, thisYm = today().slice(0, 6);
      var bets = D.bets.slice().sort(function (a, b) { return (b.date + ("0" + (b.rno || 0)).slice(-2)).localeCompare(a.date + ("0" + (a.rno || 0)).slice(-2)); });
      var month = bets.filter(function (b) { return (b.date || "").slice(0, 6) === ym; });
      var sm = sum(month), sa = sum(bets);
      var bud = "";
      if (D.budget && ym === thisYm) {
        var left = D.budget - sm.inv;
        bud = '<p class="' + (left < 0 ? "nb-over" : "sub") + '" style="margin:0">今月の予算 ' + yen(D.budget) + "：" + (left >= 0 ? "残り " + yen(left) : yen(-left) + " オーバーしています。今月はここまでにしましょう。") + "</p>";
      }
      var byM = {};
      bets.forEach(function (b) { var k = (b.date || "").slice(0, 6); (byM[k] = byM[k] || []).push(b); });
      var mrows = Object.keys(byM).sort().reverse().map(function (k) { var s = sum(byM[k]); return "<tr><td>" + (+k.slice(0, 4)) + "年" + (+k.slice(4)) + '月</td><td class="r num">' + s.n + '</td><td class="r num">' + yen(s.inv) + '</td><td class="r num">' + yen(s.ret) + '</td><td class="r num ' + (s.pl > 0 ? "plus" : s.pl < 0 ? "minus" : "") + '">' + yen(s.pl) + '</td><td class="r num">' + (s.roi == null ? "-" : Math.round(s.roi * 100) + "%") + "</td></tr>"; }).join("");
      var rm = Object.keys(D.racer).map(function (t) { var m = D.racer[t]; return '<li><a href="' + ROOT + "racer/" + esc(t) + '.html">' + esc(m.name || t) + '</a> <span class="sub">' + jd(m.t) + "</span><br>" + esc(m.text) + "</li>"; }).join("");
      var mm = Object.keys(D.motor).sort().map(function (k) { var m = D.motor[k], j = m.jcd || k.split("-")[0], no = m.no || k.split("-")[1]; var nm = esc(m.venue || "") + " " + esc(no) + "号機"; return "<li><b>" + (slugs[j] ? '<a href="' + ROOT + "venue/" + slugs[j] + "-motor.html#m" + esc(no) + '">' + nm + "</a>" : nm) + '</b> <span class="sub">' + jd(m.t) + "</span><br>" + esc(m.text) + "</li>"; }).join("");
      var vopt = Object.keys(venues).sort().map(function (j) { return '<option value="' + j + '">' + esc(venues[j]) + "</option>"; }).join("");
      var list = sel ? bets.filter(function (b) { return b.date === sel; }) : month;
      var listTitle = sel ? jd(sel) + "の記録" : (+ym.slice(4)) + "月の記録";
      var dflt = (sel || (ym === thisYm ? today() : ym + "01")).replace(/(\d{4})(\d{2})(\d{2})/, "$1-$2-$3");
      el.innerHTML = warn +
        '<section class="panel" style="display:grid;gap:10px"><div class="cal-nav"><button type="button" class="cal-prev" aria-label="前の月">‹</button><h2>' + (+ym.slice(0, 4)) + "年" + (+ym.slice(4)) + '月の収支</h2><button type="button" class="cal-next" aria-label="次の月">›</button></div>' +
        tiles(sm, "") + bud + calendar(ym, bets) +
        '<h3 class="sub" style="margin:4px 0 0">' + listTitle + (sel ? ' <button type="button" class="cal-all">月の全部を見る</button>' : "") + "</h3>" +
        (list.length ? '<div class="tbl-wrap"><table class="nb-tbl"><thead><tr><th>日</th><th>メモ</th><th class="r">購入</th><th class="r">払戻</th><th class="r">収支</th><th></th></tr></thead><tbody>' + list.map(function (b) { return betRow(b, false); }).join("") + "</tbody></table></div>" : '<p class="sub" style="margin:0">記録はありません。下の欄に、その日の購入と払戻の合計を入れてください（1日1行で十分です）。</p>') +
        '<div class="nb-add"><input type="date" class="nb-date" value="' + dflt + '"><input class="nb-inv num" inputmode="numeric" placeholder="購入額"><input class="nb-ret-in num" inputmode="numeric" placeholder="払戻"><input class="nb-memo-in" placeholder="メモ（任意：びわこ・大村など）"><button type="button" class="nb-go">記録</button></div>' +
        '<details><summary class="sub">全期間・月別を見る</summary>' + tiles(sa, "全期間の") + (mrows ? '<div class="tbl-wrap"><table><thead><tr><th>月</th><th class="r">件数</th><th class="r">購入</th><th class="r">払戻</th><th class="r">収支</th><th class="r">回収率</th></tr></thead><tbody>' + mrows + "</tbody></table></div>" : "") + "</details>" +
        '<p class="sub" style="margin:0">月の予算：<input class="nb-bud num" inputmode="numeric" value="' + (D.budget || "") + '" placeholder="例：10000" style="width:8em"> 円（決めておくと、超えたときに知らせます）</p></section>' +
        '<section class="panel"><h2>選手メモ <small>' + Object.keys(D.racer).length + "人</small></h2>" + (rm ? '<ul class="comments">' + rm + "</ul>" : '<p class="sub">各選手のページ、またはレースページの「マイノート」から書けます。</p>') + "</section>" +
        '<section class="panel"><h2>モーターメモ <small>' + Object.keys(D.motor).length + '基・<a href="' + ROOT + 'motor.html">モーター一覧へ</a></small></h2>' + (mm ? '<ul class="comments">' + mm + "</ul>" : '<p class="sub"><a href="' + ROOT + 'motor.html">モーター一覧</a>で場を選んで、各モーターの欄に書けます。モーターは入れ替わると別物なので、古いメモは消してください。</p>') + "</section>" +
        '<section class="panel" style="display:grid;gap:8px"><h2>バックアップ</h2><p class="sub" style="margin:0">記録はこの端末のブラウザの中だけにあります。機種変更やブラウザのデータ削除で消えるので、ときどきファイルに保存してください。別の端末へは、保存したファイルを読み込むと移せます。</p>' +
        '<div class="nb-add"><button type="button" class="nb-exp">ファイルに保存</button><label class="nb-imp-l">ファイルから読み込む<input type="file" class="nb-imp" accept="application/json,.json" hidden></label></div></section>';

      el.querySelector(".nb-go").addEventListener("click", function () {
        var inv = num(el.querySelector(".nb-inv").value);
        if (!inv) { el.querySelector(".nb-inv").focus(); return; }
        addBet({ date: (el.querySelector(".nb-date").value || "").replace(/-/g, "") || today(), memo: el.querySelector(".nb-memo-in").value.trim(), inv: inv, ret: num(el.querySelector(".nb-ret-in").value) });
        draw();
      });
      el.querySelector(".cal-prev").addEventListener("click", function () { curYm = shiftYm(curYm, -1); sel = ""; draw(); });
      el.querySelector(".cal-next").addEventListener("click", function () { curYm = shiftYm(curYm, 1); sel = ""; draw(); });
      el.querySelectorAll(".cal-d[data-day]").forEach(function (b) { b.addEventListener("click", function () { sel = sel === b.dataset.day ? "" : b.dataset.day; draw(); }); });
      var all = el.querySelector(".cal-all"); if (all) all.addEventListener("click", function () { sel = ""; draw(); });
      el.querySelector(".nb-bud").addEventListener("change", function (ev) { D.budget = num(ev.target.value); save(); draw(); });
      el.querySelector(".nb-exp").addEventListener("click", function () {
        var blob = new Blob([JSON.stringify(D, null, 1)], { type: "application/json" });
        var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "teilog-note-" + today() + ".json";
        document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
      });
      el.querySelector(".nb-imp").addEventListener("change", function (ev) {
        var f = ev.target.files && ev.target.files[0]; if (!f) return;
        f.text().then(function (t) {
          var x = JSON.parse(t);
          if (!x || typeof x !== "object") return;
          var ids = {}; D.bets.forEach(function (b) { ids[b.id] = 1; });
          (x.bets || []).forEach(function (b) { if (b && !ids[b.id]) D.bets.push(b); });
          Object.assign(D.racer, x.racer || {}); Object.assign(D.motor, x.motor || {});
          if (x.budget && !D.budget) D.budget = x.budget;
          save(); draw();
        }).catch(function () { });
      });
      bindBetRows(el, draw);
    }
    draw();
  }

  function slots() {
    document.querySelectorAll(".nb-slot").forEach(function (el) {
      var ex = {};
      try { ex = JSON.parse(el.dataset.extra || "{}"); } catch (e) { }
      el.innerHTML = memoBox(el.dataset.kind, el.dataset.key, el.dataset.label || "", ex);
      bindMemos(el);
    });
  }
  function motorMarks() {
    document.querySelectorAll(".nb-mark-m").forEach(function (el) {
      el.innerHTML = (D.motor[el.dataset.mkey] || {}).text ? '<span class="pill nb-mark">メモ</span>' : "";
    });
  }

  function init() {
    slots(); motorMarks();
    document.addEventListener("input", debounce(motorMarks, 500));
    document.querySelectorAll("#mynote[data-rno]").forEach(racePanel);
    document.querySelectorAll("#racer-memo").forEach(racerPanel);
    document.querySelectorAll("#note-app").forEach(notePage);
    marks();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
