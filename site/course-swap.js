/* 進入の入れ替え：出走表の下。進入順に艇をタップすると、その選手の「そのコースでの成績」を出す。
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
  // タップした順が内側のコースから入る。まだタップしていない艇は、元の並びのまま後ろにつづく
  function compose(start, picked) {
    return picked.concat(start.filter(function (f) { return picked.indexOf(f) < 0; }));
  }
  if (typeof module !== 'undefined') { module.exports = { stats: stats, rows: rows, initial: initial, compose: compose }; return; }

  document.querySelectorAll('[data-course-swap]').forEach(function (root) {
    var boats;
    try { boats = JSON.parse(root.querySelector('.course-swap-data').textContent); } catch (_) { return; }
    var pick = root.querySelector('.course-swap-pick'), list = root.querySelector('.course-swap-list');
    var reset = root.querySelector('.course-swap-reset'), note = root.querySelector('.course-swap-note');
    var start = initial(boats), picked = [];
    function el(tag, cls, text) { var x = document.createElement(tag); if (cls) x.className = cls; if (text !== undefined) x.textContent = text; return x; }
    function cell(label, value) { var s = el('span', 'cs-v'); s.append(el('small', '', label), el('b', 'num', value)); return s; }
    function draw() {
      var order = compose(start, picked);
      pick.replaceChildren();
      [1, 2, 3, 4, 5, 6].forEach(function (frame) {
        var at = picked.indexOf(frame);
        var b = el('button', 'course-swap-boat bt bt' + frame, String(frame)); b.type = 'button';
        b.setAttribute('aria-pressed', String(at >= 0));
        b.setAttribute('aria-label', frame + '号艇' + (at >= 0 ? '（' + (at + 1) + 'コースに指定ずみ）' : ''));
        if (at >= 0) b.append(el('sup', '', String(at + 1)));
        b.addEventListener('click', function () {
          if (at >= 0) picked = picked.slice(0, at); else picked = picked.concat([frame]);
          draw();
        });
        pick.append(b);
      });
      list.replaceChildren();
      rows(boats, order).forEach(function (r) {
        var row = el('div', 'course-swap-row'); row.setAttribute('role', 'listitem');
        var s = r.stats, head = el('span', 'cs-h');
        head.append(el('span', 'cs-c num', r.course + 'コース'), el('span', 'bt bt' + r.frame, String(r.frame)), el('span', 'cs-n', r.name));
        var vals = el('span', 'cs-s');
        if (s) vals.append(cell('1着', s.win.toFixed(1) + '%'), cell('2連', s.top2.toFixed(1) + '%'), cell('3連', s.top3.toFixed(1) + '%'),
          cell('平均ST', s.st === null ? '—' : s.st.toFixed(2)), cell('出走', s.n + '走'));
        else vals.append(el('span', 'cs-none', 'このコースの成績なし'));
        row.append(head, vals);
        list.append(row);
      });
      var changed = order.join() !== start.join();
      reset.disabled = !picked.length; note.hidden = !changed;
    }
    reset.addEventListener('click', function () { picked = []; draw(); });
    // 開いたときに初めて描く（閉じている間は何もしない）
    var drawn = false;
    root.addEventListener('toggle', function () { if (root.open && !drawn) { drawn = true; draw(); } });
    if (root.open) { drawn = true; draw(); }
  });
})();
