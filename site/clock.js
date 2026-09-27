// 締切10分前になったら、そのレースの時刻とレース名を赤くする（5分ごとの更新を待たずにブラウザ側で判定）
(function () {
  function nowJst() { return new Date(Date.now() + (new Date().getTimezoneOffset() + 540) * 60000); }
  function tick() {
    var n = nowJst();
    document.querySelectorAll("[data-dl]").forEach(function (el) {
      var m = /^(\d{4})(\d{2})(\d{2}) (\d{1,2}):(\d{2})$/.exec(el.getAttribute("data-dl") || "");
      if (!m) return;
      var dl = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
      var left = (dl - n) / 60000;
      el.classList.toggle("urgent", left > 0 && left <= 10);
      el.classList.toggle("closed", left <= 0);
    });
  }
  tick(); setInterval(tick, 20000);
})();
