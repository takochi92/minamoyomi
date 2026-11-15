/* 進入の入れ替え：出走表の下。2人をタップでコースを交換し、その選手の「そのコースでの成績」を出す。
   艇の色は枠のまま。AI買い目・バフには触らない。 */
(function () {
  'use strict';
  // c = [出走, 1着, 2着, 3着, ST合計(秒), STの件数]。走っていないコースは空（数字を作らない）
  function stats(c) {
    if (!c || !(c[0] > 0)) return null;
    var pc = function (x) { return Math.round(x / c[0] * 1000) / 10; };
    return { n: c[0], win: pc(c[1]), top2: pc(c[1] + c[2]), top3: pc(c[1] + c[2] + c[3]),
             st: c[5] > 0 ? Math.round(c[4] / c[5] * 100) / 100 : null };
  }
  function rows(boats, order) {
    return order.map(function (frame, i) {
      var b = boats.filter(function (x) { return x.f === frame; })[0];
      return { course: i + 1, frame: frame, name: b.n, stats: stats(b.c[String(i + 1)]) };
    });
  }
  function initial(boats) {
    return boats.slice().sort(function (a, b) { return a.k - b.k; }).map(function (b) { return b.f; });
  }
  if (typeof module !== 'undefined') { module.exports = { stats: stats, rows: rows, initial: initial }; return; }

  document.querySelectorAll('[data-course-swap]').forEach(function (root) {
    var boats;
    try { boats = JSON.parse(root.querySelector('.course-swap-data').textContent); } catch (_) { return; }
    var list = root.querySelector('.course-swap-list'), reset = root.querySelector('.course-swap-reset');
    var note = root.querySelector('.course-swap-note');
    var start = initial(boats), order = start.slice(), picked = null;
    function el(tag, cls, text) { var x = document.createElement(tag); if (cls) x.className = cls; if (text !== undefined) x.textContent = text; return x; }
    function cell(label, value) { var s = el('span', 'cs-v'); s.append(el('small', '', label), el('b', 'num', value)); return s; }
    function draw() {
      list.replaceChildren();
      rows(boats, order).forEach(function (r, i) {
        var b = el('button', 'course-swap-row'); b.type = 'button'; b.setAttribute('role', 'listitem');
        b.setAttribute('aria-pressed', String(picked === i));
        var s = r.stats;
        b.setAttribute('aria-label', r.course + 'コース ' + r.frame + '号艇 ' + r.name + (s ? '。' + s.n + '走、1着率' + s.win + '%' : '。このコースの成績なし'));
        var head = el('span', 'cs-h');
        var tag = el('span', 'bt bt' + r.frame, String(r.frame));
        head.append(el('span', 'cs-c num', r.course + 'コース'), tag, el('span', 'cs-n', r.name));
        var vals = el('span', 'cs-s');
        if (s) vals.append(cell('1着', s.win.toFixed(1) + '%'), cell('2連', s.top2.toFixed(1) + '%'), cell('3連', s.top3.toFixed(1) + '%'),
          cell('平均ST', s.st === null ? '—' : s.st.toFixed(2)), cell('出走', s.n + '走'));
        else vals.append(el('span', 'cs-none sub', 'このコースの成績なし'));
        b.append(head, vals);
        b.addEventListener('click', function () {
          if (picked === null) picked = i;
          else if (picked === i) picked = null;
          else { var t = order[picked]; order[picked] = order[i]; order[i] = t; picked = null; }
          draw();
        });
        list.append(b);
      });
      var changed = order.join() !== start.join();
      reset.disabled = !changed; note.hidden = !changed;
    }
    reset.addEventListener('click', function () { order = start.slice(); picked = null; draw(); });
    // 開いたときに初めて描く（閉じている間は何もしない）
    var drawn = false;
    root.addEventListener('toggle', function () { if (root.open && !drawn) { drawn = true; draw(); } });
    if (root.open) { drawn = true; draw(); }
  });
})();
