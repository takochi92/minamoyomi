// 選手・モーター検索（racer/index.html）。表の行はページに入っていて、ここでは絞りこみ・並べ替えだけをする
(function () {
  var ROOT = window.SITE_ROOT || "";
  var PAGE = 100;
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  // ひらがな→カタカナ、半角カナ→全角、空白なし
  function norm(s) {
    s = String(s || "").normalize("NFKC").replace(/[\s　・]/g, "").toLowerCase();
    return s.replace(/[ぁ-ゖ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) + 0x60); });
  }
  var DATA = {};
  try { DATA = JSON.parse(($("sx-data") || {}).textContent || "{}"); } catch (e) { }
  var Fav = window.TeiFav || { all: function () { return {}; }, has: function () { return false; }, bind: function () { }, onChange: function () { }, today: function () { return Promise.resolve({}); }, chips: function () { return ""; } };

  // ---- タブ
  var tabs = document.querySelectorAll(".sx-tabs button");
  function show(k) {
    tabs.forEach(function (b) { b.classList.toggle("on", b.dataset.tab === k); });
    document.querySelectorAll(".tabp.sx").forEach(function (p) { p.hidden = p.dataset.tab !== k; });
    if (k === "m") drawMotors();
    if (k === "f") drawFav();
    var h = { r: "", m: "#motor", f: "#fav" }[k];
    if (history.replaceState) history.replaceState(null, "", location.pathname + location.search + h);
  }
  tabs.forEach(function (b) { b.addEventListener("click", function () { show(b.dataset.tab); }); });

  // ---- 選手：DATA.racers = [登番, 名前, よみ, 支部, 期, 級, 勝率, 女子, 今日[[場, R, 枠]]]
  var tbody = $("sx-rows");
  var V = DATA.venues || {}, SL = DATA.slug || {};
  var RS = (DATA.racers || []).map(function (r, i) {
    return { t: r[0], n: r[1], k: r[2], b: r[3], ki: r[4], c: r[5], w: r[6], l: r[7], tod: r[8] || [], i: i, key: norm(r[1]) + " " + norm(r[2]) + " " + r[0] };
  });
  var byT = {}; RS.forEach(function (r) { byT[r.t] = r; });
  function todChips(r) {
    return r.tod.map(function (x) { return '<a class="chip tg" href="' + ROOT + "race/" + DATA.date + "/" + SL[x[0]] + "-" + x[1] + '.html"><span class="bt b' + x[2] + '">' + x[2] + "</span>" + esc(V[x[0]] || "") + x[1] + "R</a>"; }).join("");
  }
  function rowH(r) {
    return '<tr data-t="' + r.t + '"' + (Fav.has(r.t) ? ' class="is-fav"' : "") + '><td><button type="button" class="fav-btn sm" data-toban="' + r.t + '" data-name="' + esc(r.n) + '">☆</button></td>' +
      '<td><a href="' + r.t + '.html"><b>' + esc(r.n) + '</b></a><span class="sub rk"> ' + r.t + (r.l ? " 女子" : "") + "</span></td><td>" + esc(r.c) + "</td><td>" + esc(r.b) + '</td>' + (DATA.hasKi ? '<td class="r num">' + (r.ki || "-") + "</td>" : "") +
      '<td class="r num">' + (r.w >= 0 ? r.w.toFixed(2) : "-") + '</td><td class="tod">' + todChips(r) + "</td></tr>";
  }
  var shown = PAGE;
  function filtR(reset) {
    if (reset) shown = PAGE;
    var q = norm($("q").value), b = $("fb").value, k = $("fk") ? +$("fk").value : 0, c = $("fc").value, x = $("fx").value, s = $("fs").value;
    var hit = RS.filter(function (r) {
      return (!q || r.key.indexOf(q) >= 0) && (!b || r.b === b) && (!k || r.ki === k) && (!c || r.c === c) &&
        (!x || (x === "l" ? r.l : x === "f" ? Fav.has(r.t) : r.tod.length));
    });
    var key = {
      w: function (r) { return -r.w; },
      k: function (r) { return -r.ki * 1e4 + +r.t; },
      t: function (r) { return +r.t; }
    }[s] || function (r) { return r.i; };
    hit.sort(function (a, z) { return key(a) - key(z); });
    tbody.innerHTML = hit.slice(0, shown).map(rowH).join("") || '<tr><td colspan="7" class="empty">見つかりませんでした。ひらがな・カタカナ・登録番号でもさがせます。</td></tr>';
    Fav.bind(tbody);
    document.querySelector("#sx-r .sx-n").textContent = hit.length.toLocaleString("ja-JP") + "人" + (hit.length > shown ? "（" + shown + "人まで表示）" : "");
    document.querySelector(".sx-more").hidden = hit.length <= shown;
  }
  if (tbody) {
    var t;
    $("q").addEventListener("input", function () { clearTimeout(t); t = setTimeout(function () { filtR(true); }, 150); });
    ["fb", "fk", "fc", "fx", "fs"].forEach(function (id) { var el = $(id); if (el) el.addEventListener("change", function () { filtR(true); }); });
    $("sx-more").addEventListener("click", function () { shown += PAGE * 2; filtR(false); });
    filtR(true);
  }

  // ---- モーター
  var M = DATA.motors || [], HELD = DATA.held || [];
  function pc(v) { return v == null ? "-" : (v * 100).toFixed(1) + "%"; }
  function drawMotors() {
    var body = $("mx-rows"); if (!body) return;
    var v = $("mv").value, s = $("ms").value, mn = +$("mn").value, q = norm($("mq").value);
    var hit = M.filter(function (m) {
      if (v === "held" ? HELD.indexOf(m[0]) < 0 : (v && m[0] !== v)) return false;
      if (m[2] < mn) return false;
      if (q && !(String(m[1]) === q || norm(m[6]).indexOf(q) >= 0 || norm(m[7]).indexOf(q) >= 0)) return false;
      return true;
    });
    var key = {
      "2": function (m) { return -m[3]; }, "3": function (m) { return -m[4]; },
      e: function (m) { return m[5] ? m[5] : 999; }, n: function (m) { return +m[0] * 1000 + m[1]; }
    }[s];
    hit.sort(function (a, b) { return key(a) - key(b) || (+a[0] * 1000 + a[1]) - (+b[0] * 1000 + b[1]); });
    var top = hit.slice(0, 200);
    body.innerHTML = top.length ? top.map(function (m) {
      var href = ROOT + "venue/" + SL[m[0]] + "-motor.html#m" + m[1];
      return "<tr><td>" + esc(V[m[0]] || m[0]) + '</td><td class="r num"><a href="' + href + '"><b>' + m[1] + '</b>号機</a></td><td class="r num' + (m[3] >= 0.4 ? " best" : "") + '">' + pc(m[3]) +
        '</td><td class="r num">' + pc(m[4]) + '</td><td class="r num">' + m[2] + '</td><td class="r num">' + (m[5] || "-") + "</td><td>" + esc(m[6] || "-") + "</td><td>" + (m[7] ? "<b>" + esc(m[7]) + "</b>" : '<span class="sub">-</span>') + "</td></tr>";
    }).join("") : '<tr><td colspan="8" class="empty">' + (M.length ? "条件に合うモーターがありません。" : "モーターのデータを集めているところです。") + "</td></tr>";
    document.querySelector("#sx-m .sx-n").textContent = hit.length.toLocaleString("ja-JP") + "基" + (hit.length > 200 ? "（上位200基を表示）" : "");
  }
  if ($("mx-rows")) {
    ["mv", "ms", "mn"].forEach(function (id) { $(id).addEventListener("change", drawMotors); });
    var mt; $("mq").addEventListener("input", function () { clearTimeout(mt); mt = setTimeout(drawMotors, 150); });
  }

  // ---- お気に入り
  function favCount() {
    var n = Object.keys(Fav.all()).length;
    document.querySelectorAll(".fav-n").forEach(function (el) { el.textContent = n ? " " + n + "人" : ""; });
  }
  function drawFav() {
    var el = $("fav-list"); if (!el) return;
    var F = Fav.all(), ts = Object.keys(F);
    if (!ts.length) { el.innerHTML = '<p class="sub" style="margin:0">まだいません。「選手」のタブや各選手のページで☆を押すと、ここに並びます。出走表では名前の前に★がつきます。</p>'; return; }
    Fav.today().then(function (d) {
      var R = (d && d.racers) || {};
      ts.sort(function (a, b) { return (R[b] ? 1 : 0) - (R[a] ? 1 : 0) || (+a) - (+b); });
      el.innerHTML = '<div class="tbl-wrap"><table class="sx-tbl"><thead><tr><th></th><th>名前</th><th>級</th><th>支部</th><th class="r">勝率</th><th>今日</th></tr></thead><tbody>' + ts.map(function (t) {
        var x = byT[t] || {};
        return '<tr><td><button type="button" class="fav-btn sm" data-toban="' + esc(t) + '" data-name="' + esc(F[t].name) + '">★</button></td><td><a href="' + esc(t) + '.html"><b>' + esc(F[t].name) + '</b></a><span class="sub rk"> ' + esc(t) + "</span></td><td>" + esc(x.c || "") + "</td><td>" + esc(x.b || "") +
          '</td><td class="r num">' + (x.w >= 0 ? x.w.toFixed(2) : "-") + '</td><td class="tod">' + (Fav.chips(R[t]) || '<span class="sub">-</span>') + "</td></tr>";
      }).join("") + "</tbody></table></div><p class=\"sub\">★を押すとお気に入りから外れます。お気に入りはこの端末だけに保存されます。<a href=\"" + ROOT + "mynote.html\">マイノート</a>のバックアップにも入ります。</p>";
      Fav.bind(el);
    });
  }
  Fav.onChange(function () { favCount(); if (!$("sx-f").hidden) drawFav(); else if (tbody) tbody.querySelectorAll("tr[data-t]").forEach(function (tr) { tr.classList.toggle("is-fav", Fav.has(tr.dataset.t)); }); });
  favCount();

  var h = location.hash;
  if (h === "#motor") show("m"); else if (h === "#fav") show("f");
})();
