// 締切10分前になったら、そのレースの時刻とレース名を赤くする（5分ごとの更新を待たずにブラウザ側で判定）
// 開催場のタイルは、締切を過ぎたら次のレースへ進める。「締切が近いレース」は締切を過ぎたものを外す。
(function () {
  function nowJst() { return new Date(Date.now() + (new Date().getTimezoneOffset() + 540) * 60000); }
  function at(date, hm) {
    var m = /^(\d{4})(\d{2})(\d{2})$/.exec(date || ""), t = /^(\d{1,2}):(\d{2})$/.exec(hm || "");
    return m && t ? new Date(+m[1], +m[2] - 1, +m[3], +t[1], +t[2]) : null;
  }
  function tick() {
    var n = nowJst();
    document.querySelectorAll("[data-next]").forEach(function (el) {
      var date = (el.getAttribute("data-dl") || "").split(" ")[0];
      var list = (el.getAttribute("data-next") || "").split(",").filter(Boolean).map(function (x) { var p = x.split("@"); return { r: p[0], hm: p[1] }; });
      var nx = list.filter(function (x) { var d = at(date, x.hm); return d && d > n; })[0];
      if (!nx) {
        el.textContent = "本日終了";
        el.removeAttribute("data-dl");
        var a = el.closest(".vt"); if (a) a.classList.add("done");
        return;
      }
      if (el.getAttribute("data-dl") !== date + " " + nx.hm) {
        el.setAttribute("data-dl", date + " " + nx.hm);
        el.innerHTML = nx.r + 'R <span class="num">' + nx.hm + "</span>";
      }
    });
    document.querySelectorAll("[data-dl]").forEach(function (el) {
      var m = /^(\d{4})(\d{2})(\d{2}) (\d{1,2}):(\d{2})$/.exec(el.getAttribute("data-dl") || "");
      if (!m) return;
      var dl = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
      var left = (dl - n) / 60000;
      el.classList.toggle("urgent", left > 0 && left <= 10);
      el.classList.toggle("closed", left <= 0);
    });
    var shown = 0;
    document.querySelectorAll("[data-soon]").forEach(function (el) {
      var hide = el.classList.contains("closed") || shown >= 4;
      el.hidden = hide;
      if (!hide) shown++;
    });
  }
  tick(); setInterval(tick, 20000);
})();
