/* ライブオッズ（レースページ）
 * config.js の liveApi（Cloudflare Worker）から1分ごとに最新オッズを読み、
 * 推奨買い目の合成オッズ・単勝・3連単人気順の「動き」を出す。締切を過ぎたら止まる。
 */
(() => {
  const R = window.__RACE__, box = document.getElementById("live");
  const api = (window.SITE_CONFIG || {}).liveApi;
  if (!R || !box || (!api && !window.__LIVE_DEMO__)) return;
  const COMBOS = [];
  for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) for (let c = 1; c <= 6; c++) if (a !== b && b !== c && a !== c) COMBOS.push(`${a}-${b}-${c}`);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const bt = (n) => `<span class="bt bt${n}">${n}</span>`;
  const combo = (c) => `<span class="combo">${c.split("-").map(bt).join('<span class="sep">-</span>')}</span>`;
  const toMin = (hm) => { const [h, m] = hm.split(":").map(Number); return h * 60 + m; };
  const nowMin = () => { const j = new Date(Date.now() + 9 * 3600e3); return j.getUTCHours() * 60 + j.getUTCMinutes(); };
  const comp = (list) => { const s = list.reduce((a, o) => a + (o ? 1 / o : 0), 0); return s ? 1 / s : null; };
  const f1 = (v) => (v == null ? "-" : v >= 100 ? v.toFixed(0) : v.toFixed(1));

  function chg(now, before) {
    if (now == null || before == null) return '<span class="sub">-</span>';
    const r = now / before - 1;
    if (Math.abs(r) < 0.03) return '<span class="sub">→</span>';
    const cls = r <= -0.15 ? "drop big" : r < 0 ? "drop" : "rise";
    return `<span class="${cls}">${r < 0 ? "↓" : "↑"}${Math.abs(r * 100).toFixed(0)}%</span>`;
  }

  /** 5分前に一番近いスナップ */
  function before(snaps, mins) {
    const last = toMin(snaps[snaps.length - 1].t);
    let best = null;
    for (const s of snaps) if (last - toMin(s.t) >= mins) best = s;
    return best;
  }

  function render(d) {
    const snaps = d.snaps || [];
    if (!snaps.length) {
      box.hidden = false;
      box.innerHTML = `<h2>ライブオッズ <small>締切30分前から1分ごとに更新します</small></h2>`;
      return;
    }
    window.dispatchEvent(new CustomEvent("liveodds", { detail: snaps[snaps.length - 1] }));
    const cur = snaps[snaps.length - 1], b5 = before(snaps, 5) || snaps[0], first = d.first || snaps[0];
    const left = d.left ?? toMin(R.deadline) - nowMin();
    const tf = (cur.tf || []).map((o, i) => `<tr class="${R.targets.includes(i + 1) ? "tg" : ""}"><td>${bt(i + 1)}${R.targets.includes(i + 1) ? ' <span class="chip tg">狙い目</span>' : ""}</td>
      <td class="r num"><b>${f1(o)}</b></td><td class="r num">${chg(o, b5.tf?.[i])}</td><td class="r num">${chg(o, first.tf?.[i])}</td></tr>`).join("");
    let recoH = "";
    if (R.bets.length) {
      const nowC = comp(R.bets.map((c) => cur.o3[COMBOS.indexOf(c)]));
      const b5C = comp(R.bets.map((c) => b5.o3[COMBOS.indexOf(c)]));
      const low = nowC != null && nowC < 5;
      recoH = `<div class="tiles"><div class="tile ${low ? "warn" : ""}"><small>推奨買い目の合成オッズ（今）</small><b>${nowC ? nowC.toFixed(2) : "-"}倍</b></div>
        <div class="tile"><small>5分前</small><b>${b5C ? b5C.toFixed(2) : "-"}倍</b></div></div>
        ${low ? '<p class="warn-t">売れて合成オッズが5倍を割りました。買い目を絞るか、見送りも検討してください。</p>' : ""}`;
    }
    const pop = COMBOS.map((c, i) => ({ c, o: cur.o3[i], b: b5.o3[i] })).filter((x) => x.o).sort((a, b) => a.o - b.o);
    const topRows = pop.slice(0, 15).map((x, i) => `<tr class="${R.bets.includes(x.c) ? "mine" : ""}"><td class="r num sub">${i + 1}</td><td>${combo(x.c)}</td><td class="r num"><b>${f1(x.o)}</b></td><td class="r num sub">${f1(x.b)}</td><td class="r num">${chg(x.o, x.b)}</td></tr>`).join("");
    const drops = pop.filter((x) => x.b && x.o / x.b - 1 <= -0.15 && x.o < 100).slice(0, 5);
    const grid = [1, 2, 3, 4, 5, 6].map((a) => `<div class="og"><div class="og-h">${bt(a)} 1着</div>${COMBOS.map((c, i) => [c, i]).filter(([c]) => c[0] == a)
      .map(([c, i]) => `<div class="og-r ${R.bets.includes(c) ? "mine" : ""}"><span>${c.slice(2)}</span><b class="num">${f1(cur.o3[i])}</b>${chg(cur.o3[i], b5.o3[i])}</div>`).join("")}</div>`).join("");
    box.hidden = false;
    box.innerHTML = `<h2>ライブオッズ <small>${esc(cur.t)}更新・${left > 0 ? `締切まで${left}分` : "締切"}・1分ごと</small></h2>
      ${window.__LIVE_DEMO__ ? '<p class="demo">プレビュー用のデモ：オッズの動きは疑似データです（本番は公式から1分ごとに取得）</p>' : ""}
      ${recoH}
      ${drops.length ? `<div class="drops"><b>5分で急に売れた目</b> ${drops.map((x) => `${combo(x.c)} <span class="num">${f1(x.b)}→${f1(x.o)}</span>`).join("　")}</div>` : ""}
      <div class="two"><div class="tbl-wrap"><table><thead><tr><th>単勝</th><th class="r">今</th><th class="r">5分前比</th><th class="r">${esc(first.t)}比</th></tr></thead><tbody>${tf}</tbody></table></div>
      <div class="tbl-wrap"><table><thead><tr><th class="r">人気</th><th>3連単</th><th class="r">今</th><th class="r">5分前</th><th class="r">動き</th></tr></thead><tbody>${topRows}</tbody></table></div></div>
      <details><summary>3連単 全120通り</summary><div class="ogrid">${grid}</div></details>
      <p class="sub">色つきの行は推奨買い目。↓は売れてオッズが下がった目（15%以上は赤）。データ：BOAT RACE公式。</p>`;
  }

  async function load() {
    if (window.__LIVE_DEMO__) return render(window.__LIVE_DEMO__);
    try {
      const r = await fetch(`${api}/live?race=${R.date}-${R.jcd}-${R.rno}`);
      if (r.ok) render(await r.json());
    } catch (e) { /* 次の回で再試行 */ }
    if (toMin(R.deadline) - nowMin() >= -2) setTimeout(load, 60000);
  }
  load();
})();
