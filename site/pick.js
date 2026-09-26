/* 買い目を選ぶだけで合成オッズと配分が出る（レースページ）
 * オッズはページに載っている締切前のオッズ。ライブオッズが動いていれば、そちらで自動更新する。
 * 推奨買い目があれば最初から選んだ状態にする。
 */
(() => {
  const R = window.__RACE__, box = document.getElementById("pick");
  if (!R || !box) return;
  const COMBOS = [];
  for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) for (let c = 1; c <= 6; c++) if (a !== b && b !== c && a !== c) COMBOS.push(`${a}-${b}-${c}`);
  let odds = R.odds, at = R.odds_at, budget = 1000;
  const sel = new Set(R.bets || []);
  const bt = (n) => `<span class="bt bt${n}">${n}</span>`;
  const f1 = (v) => (v == null ? "-" : v >= 100 ? v.toFixed(0) : v.toFixed(1));
  const yen = (v) => "¥" + Math.round(v).toLocaleString("ja-JP");

  function alloc(list) {           // 100円単位で、どれが当たっても払戻がそろう配分
    const inv = list.map((o) => 1 / o), s = inv.reduce((a, b) => a + b, 0);
    const units = inv.map((x) => Math.max(1, Math.round((budget * x) / s / 100)));
    return units.map((u) => u * 100);
  }

  function render() {
    if (!odds) { box.hidden = true; return; }
    box.hidden = false;
    const chosen = COMBOS.map((c, i) => ({ c, o: odds[i], p: R.p3 ? R.p3[i] : null })).filter((x) => sel.has(x.c) && x.o);
    const s = chosen.reduce((a, x) => a + 1 / x.o, 0), comp = s ? 1 / s : null;
    const al = chosen.length ? alloc(chosen.map((x) => x.o)) : [];
    const tot = al.reduce((a, b) => a + b, 0), minRet = chosen.length ? Math.min(...chosen.map((x, i) => al[i] * x.o)) : 0;
    const mk = chosen.reduce((a, x) => a + 0.75 / x.o, 0);
    const grid = [1, 2, 3, 4, 5, 6].map((a) => `<div class="og"><div class="og-h">${bt(a)} 1着</div>${COMBOS.map((c, i) => [c, i]).filter(([c]) => c[0] == a)
      .map(([c, i]) => `<button type="button" class="og-r pk ${sel.has(c) ? "on" : ""}" data-c="${c}"><span>${c.slice(2)}</span><b class="num">${f1(odds[i])}</b></button>`).join("")}</div>`).join("");
    const rows = chosen.map((x, i) => `<tr><td>${x.c.split("-").map(bt).join("-")}</td><td class="r num">${f1(x.o)}倍</td><td class="r num">${yen(al[i])}</td><td class="r num">${yen(al[i] * x.o)}</td></tr>`).join("");
    box.innerHTML = `<h2>買い目を選んで合成オッズ <small>${at ? at + "時点のオッズ" : ""}・マスを押すと追加／解除</small></h2>
      <div class="tiles"><div class="tile ${comp && comp < 5 ? "warn" : ""}"><small>合成オッズ</small><b>${comp ? comp.toFixed(2) + "倍" : "-"}</b></div>
      <div class="tile"><small>点数</small><b>${chosen.length}点</b></div><div class="tile"><small>的中の目安（オッズから）</small><b>${chosen.length ? Math.round(mk * 100) + "%" : "-"}</b></div>
      <div class="tile"><small>予算</small><b><input id="pk-budget" type="number" step="100" min="100" value="${budget}" inputmode="numeric" style="width:90px"> 円</b></div></div>
      ${rows ? `<div class="tbl-wrap"><table><thead><tr><th>3連単</th><th class="r">オッズ</th><th class="r">配分（計${yen(tot)}）</th><th class="r">当たれば</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="sub">どれが当たっても ${yen(minRet)} 以上。<button type="button" class="btn" id="pk-clear">選択をクリア</button> ${R.bets.length ? '<button type="button" class="btn" id="pk-reco">推奨買い目に戻す</button>' : ""}</p>` : '<p class="sub">下の表から買いたい目を押してください。</p>'}
      <div class="ogrid">${grid}</div>`;
    box.querySelectorAll(".pk").forEach((b) => b.addEventListener("click", () => { const c = b.dataset.c; sel.has(c) ? sel.delete(c) : sel.add(c); render(); }));
    const bi = box.querySelector("#pk-budget");
    if (bi) bi.addEventListener("change", () => { budget = Math.max(100, Math.round((+bi.value || 1000) / 100) * 100); render(); });
    const cl = box.querySelector("#pk-clear"); if (cl) cl.onclick = () => { sel.clear(); render(); };
    const rc = box.querySelector("#pk-reco"); if (rc) rc.onclick = () => { sel.clear(); R.bets.forEach((c) => sel.add(c)); render(); };
  }
  // ライブオッズが届いたら差し替え
  window.addEventListener("liveodds", (e) => { odds = e.detail.o3; at = e.detail.t; render(); });
  render();
})();
