/* 水面ヨミ フロントエンド（依存ライブラリなし）
 * データは data/ 以下の JSON（GitHub Actions が 5 分おきに更新）を読むだけ。
 * プレビュー用に window.__DEMO__ があればそれを使う。
 */
(() => {
  const CFG = window.SITE_CONFIG || {};
  const $ = (s, el = document) => el.querySelector(s);
  const app = $("#app");
  const cache = {};

  async function load(path) {
    if (window.__DEMO__) return window.__DEMO__[path] ?? null;
    try {
      const r = await fetch(`${window.SITE_ROOT || ""}data/${path}?t=${Math.floor(Date.now() / 60000)}`);
      if (!r.ok) return null;
      return await r.json();
    } catch { return null; }
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const bt = (n) => `<span class="bt bt${n}">${n}</span>`;
  const combo = (c) => `<span class="combo">${c.split("-").map(bt).join('<span class="sep">-</span>')}</span>`;
  const pct = (v, d = 0) => (v == null ? "-" : (v * 100).toFixed(d) + "%");
  const yen = (v) => (v == null ? "-" : "¥" + Number(v).toLocaleString("ja-JP"));
  const lvClass = (lv) => `lv${lv || 2}`;

  function deadlineMs(date, hhmm) {
    const [h, m] = hhmm.split(":").map(Number);
    return Date.UTC(+date.slice(0, 4), +date.slice(4, 6) - 1, +date.slice(6, 8), h - 9, m);
  }
  function now() { return window.__DEMO__?.now ?? Date.now(); }
  function countdown(date, hhmm) {
    const diff = Math.round((deadlineMs(date, hhmm) - now()) / 60000);
    if (diff < 0) return `<span class="cd past">締切済</span>`;
    if (diff >= 60) return `<span class="cd">${Math.floor(diff / 60)}時間${diff % 60}分</span>`;
    return `<span class="cd">あと${diff}分</span>`;
  }
  function raceState(r) {
    if (r.result) return r.hit ? "hit" : "miss";
    if (r.stage === "直前") return "live";
    if (r.stage === "事前") return "pre";
    return "";
  }
  function setNav(key) {
    document.querySelectorAll(".nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.k === key ? "page" : "false"));
  }
  function ad(slot) { return `<div class="ad-slot">${(CFG.ads || {})[slot] || ""}</div>`; }
  function fmtDate(d) { return `${+d.slice(4, 6)}月${+d.slice(6, 8)}日`; }

  // ------------------------------------------------------------ トップ
  async function viewHome() {
    setNav("home");
    const idx = await load("index.json");
    if (!idx) { app.innerHTML = `<p class="empty">本日のデータを準備中です。</p>`; return; }
    cache.idx = idx;
    const upcoming = [];
    for (const v of idx.venues) for (const r of v.races) {
      const t = deadlineMs(idx.date, r.deadline);
      if (t > now()) upcoming.push({ v, r, t });
    }
    upcoming.sort((a, b) => a.t - b.t);
    const soon = upcoming.slice(0, 6).map(({ v, r }) => `
      <a href="#/r/${v.jcd}/${r.rno}">
        <div class="row"><strong>${esc(v.name)} ${r.rno}R</strong>${countdown(idx.date, r.deadline)}</div>
        <div class="row"><span class="sub num">締切 ${r.deadline}</span>${r.confidence ? `<span class="pill ${lvClass(r.level)}">${esc(r.confidence)}</span>` : `<span class="sub">予想準備中</span>`}</div>
        ${r.honmei ? `<div class="row">${combo(r.honmei[0])}<span class="sub">${r.stage === "直前" ? "展示反映済" : "展示前"}</span></div>` : ""}
      </a>`).join("");

    const recos = [];
    let gachi = 0, checked = 0;
    for (const v of idx.venues) for (const r of v.races) if (r.reco) {
      checked++;
      if (r.reco.verdict === "購入非推奨") gachi++;
      else if (r.reco.verdict === "自信あり") recos.push({ v, r, t: deadlineMs(idx.date, r.deadline) });
    }
    recos.sort((a, b) => a.t - b.t);
    const valueHtml = recos.map(({ v, r }) => `
      <a href="#/r/${v.jcd}/${r.rno}">
        <div class="row"><strong>${esc(v.name)} ${r.rno}R</strong>${r.result ? `<span class="pill ${r.reco.hit ? "hit" : "miss"}">${r.reco.hit ? "的中 " + yen(r.payout) : "不的中"}</span>` : countdown(idx.date, r.deadline)}</div>
        <div class="row">${combo(r.reco.top)}<span class="sub">ほか${r.reco.n - 1}点</span></div>
        <div class="row"><span class="num">合成 ${r.reco.comp}倍</span><span class="sub">見込み ${pct(r.reco.market_hit)}</span></div>
      </a>`).join("");

    const specs = [];
    for (const v of idx.venues) for (const r of v.races) if (r.spec) specs.push({ v, r, t: deadlineMs(idx.date, r.deadline) });
    specs.sort((a, b) => a.t - b.t);
    const specHtml = specs.map(({ v, r }) => `<a href="#/r/${v.jcd}/${r.rno}">
        <div class="row"><strong>${esc(v.name)} ${r.rno}R</strong>${r.result ? `<span class="pill ${r.spec_hit ? "hit" : "miss"}">${r.spec_hit ? "的中" : "着外"}</span>` : countdown(idx.date, r.deadline)}</div>
        <div class="row">${r.spec.map((x) => `${bt(x.frame)} <span class="sub">${x.course}コース</span>`).join(" ")}</div></a>`).join("");

    const venues = idx.venues.map((v) => {
      const next = v.races.find((r) => deadlineMs(idx.date, r.deadline) > now());
      const hits = v.races.filter((r) => r.hit).length, done = v.races.filter((r) => r.result).length;
      return `<a class="venue" href="#/v/${v.jcd}">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
          <span class="nm">${esc(v.name)}</span><span class="pill grade ${esc(v.grade)}">${esc(v.grade)}</span></div>
        <div class="meta">${v.timezone ? `<span>${esc(v.timezone)}</span>·` : ""}<span>${esc(v.day)}</span></div>
        <div class="sub" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(v.title)}</div>
        <div class="dots" aria-label="レース進行">${v.races.map((r) => `<span class="${raceState(r)}" title="${r.rno}R"></span>`).join("")}</div>
        <div class="meta"><span>${v.cancelled ? "中止" : next ? `次 ${next.rno}R ${next.deadline}` : "本日終了"}</span>${done ? `<span>· 的中 ${hits}/${done}</span>` : ""}</div>
      </a>`;
    }).join("");

    app.innerHTML = `
      <section style="display:grid;gap:6px">
        <span class="eyebrow">${fmtDate(idx.date)}のボートレース</span>
        <h1>合成オッズ5倍以上で組む、全場の推奨買い目</h1>
        <p class="sub">最終更新 ${esc(idx.updated_at?.slice(11) || "")}　AIの着順予想を締切前のオッズと突き合わせ、合成オッズが5倍を割らない買い目だけで組みます。本命が売れすぎているレースは「購入非推奨」です。</p>
      </section>
      <section style="display:grid;gap:10px"><h2>自信ありレース <small>合成オッズ5倍以上で組めて、AIの見込みが高いレース</small></h2>
        <div class="soon">${valueHtml || `<p class="empty">${checked ? "該当レースはまだありません。" : "締切35分前からオッズを見て判定します。"}</p>`}</div>
        ${checked ? `<p class="sub">判定済み ${checked}レース：自信あり ${recos.length}・購入非推奨（ガチガチ） ${gachi}・残りは通常の推奨</p>` : ""}</section>
      ${specs.length ? `<section style="display:grid;gap:10px"><h2>注目：B級のコース巧者 <small>検証中・単勝で追跡</small></h2><div class="soon">${specHtml}</div></section>` : ""}
      <section style="display:grid;gap:10px"><h2>まもなく締切 <small>展示が出るとすぐ予想を更新</small></h2>
        <div class="soon">${soon || `<p class="empty">本日のレースは終了しました。</p>`}</div></section>
      ${ad("home_mid")}
      <section style="display:grid;gap:10px"><h2>本日の開催場 <small>${idx.venues.length}場</small></h2>
        <div class="venues">${venues}</div>
        <p class="sub"><span class="bt" style="width:10px;height:8px;background:var(--water2);border:0"></span> 事前予想　<span class="bt" style="width:10px;height:8px;background:var(--ink);border:0"></span> 直前予想　<span class="bt" style="width:10px;height:8px;background:var(--accent);border:0"></span> 的中</p>
      </section>`;
  }

  // ------------------------------------------------------------ 場
  async function viewVenue(jcd) {
    setNav("");
    const idx = cache.idx || (cache.idx = await load("index.json"));
    const venues = await load("venues.json");
    const v = idx?.venues.find((x) => x.jcd === jcd);
    if (!v) { app.innerHTML = `<p class="empty">この場は本日開催がありません。</p>`; return; }
    const info = venues?.venues?.[jcd];
    const max = info ? Math.max(...info.courses.map((c) => c.win)) : 1;
    const rows = v.races.map((r) => `<tr class="link" data-href="#/r/${jcd}/${r.rno}">
      <td><strong>${r.rno}R</strong></td><td class="num">${r.deadline}</td>
      <td>${r.confidence ? `<span class="pill ${lvClass(r.level)}">${esc(r.confidence)}</span>` : `<span class="sub">-</span>`}</td>
      <td>${r.honmei ? combo(r.honmei[0]) : ""}</td>
      <td>${r.result ? combo(r.result) : countdown(idx.date, r.deadline)}</td>
      <td class="r num">${r.result ? yen(r.payout) : ""}</td>
      <td>${r.reco ? (r.reco.verdict === "購入非推奨" ? `<span class="sub">購入非推奨</span>` : `<span class="pill ${r.reco.hit === undefined ? (r.reco.verdict === "自信あり" ? "lv4" : "") : (r.reco.hit ? "hit" : "miss")}">${r.reco.verdict} ${r.reco.n}点・合成${r.reco.comp}倍</span>`) : ""}</td></tr>`).join("");
    app.innerHTML = `
      <a class="back" href="#/">← 本日の開催一覧</a>
      <section class="race-head"><div><span class="eyebrow">${esc(v.grade)} · ${esc(v.day)}</span><h1>${esc(v.name)}</h1><p class="sub">${esc(v.title)}</p></div></section>
      <section class="panel" style="display:grid;gap:12px">
        <h2>水面の特性 <small>${info ? `${esc(info.water)}${info.tide ? "・干満差あり" : ""}` : ""}</small></h2>
        ${info ? `<div class="courses">${info.courses.map((c) => `<div><small>${c.win.toFixed(1)}%</small><i style="height:${(c.win / max) * 80}%"></i>${bt(c.course)}</div>`).join("")}</div>
        <p class="sub">コース別1着率（${esc(venues.period)}）${info.note ? "　" + esc(info.note) : ""}</p>` : ""}
      </section>
      <section style="display:grid;gap:10px"><h2>レース一覧</h2>
        <div class="panel tbl-wrap" style="padding:4px 8px"><table><thead><tr><th>R</th><th>締切</th><th>信頼度</th><th>本線</th><th>結果</th><th class="r">3連単</th><th>推奨買い目</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
    app.querySelectorAll("tr.link").forEach((tr) => tr.addEventListener("click", () => (location.hash = tr.dataset.href)));
  }

  // ------------------------------------------------------------ レース
  function waterSvg(wind, weather) {
    const deg = wind?.arrow_deg;
    const arrow = deg == null ? `<text x="150" y="86" text-anchor="middle" font-size="14" fill="var(--ink2)">無風</text>`
      : `<g transform="translate(150 78) rotate(${deg})"><path d="M0 -30 L12 -8 L4 -8 L4 30 L-4 30 L-4 -8 L-12 -8 Z" fill="var(--accent)"/></g>`;
    return `<svg viewBox="0 0 300 190" role="img" aria-label="水面図と風向き">
      <rect x="0" y="0" width="300" height="160" rx="10" fill="var(--water)"/>
      <path d="M50 118 H250" stroke="var(--water2)" stroke-width="2" stroke-dasharray="6 5"/>
      <path d="M50 42 H250" stroke="var(--water2)" stroke-width="2" stroke-dasharray="6 5"/>
      <polygon points="42,88 52,70 62,88" fill="var(--bad)"/><text x="52" y="104" text-anchor="middle" font-size="10" fill="var(--ink2)">2マーク</text>
      <polygon points="238,88 248,70 258,88" fill="var(--bad)"/><text x="248" y="104" text-anchor="middle" font-size="10" fill="var(--ink2)">1マーク</text>
      <path d="M90 132 H210" stroke="var(--ink2)" stroke-width="1.5" marker-end="url(#ah)"/>
      <defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="var(--ink2)"/></marker></defs>
      <text x="150" y="150" text-anchor="middle" font-size="9" fill="var(--ink2)">スタート方向</text>
      ${arrow}
      <rect x="0" y="166" width="300" height="24" rx="6" fill="var(--surface2)"/>
      <text x="150" y="182" text-anchor="middle" font-size="11" fill="var(--ink2)">スタンド</text>
    </svg>`;
  }

  async function viewRace(jcd, rno) {
    setNav("");
    const idx = cache.idx || (cache.idx = await load("index.json"));
    const date = idx?.date;
    const race = date ? await load(`races/${date}/${jcd}${String(rno).padStart(2, "0")}.json`) : null;
    const v = idx?.venues.find((x) => x.jcd === jcd);
    const summary = v?.races.find((r) => r.rno === +rno);
    const head = `<a class="back" href="#/v/${jcd}">← ${esc(v?.name || "")}のレース一覧</a>
      <section class="race-head"><div><span class="eyebrow">${esc(v?.name || "")} · ${date ? fmtDate(date) : ""}</span>
      <h1>${esc(v?.name || "")} ${rno}R <span class="sub num" style="font-size:14px">締切 ${esc(summary?.deadline || race?.deadline || "")}</span></h1>
      <p class="sub">${esc(race?.race_name || "")}</p></div>
      <div>${summary ? countdown(date, summary.deadline) : ""}</div></section>`;
    if (!race || !race.prediction) {
      app.innerHTML = head + `<section class="panel"><p class="empty">予想は締切の約2時間前に出走表から作成し、展示が終わると直前予想に更新します。</p></section>`;
      return;
    }
    const p = race.prediction, rl = race.racelist, bi = race.before || {};
    const bmap = Object.fromEntries((rl.boats || []).map((b) => [b.frame, b]));
    const w = bi.weather || {};
    const res = race.result?.finished ? race.result : null;
    const bought = new Set([...p.bets.main, ...p.bets.sub].map((b) => b.combo));
    const maxWin = Math.max(...p.boats.map((b) => b.p_win));
    const exTimes = p.boats.map((b) => b.exhibit_time).filter(Boolean);
    const bestEx = exTimes.length ? Math.min(...exTimes) : null;
    const rows = p.boats.map((b) => {
      const r = bmap[b.frame] || {};
      return `<tr>
        <td><span class="mark">${p.marks[b.frame] || ""}</span></td>
        <td>${bt(b.frame)}</td>
        <td><strong>${esc(b.name)}</strong> <span class="sub">${esc(b.class)} ${esc(r.branch || "")}</span>${r.f ? ` <span class="pill lv1">F${r.f}</span>` : ""}</td>
        <td class="r num">${b.course}</td>
        <td class="r num">${r.nat_win?.toFixed(2) ?? "-"}</td>
        <td class="r num">${r.loc_win ? r.loc_win.toFixed(2) : "-"}</td>
        <td class="r num">${r.motor_2?.toFixed(1) ?? "-"}</td>
        <td class="r num ${b.exhibit_time && b.exhibit_time === bestEx ? "best" : ""}">${b.exhibit_time?.toFixed(2) ?? "-"}</td>
        <td class="r num">${b.ex_st == null ? "-" : (b.ex_st_flag === "F" ? "F" : "") + Math.abs(b.ex_st).toFixed(2).replace(/^0/, "")}</td>
        <td><div style="display:flex;align-items:center;gap:6px"><div class="bar"><b style="width:${(b.p_win / maxWin) * 100}%"></b></div><span class="num">${pct(b.p_win)}</span></div></td>
        <td class="r num">${pct(b.p_top3)}</td></tr>`;
    }).join("");
    const oddsOf = (c) => {
      const o = race.odds_pre;
      if (!o) return null;
      if (c.length === 3) return o.ex?.[c] ?? null;
      const [a, b2, c2] = c.split("-").map(Number);
      const rest = [1, 2, 3, 4, 5, 6].filter((x) => x !== a);
      const pairs = [];
      for (const x of rest) for (const y of rest) if (x !== y) pairs.push(`${x}-${y}`);
      return o.v?.[(a - 1) * 20 + pairs.indexOf(`${b2}-${c2}`)] ?? null;
    };
    const betCell = (b, won) => {
      const o = oddsOf(b.combo);
      return `<span class="bet ${won ? "won" : ""}">${combo(b.combo)}${o ? `<b class="odds num">${o}倍</b>` : ""}<small>AI ${pct(b.p, 1)}</small></span>`;
    };
    const comp = (arr) => {
      const os = arr.map((b) => oddsOf(b.combo));
      if (!os.length || os.some((o) => !o)) return "";
      return `・合成オッズ <b class="num">${(1 / os.reduce((s, o) => s + 1 / o, 0)).toFixed(1)}倍</b>`;
    };
    const betRow = (arr) => arr.map((b) => betCell(b, res && res.trifecta === b.combo)).join("");
    const wind = p.wind || {};
    app.innerHTML = head + `
      <div class="race-grid">
        <div style="display:grid;gap:16px;min-width:0">
          ${recoPanel(race, res)}
          ${specPanel(race, p, res)}
          <section class="slip">
            <div class="slip-h"><b>参考：AIの着順予想</b><span><span class="pill" style="border-color:#fff;color:#fff">${esc(p.confidence.label)}</span>　${esc(p.stage)}予想 ${esc(p.made_at || "")}時点・${race.odds_pre ? `オッズ ${esc(race.odds_pre.at)}時点` : "オッズは締切35分前から表示"}</span></div>
            <div class="slip-b">
              <div class="bet-group"><span>本線（3連単 ${p.bets.main.length}点${comp(p.bets.main)}）</span><div class="bets">${betRow(p.bets.main)}</div></div>
              <div class="bet-group"><span>押さえ（${p.bets.sub.length}点${comp(p.bets.sub)}）</span><div class="bets">${betRow(p.bets.sub)}</div></div>
              ${p.bets.ana.length ? `<div class="bet-group"><span>穴目</span><div class="bets">${betRow(p.bets.ana)}</div></div>` : ""}
              <div class="bet-group"><span>2連単</span><div class="bets">${p.bets.exacta.map((b) => betCell(b, false)).join("")}</div></div>
              ${res ? `<div class="bet-group"><span>結果</span><div class="bets" style="align-items:center">${combo(res.trifecta)} <strong class="num">${yen(res.trifecta_payout)}</strong> <span class="sub">${esc(res.kimarite)}</span> <span class="pill ${bought.has(res.trifecta) ? "hit" : "miss"}">${bought.has(res.trifecta) ? "的中" : "不的中"}</span></div></div>` : ""}
            </div>
          </section>
          <section class="panel" style="display:grid;gap:8px"><h2>見立て</h2><ul class="comments">${p.comments.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></section>
          ${courseStatsPanel(p)}
          ${ad("race_mid")}
          <section style="display:grid;gap:8px"><h2>出走データと予想確率 <small>進入 ${p.entry.map(bt).join("")}${p.entry_changed ? " 進入変化あり" : ""}</small></h2>
            <div class="panel tbl-wrap" style="padding:4px 8px"><table>
              <thead><tr><th></th><th>枠</th><th>選手</th><th class="r">コース</th><th class="r">全国勝率</th><th class="r">当地</th><th class="r">モーター2連</th><th class="r">展示T</th><th class="r">展示ST</th><th>1着確率</th><th class="r">3着内</th></tr></thead>
              <tbody>${rows}</tbody></table></div></section>
        </div>
        <aside class="panel water" style="display:grid;gap:6px">
          <h2>水面気象 <small>${w.as_of ? esc(w.as_of) + "現在" : (bi.weather ? "" : "展示前")}</small></h2>
          ${waterSvg(wind, w)}
          <div class="wx">
            <div><small>風</small><b>${esc(wind.type || "-")}</b></div>
            <div><small>風速</small><b>${wind.speed ?? "-"}m</b></div>
            <div><small>波高</small><b>${w.wave_cm ?? "-"}cm</b></div>
            <div><small>天候</small><b style="font-family:var(--body)">${esc(w.weather || "-")}</b></div>
            <div><small>気温</small><b>${w.air_temp ?? "-"}℃</b></div>
            <div><small>水温</small><b>${w.water_temp ?? "-"}℃</b></div>
          </div>
          ${ad("race_side")}
        </aside>
      </div>`;
  }




  // ------------------------------------------------------------ B級コース巧者（検証中の仮説）
  function specPanel(race, p, res) {
    const sp = p.specialists || [];
    if (!sp.length) return "";
    const wo = race.win_odds?.v || [];
    const rows = sp.map((x) => `<tr><td>${bt(x.frame)} ${esc(x.name)} <span class="sub">${esc(x.class)}</span></td><td class="r num">${x.course}コース</td>
      <td class="r num">${x.wins}/${x.starts}（全国平均の${x.ratio}倍）</td><td class="r num">${wo[x.frame - 1] ? wo[x.frame - 1] + "倍" : "-"}</td>
      <td>${res ? `<span class="pill ${res.win === x.frame ? "hit" : "miss"}">${res.win === x.frame ? "1着 " + yen(res.win_payout) : "着外"}</span>` : ""}</td></tr>`).join("");
    return `<section class="panel vp" style="border:2px dashed var(--accent)"><h2>注目：B級のコース巧者 <small>検証中の仮説・単勝で追跡</small></h2>
      <div class="tbl-wrap"><table><thead><tr><th>選手</th><th class="r">進入</th><th class="r">このコースの1着（直近1年）</th><th class="r">単勝</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="sub">B級で3・4コースに入り、そのコースの成績が全国平均の約1.5倍以上ある選手です。過去9千レースでは、オッズの見立てより約1.4倍多く1着になっていました。まだ偶然の可能性があるため、単勝での成績をこのサイトで公開しながら検証しています。</p></section>`;
  }


  // ------------------------------------------------------------ 推奨買い目（合成オッズ5倍以上）
  function recoPanel(race, res) {
    const r = race.reco;
    if (!r) return `<section class="panel vp"><h2>推奨買い目 <small>締切35分前からオッズを見て、合成オッズ5倍以上になるように組みます</small></h2></section>`;
    const prov = r.final === false ? "（暫定。締切7分前以降で確定）" : "";
    const head = `<small>${esc(r.at)}時点のオッズ${prov}</small>`;
    const verdictCls = { "自信あり": "go", "推奨": "", "購入非推奨": "skip", "見送り": "skip" }[r.verdict] || "";
    if (r.verdict === "購入非推奨") {
      return `<section class="panel vp skip"><h2>購入非推奨（ガチガチ） ${head}</h2>
        <p>AIの本命 ${combo(r.top.combo)} が <b class="num">${r.top.odds ?? "-"}倍</b>。人気が集中していて、合成オッズ${r.rule.min_comp}倍以上で組むと本命を外すことになります。5倍以上で組むには本命の目を外すしかなく、狙いとずれるため購入非推奨にしています。</p>
        ${res ? `<p class="sub">結果 ${combo(res.trifecta)} ${yen(res.trifecta_payout)}</p>` : ""}</section>`;
    }
    const rows = r.bets.map((b) => `<tr class="${res && res.trifecta === b.combo ? "won" : ""}"><td>${combo(b.combo)}</td><td class="r num">${b.odds}倍</td><td class="r num">${r.alloc[b.combo] ? yen(r.alloc[b.combo]) : "-"}</td><td class="r num">${r.alloc[b.combo] ? yen(Math.round(r.alloc[b.combo] * b.odds)) : "-"}</td><td class="r num sub">${pct(b.p, 1)}</td></tr>`).join("");
    const allocTotal = Object.values(r.alloc).reduce((a, b) => a + b, 0);
    const result = res ? `<p><span class="pill ${race.r_hit ? "hit" : "miss"}">${race.r_hit ? "的中" : "不的中"}</span> 結果 ${combo(res.trifecta)} ${yen(res.trifecta_payout)}</p>` : "";
    return `<section class="panel vp ${verdictCls}"><h2>${r.verdict === "自信あり" ? "推奨買い目・自信あり" : "推奨買い目"} ${head}</h2>
      <div class="tiles">
        <div class="tile"><small>合成オッズ</small><b>${Number(r.comp).toFixed(2)}倍</b></div>
        <div class="tile"><small>点数</small><b>${r.bets.length}点</b></div>
        <div class="tile"><small>的中見込み（オッズから）</small><b>${pct(r.market_hit)}</b></div>
        <div class="tile"><small>AIの見込み</small><b>${pct(r.ai_hit)}</b></div>
      </div>
      <div class="tbl-wrap"><table><thead><tr><th>3連単</th><th class="r">オッズ</th><th class="r">配分（計${yen(allocTotal)}）</th><th class="r">当たれば</th><th class="r">AI確率</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${r.alloc_min_return ? `<p>この配分（計 <b class="num">${yen(allocTotal)}</b>）なら、どれが当たっても <b class="num">${yen(r.alloc_min_return)}</b> 以上（実質 <b class="num">${(r.alloc_min_return / allocTotal).toFixed(2)}倍</b>）。予算に合わせて全部を同じ割合で増減してください。</p>` : ""}
      ${result}
      <p class="sub">合成オッズ ＝ 1 ÷（1/オッズ① ＋ 1/オッズ② ＋ …）。AIの確率が高い順に、合成オッズが${r.rule.min_comp}倍を下回らない範囲で最大${r.rule.max_points}点（AI確率1%未満の目は入れない）を選んでいます。配分どおりに買えば、どれが当たっても払戻がほぼ同じ（投資額×合成オッズ）になります。過去9千レースの検証では、実際の的中率は「AIの見込み」より「オッズからの見込み」に近く出ています。</p></section>`;
  }

  // ------------------------------------------------------------ 期待値パネル
  function valuePanel(race, res) {
    const v = race.value;
    if (!v) return `<section class="panel vp"><h2>期待値チェック <small>締切7分前にオッズを確認して判定します</small></h2></section>`;
    const st = v.params?.status || "検証中";
    const head = `<small>${esc(v.at)}時点のオッズ${v.final === false ? "（暫定。締切7分前以降で確定）" : ""}・判定ルール：合成確率×オッズ≧${v.params?.ev_min ?? 1}・${v.params?.max_odds ?? 200}倍以下・<span class="pill ${st === "有効" ? "lv4" : "lv2"}">${esc(st)}</span></small>`;
    if (!v.bets.length) return `<section class="panel vp skip"><h2>見送り推奨 ${head}</h2><p>この時点のオッズでは、期待値が1を超える買い目はありませんでした。AIの本命どおりでも、オッズが安すぎて長く続けると負ける形です。</p></section>`;
    const rows = v.bets.map((b) => `<tr class="${res && res.trifecta === b.combo ? "won" : ""}"><td>${combo(b.combo)}</td><td class="r num">${b.odds}倍</td><td class="r num">${pct(b.p, 1)}</td><td class="r num best">${b.ev.toFixed(2)}</td></tr>`).join("");
    const result = res ? `<p><span class="pill ${race.value_hit ? "hit" : "miss"}">${race.value_hit ? "的中" : "不的中"}</span> 結果 ${combo(res.trifecta)} ${yen(res.trifecta_payout)}（投資 ${yen(race.v_invest)} → 払戻 ${yen(race.v_return)}）</p>` : "";
    return `<section class="panel vp go"><h2>勝負：期待値のある買い目 ${v.bets.length}点 ${head}</h2>
      <div class="tbl-wrap"><table><thead><tr><th>3連単</th><th class="r">オッズ</th><th class="r">合成確率</th><th class="r">期待値</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${result}<p class="sub">合成確率は、オッズが示す確率にAIの予想を少し混ぜたものです。期待値1.0は「長く買い続けると元本と同じ」の目安です。</p></section>`;
  }

  // ------------------------------------------------------------ コース戦績パネル
  function courseStatsPanel(p) {
    const cs = p.course_stats;
    if (!cs) return "";
    const inb = p.boats.find((b) => b.course === 1);
    const ip = cs.in;
    let inHtml = "";
    if (ip && ip.starts) {
      const bars = ["差され", "捲られ", "捲り差され", "その他"].map((k) => {
        const v = ip.loss[k] || 0, n = ip.nat_loss[k] || 0, max = 0.3;
        const warn = n && v >= n * 1.3 && v >= 0.06;
        return `<div class="lrow"><span>${k}</span><div class="lbar"><b style="width:${Math.min(v / max, 1) * 100}%" class="${warn ? "warn" : ""}"></b><i style="left:${Math.min(n / max, 1) * 100}%" title="全国平均"></i></div><span class="num ${warn ? "best" : ""}">${pct(v)}</span></div>`;
      }).join("");
      inHtml = `<div class="inprof">
        <div><span class="eyebrow">1コース ${bt(inb.frame)} ${esc(inb.name)}</span>
          <div class="esc"><b class="num">${pct(ip.escape)}</b><span class="sub">逃げ率（全国 ${pct(ip.nat_escape)}・${ip.starts}走）</span></div></div>
        <div class="lbars">${bars}<p class="sub">縦線は全国平均。赤は平均の1.3倍以上</p></div></div>`;
    }
    const rows = p.boats.slice().sort((a, b) => a.course - b.course).map((b) => {
      const s = cs.boats[b.frame];
      if (!s) return "";
      const kim = Object.entries(s.kimarite).map(([k, v]) => `${k}${v}`).join("・") || "-";
      const up = s.win != null && s.nat_win && s.win >= s.nat_win * 1.2;
      return `<tr><td class="r num">${b.course}</td><td>${bt(b.frame)}</td><td>${esc(b.name)}</td>
        <td class="r num">${s.starts}</td>
        <td class="r num ${up ? "best" : ""}">${pct(s.win)}</td><td class="r num sub">${pct(s.nat_win)}</td>
        <td class="r num">${pct(s.top3)}</td><td>${esc(kim)}</td><td class="r num">${s.avg_st != null ? s.avg_st.toFixed(2).replace(/^0/, "") : "-"}</td></tr>`;
    }).join("");
    return `<section class="panel" style="display:grid;gap:12px"><h2>コース戦績 <small>直近1年・今回の進入コースでの成績</small></h2>
      ${inHtml}
      <div class="tbl-wrap"><table><thead><tr><th class="r">コース</th><th>枠</th><th>選手</th><th class="r">出走</th><th class="r">1着率</th><th class="r">全国</th><th class="r">3連対率</th><th>1着の決まり手</th><th class="r">平均ST</th></tr></thead><tbody>${rows}</tbody></table></div>
    </section>`;
  }

  // ------------------------------------------------------------ 成績
  async function viewStats() {
    setNav("stats");
    const s = await load("stats.json");
    if (!s || !s.all.races) { app.innerHTML = `<p class="empty">的中実績は結果が出たレースから集計されます。</p>`; return; }
    let range = "last30";
    const render = () => {
      const t = s[range];
      const rate = t.races ? t.hits / t.races : 0, roi = t.invest ? t.return / t.invest : 0;
      const roiM = t.invest_main ? t.return_main / t.invest_main : 0;
      const days = s.days.slice(range === "last7" ? -7 : -30);
      const maxV = Math.max(1, ...days.map((d) => Math.max(d.invest, d.return)));
      const bw = 560 / Math.max(days.length, 1);
      const bars = days.map((d, i) => {
        const x = 40 + i * bw, hi = (d.invest / maxV) * 150, hr = (d.return / maxV) * 150;
        return `<rect x="${x + bw * 0.12}" y="${170 - hi}" width="${bw * 0.36}" height="${hi}" fill="var(--water2)"/>
          <rect x="${x + bw * 0.5}" y="${170 - hr}" width="${bw * 0.36}" height="${hr}" fill="var(--accent)"/>
          ${days.length <= 10 || i % 3 === 0 ? `<text x="${x + bw / 2}" y="186" text-anchor="middle" font-size="10" fill="var(--ink2)">${+d.date.slice(6)}日</text>` : ""}`;
      }).join("");
      const ticks = [0, 0.5, 1].map((k) => `<line x1="40" x2="600" y1="${170 - k * 150}" y2="${170 - k * 150}" stroke="var(--line)"/>
        <text x="34" y="${174 - k * 150}" text-anchor="end" font-size="10" fill="var(--ink2)">${Math.round((maxV * k) / 1000)}k</text>`).join("");
      const vroi = t.v_invest ? t.v_return / t.v_invest : 0;
      $("#stats-body").innerHTML = `
        <h2>推奨買い目（合成オッズ5倍以上）<small>主な成績・合成オッズ配分（1,000円）で購入した場合</small></h2>
        <div class="tiles">
          <div class="tile"><small>推奨したレース</small><b>${(t.r_races || 0).toLocaleString()}</b></div>
          <div class="tile"><small>的中</small><b>${t.r_hits || 0}${t.r_races ? `<small style="display:inline"> (${pct(t.r_hits / t.r_races)})</small>` : ""}</b></div>
          <div class="tile"><small>回収率</small><b class="${t.r_invest && t.r_return >= t.r_invest ? "up" : "down"}">${t.r_invest ? pct(t.r_return / t.r_invest, 1) : "-"}</b></div>
          <div class="tile"><small>購入非推奨にしたレース</small><b>${t.gachi || 0}</b></div>
        </div>
        <div class="tiles">
          <div class="tile"><small>うち自信あり</small><b>${t.rc_races || 0}</b></div>
          <div class="tile"><small>自信ありの的中</small><b>${t.rc_hits || 0}</b></div>
          <div class="tile"><small>自信ありの回収率</small><b class="${t.rc_invest && t.rc_return >= t.rc_invest ? "up" : "down"}">${t.rc_invest ? pct(t.rc_return / t.rc_invest, 1) : "-"}</b></div>
          <div class="tile"><small>期待値買い（検証中）</small><b style="font-size:18px">${t.v_races ? `${t.v_races}R・${pct(vroi)}` : "該当なし"}</b></div>
        </div>
        <h2>B級コース巧者の単勝（検証中）</h2>
        <div class="tiles">
          <div class="tile"><small>対象艇</small><b>${t.s_boats || 0}</b></div>
          <div class="tile"><small>1着</small><b>${t.s_hits || 0}</b></div>
          <div class="tile"><small>単勝回収率</small><b class="${t.s_invest && t.s_return / t.s_invest >= 1 ? "up" : "down"}">${t.s_invest ? pct(t.s_return / t.s_invest, 1) : "-"}</b></div>
        </div>
        <h2>参考：AIの着順予想を全レース買った場合</h2>
        <div class="tiles">
          <div class="tile"><small>対象レース</small><b>${t.races}</b></div>
          <div class="tile"><small>的中率（本線＋押さえ）</small><b>${pct(rate, 1)}</b></div>
          <div class="tile"><small>回収率（本線＋押さえ）</small><b class="${roi >= 1 ? "up" : "down"}">${pct(roi, 1)}</b></div>
          <div class="tile"><small>回収率（本線のみ）</small><b class="${roiM >= 1 ? "up" : "down"}">${pct(roiM, 1)}</b></div>
        </div>
        <section class="panel chart" style="display:grid;gap:6px"><h2>日別の投資と払戻 <small>各買い目100円換算</small></h2>
          <svg viewBox="0 0 610 196" role="img" aria-label="日別の投資額と払戻額">${ticks}${bars}</svg>
          <p class="sub"><span class="bt" style="width:10px;height:10px;background:var(--water2);border:0"></span> 投資　<span class="bt" style="width:10px;height:10px;background:var(--accent);border:0"></span> 払戻</p></section>`;
      document.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.r === range));
    };
    const best = s.best.map((b) => `<tr><td class="num">${+b.date.slice(4, 6)}/${+b.date.slice(6)}</td><td>${esc(b.venue)} ${b.rno}R</td><td>${combo(b.combo)}</td><td class="r num best">${yen(b.payout)}</td></tr>`).join("");
    app.innerHTML = `
      <section style="display:grid;gap:6px"><span class="eyebrow">Track record</span><h1>的中実績</h1>
        <p class="sub">${esc(s.note || "締切前に掲載した買い目だけを自動で集計しています。後から書き換えはしていません。")}</p></section>
      <div class="seg" role="group" aria-label="集計期間"><button data-r="last7">7日</button><button data-r="last30">30日</button><button data-r="all">全期間</button></div>
      <div id="stats-body" style="display:grid;gap:16px"></div>
      ${dayReport(s.day_report)}
      <section style="display:grid;gap:8px"><h2>高配当の的中</h2>
        <div class="panel tbl-wrap" style="padding:4px 8px"><table><thead><tr><th>日付</th><th>レース</th><th>3連単</th><th class="r">払戻</th></tr></thead><tbody>${best || `<tr><td colspan="4" class="empty">まだありません</td></tr>`}</tbody></table></div></section>`;
    document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => { range = b.dataset.r; render(); }));
    render();
  }




  function recoSection(r) {
    const b = r.reco_backtest;
    if (!b) return "";
    const rows = Object.entries(b.tiers).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="r num">${v.races.toLocaleString()}</td><td class="r num">${v.median_comp}倍</td><td class="r num">${pct(v.hit, 1)}</td><td class="r num">${pct(v.market_hit, 1)}</td><td class="r num sub">${pct(v.ai_hit, 1)}</td><td class="r num ${v.roi >= 1 ? "best" : ""}">${pct(v.roi, 1)}</td><td class="r num sub">${pct(v.ci95[0])}〜${pct(v.ci95[1])}</td><td class="r num">${pct(v.roi_alloc, 1)}</td><td class="r num sub">${pct(v.ci95_alloc[0])}〜${pct(v.ci95_alloc[1])}</td></tr>`).join("");
    return `<section class="panel" style="display:grid;gap:10px"><h2>推奨買い目（合成オッズ5倍以上）の検証 <small>${esc(b.period)}</small></h2>
      <p>${esc(b.rule)}。各100円で買った場合です。</p>
      <div class="tbl-wrap"><table><thead><tr><th>判定</th><th class="r">レース</th><th class="r">合成オッズ</th><th class="r">実際の的中率</th><th class="r">オッズからの見込み</th><th class="r">AIの見込み</th><th class="r">均等買い回収</th><th class="r">95%区間</th><th class="r">配分買い回収</th><th class="r">95%区間</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="sub">均等買いは各100円、配分買いは合成オッズどおり（どれが当たっても払戻が同じになる配分）で買った場合です。合成オッズを5倍にすると、実際の的中率は15〜16%前後に落ち着き、これはオッズから逆算した見込みとほぼ一致します。AIの見込みは高めに出るため、表示ではオッズからの見込みを主に使っています。どの判定も100%には届いていません。「自信あり」でも実際の的中率は通常とほぼ同じで、AIの自信はオッズ以上の情報にはなっていません。ガチガチのレースは、配分買いでは他と同程度の回収率です。</p></section>`;
  }

  function evSection(r) {
    const e = r.ev;
    if (!e) return "";
    const fmt = (d) => `${d.slice(0, 4)}/${+d.slice(4, 6)}/${+d.slice(6)}`;
    const m = e.result;
    const rows = Object.entries(e.variants).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="r num">${(v.bet_races || 0).toLocaleString()}</td><td class="r num">${v.hits ?? "-"}</td><td class="r num ${v.roi >= 1 ? "best" : ""}">${v.roi == null ? "買い目なし" : pct(v.roi, 1)}</td><td class="r num sub">${v.ci95 ? pct(v.ci95[0]) + "〜" + pct(v.ci95[1]) : "-"}</td></tr>`).join("");
    const sp = r.specialist ? Object.entries(r.specialist).map(([c, v]) => `<tr><td>${c}コース</td><td class="r num">${v.boats}</td><td class="r num">${pct(v.win, 1)}</td><td class="r num">${pct(v.market, 1)}</td><td class="r num ${v.win / v.market >= 1.1 ? "best" : ""}">${(v.win / v.market).toFixed(2)}倍</td></tr>`).join("") : "";
    return `<section class="panel" style="display:grid;gap:10px"><h2>オッズ × AI の期待値買い <small>${fmt(e.period[0])}〜${fmt(e.period[1])}・確定オッズのある${e.races.toLocaleString()}レース</small></h2>
      <div class="tiles">
        <div class="tile"><small>勝負したレース</small><b>${m.bet_races.toLocaleString()}</b></div>
        <div class="tile"><small>的中</small><b>${m.hits}</b></div>
        <div class="tile"><small>回収率</small><b class="${m.roi >= 1 ? "up" : "down"}">${m.roi == null ? "-" : pct(m.roi, 1)}</b></div>
        <div class="tile"><small>判定</small><b style="font-size:20px">${esc(e.blend.status)}</b></div>
      </div>
      <p>オッズが示す確率に、AIの予想を少しだけ混ぜた確率（市場${e.blend.market}：AI${e.blend.model}の重み）で期待値を計算し、${e.rule.ev_min}以上・${e.rule.max_odds}倍以下の目だけを買った場合です。混ぜる割合は偶数日で決めて奇数日で検証、その逆も行いました。</p>
      <div class="tbl-wrap"><table><thead><tr><th>買い方</th><th class="r">勝負レース</th><th class="r">的中</th><th class="r">回収率</th><th class="r">95%区間</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${e.note ? `<p class="sub">${esc(e.note)}</p>` : ""}
      ${sp ? `<h2>B級の外コース巧者は安く見られているか <small>そのコースの1着率が全国平均の1.5倍以上</small></h2>
      <div class="tbl-wrap"><table><thead><tr><th>コース</th><th class="r">艇数</th><th class="r">実際の1着率</th><th class="r">オッズの見立て</th><th class="r">実際÷見立て</th></tr></thead><tbody>${sp}</tbody></table></div>` : ""}
      ${r.specialist_tansho ? `<h2>単勝で買った場合 <small>${esc(r.specialist_tansho.period)}</small></h2>
      <div class="tbl-wrap"><table><thead><tr><th>コース</th><th class="r">艇数</th><th class="r">1着</th><th class="r">平均単勝オッズ</th><th class="r">単勝回収率</th><th class="r">95%区間</th></tr></thead><tbody>
      ${Object.entries(r.specialist_tansho.by_course).map(([c, v]) => `<tr><td>${c}コース</td><td class="r num">${v.boats}</td><td class="r num">${v.wins}</td><td class="r num">${v.avg_odds}倍</td><td class="r num ${v.roi >= 1 ? "best" : ""}">${pct(v.roi, 1)}</td><td class="r num sub">${pct(v.ci95[0])}〜${pct(v.ci95[1])}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="sub">4コースの巧者は単勝回収率141%でしたが、艇数が少なく95%区間は73%〜227%で、まだ偶然と区別できません。一方、2コース・6コースの「巧者」は人気を集めすぎていて、単勝回収率はそれぞれ43%・24%と大きく負けています。</p>` : ""}
    </section>`;
  }


  function dayReport(d) {
    if (!d) return "";
    const row = (name, v) => `<tr><td>${esc(name)}</td><td class="r num">${v.races}</td><td class="r num">${pct(v.fav_win / v.races)}</td><td class="r num">${v.top1}</td>
      <td class="r num">${v.main_hit}</td><td class="r num ${v.main_ret >= v.main_inv ? "best" : ""}">${pct(v.main_ret / v.main_inv)}</td>
      <td class="r num">${v.all_hit}</td><td class="r num ${v.all_ret >= v.all_inv ? "best" : ""}">${pct(v.all_ret / v.all_inv)}</td>
      <td class="r num">${v.r_races ? `${v.r_hit}/${v.r_races}` : "-"}</td><td class="r num ${v.r_ret >= v.r_inv && v.r_inv ? "best" : ""}">${v.r_inv ? pct(v.r_ret / v.r_inv) : "-"}</td><td class="r num">${v.gachi || 0}</td>
      <td class="r num">${v.s_boats ? `${v.s_hit}/${v.s_boats}` : "-"}</td><td class="r num">${v.s_inv ? pct(v.s_ret / v.s_inv) : "-"}</td></tr>`;
    const rows = Object.entries(d.venues).map(([k, v]) => row(k, v)).join("");
    return `<section style="display:grid;gap:8px"><h2>本日の会場別成績 <small>各買い目100円換算</small></h2>
      <div class="panel tbl-wrap" style="padding:4px 8px"><table><thead><tr><th>会場</th><th class="r">R</th><th class="r">本命1着</th><th class="r">1点目的中</th><th class="r">本線的中</th><th class="r">本線回収</th><th class="r">本線+押さえ的中</th><th class="r">同回収</th><th class="r">推奨的中</th><th class="r">推奨回収</th><th class="r">非推奨</th><th class="r">巧者1着</th><th class="r">巧者単勝回収</th></tr></thead>
      <tbody>${rows}</tbody><tfoot>${row("合計", d.total).replace(/<td>/, "<td><b>").replace("合計</td>", "合計</b></td>")}</tfoot></table></div></section>`;
  }

  // ------------------------------------------------------------ 予想の根拠
  async function viewLogic() {
    setNav("logic");
    const r = await load("model_report.json");
    if (!r) { app.innerHTML = `<p class="empty">検証結果を準備中です。</p>`; return; }
    const fmt = (d) => `${d.slice(0, 4)}/${+d.slice(4, 6)}/${+d.slice(6)}`;
    const vrows = Object.entries(r.variants).map(([k, v], i, a) => {
      const prev = i ? a[i - 1][1].logloss : null;
      return `<tr><td>${esc(k)}</td><td class="r num">${pct(v.win_acc, 1)}</td><td class="r num">${v.logloss.toFixed(4)}</td><td class="r num sub">${prev ? (prev - v.logloss).toFixed(4) : "-"}</td></tr>`;
    }).join("");
    const grid = (c) => {
      const m = r.matchup[c];
      const labI = ["捲られにくい", "普通", "捲られやすい"], labA = ["捲り勝ち少", "普通", "捲り勝ち多"];
      const max = Math.max(...m.grid.flat().map((x) => x.makuri_win));
      return `<div class="tbl-wrap"><table class="heat"><thead><tr><th>1コース艇 ＼ ${c}コース艇</th>${labA.map((l) => `<th class="r">${l}</th>`).join("")}</tr></thead><tbody>
        ${m.grid.map((row, i) => `<tr><th>${labI[i]}</th>${row.map((x) => `<td class="r num" style="background:color-mix(in srgb, var(--accent) ${Math.round((x.makuri_win / max) * 55)}%, transparent)">${pct(x.makuri_win, 1)}<small>1着 ${pct(x.win)}</small></td>`).join("")}</tr>`).join("")}
        </tbody></table></div><p class="sub">区切り：インの捲られ率 ${m.in_cut.map((v) => pct(v)).join(" / ")}、${c}コースでの捲り勝ち率 ${m.att_cut.map((v) => pct(v, 1)).join(" / ")}</p>`;
    };
    const t = r.test;
    const topn = Object.entries(t.trifecta_topN).map(([n, v]) => `<tr><td class="r num">上位${n}点</td><td class="r num">${pct(v.hit, 1)}</td><td class="r num ${v.roi >= 1 ? "best" : ""}">${v.roi == null ? "買い目なし" : pct(v.roi, 1)}</td></tr>`).join("");
    const conf = Object.entries(t.by_confidence).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="r num">${v.races.toLocaleString()}</td><td class="r num">${pct(v.win_acc, 1)}</td><td class="r num">${pct(v.top8_hit, 1)}</td><td class="r num">${pct(v.top8_roi, 1)}</td></tr>`).join("");
    app.innerHTML = `
      <section style="display:grid;gap:6px"><span class="eyebrow">Evidence</span><h1>予想の根拠</h1>
        <p class="sub">重みはすべて公式の競走成績・番組表データから学習しています。検証は学習に使っていない${fmt(r.period.test[0])}〜${fmt(r.period.test[1])}の${t.races.toLocaleString()}レースで行いました（学習：${r.n_train.toLocaleString()}レース）。各レースの特徴量は、そのレースより前のデータだけで計算しています。</p></section>
      ${recoSection(r)}
      ${evSection(r)}
      <section class="panel" style="display:grid;gap:10px"><h2>仮説：捲られやすいイン × 捲りの多い攻め手 <small>実際に捲りで勝った割合</small></h2>
        <div class="two">${grid("3")}${grid("4")}</div>
        <p>捲られにくいインと捲りの少ない3コースの組み合わせでは捲り勝ちが数%ですが、捲られやすいインと捲りの多い3コースでは10%を超え、1着率も3倍前後になります。</p></section>
      <section class="panel" style="display:grid;gap:10px"><h2>要素を足すと予想はどれだけ良くなるか <small>検証期間・1着予想</small></h2>
        <div class="tbl-wrap"><table><thead><tr><th>モデル</th><th class="r">本命の1着的中率</th><th class="r">対数損失</th><th class="r">改善幅</th></tr></thead><tbody>${vrows}</tbody></table></div>
        <p class="sub">対数損失は小さいほど確率の当てはまりが良い指標です。インの負け方×攻め手は、表のとおり実際の結果に強く効いていますが、その多くは勝率やコース別成績にすでに含まれているため、上乗せ分は小さくなります。</p></section>
      <section class="panel" style="display:grid;gap:10px"><h2>3連単の検証結果 <small>確率の高い順にN点買った場合・100円換算</small></h2>
        <div class="two"><div class="tbl-wrap"><table><thead><tr><th class="r">買い方</th><th class="r">的中率</th><th class="r">回収率</th></tr></thead><tbody>${topn}</tbody></table></div>
        <div class="tbl-wrap"><table><thead><tr><th>信頼度</th><th class="r">レース数</th><th class="r">1着的中</th><th class="r">8点的中</th><th class="r">8点回収</th></tr></thead><tbody>${conf}</tbody></table></div></div>
        <p class="sub">3連単の払戻率は75%なので、でたらめに買うと回収率は75%前後になります。このモデルはそれを上回りますが、100%には届いていません。オッズを使って期待値の高い買い目だけに絞る仕組みは今後追加します。</p></section>`;
  }

  // ------------------------------------------------------------ ルーター
  async function route() {
    const h = window.__ROUTE__ || location.hash.replace(/^#\/?/, "");
    const [a, b, c] = h.split("/");
    try {
      if (a === "v") await viewVenue(b);
      else if (a === "r") await viewRace(b, +c);
      else if (a === "stats") await viewStats();
      else if (a === "logic") await viewLogic();
      else await viewHome();
    } catch (e) {
      console.error(e);
      app.innerHTML = `<p class="empty">表示中にエラーが発生しました。ページを再読み込みしてください。</p>`;
    }
  }
  if (!app) return;
  if (!window.__ROUTE__) window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); });
  route();
  // 1分ごとにデータを読み直す（開いたままでも締切カウントダウンと予想が進む）
  if (!window.__DEMO__) setInterval(() => { delete cache.idx; route(); }, 60000);
})();
