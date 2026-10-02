"""検索エンジンに読まれる「普通のHP」を静的HTMLで書き出す。

  python -m scraper.sitegen          # 全ページを site/ に生成（5分おきの更新ごとに実行）

ページ
  index.html                         トップ（今日の推奨・開催場・狙い目）
  race/YYYYMMDD/{場}-{R}.html         レースごとの予想・オッズ・展示・結果
  venue/{場}.html                     レース場の特徴とコース別成績（24場）
  racer/{登番}.html / racer/index.html 選手のコース別成績（約1,600人）
  targets.html                       狙い目レーサーまとめ
  tools/composite.html               合成オッズ計算
  guide/*.html                       初心者向け解説
  stats.html / logic.html            的中実績・予想の根拠（data/*.json を読む小さなJS）
  sitemap.xml / robots.txt

リンクはすべて相対パス（どの階層から開いても、プレビューでも動く）。
"""
from __future__ import annotations

import html
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import fstart, overperf
from .history import load_all
from .model import KIM, load_stats
from .predict import VENUES

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
DATA = OUT / "data"
SITE_NAME = "艇ろぐ"
SITE_URL = __import__("os").environ.get("SITE_URL", "https://example.com").rstrip("/")
SLUG = {"01": "kiryu", "02": "toda", "03": "edogawa", "04": "heiwajima", "05": "tamagawa", "06": "hamanako", "07": "gamagori",
        "08": "tokoname", "09": "tsu", "10": "mikuni", "11": "biwako", "12": "suminoe", "13": "amagasaki", "14": "naruto",
        "15": "marugame", "16": "kojima", "17": "miyajima", "18": "tokuyama", "19": "shimonoseki", "20": "wakamatsu",
        "21": "ashiya", "22": "fukuoka", "23": "karatsu", "24": "omura"}
RACE_KEEP_DAYS = 30
# 攻めた艇が1着のときの2着のコース（過去3年）と、まくりで勝ったときの2着
SECOND_ALL = {3: {1: .40, 2: .20, 4: .20, 5: .14, 6: .06}, 4: {1: .31, 5: .23, 2: .19, 3: .16, 6: .10}}
SECOND_MK = {3: {4: .28, 1: .23, 2: .20, 5: .20, 6: .09}, 4: {5: .34, 1: .23, 2: .18, 6: .15, 3: .10}}
FOLLOW_NOTE = {3: "3がまくると4が連れて2着に来やすい", 4: "2・3着は、5・6コースを中心に選手の力と展示で選んだ目", 5: "5がまくると叩かれた4は残りにくく、6と2が来やすい"}
MIN_STARTS = 20
OP_MIN = 15          # 実力補正スコアを出す最低出走数（そのコースで）
OP_MARK = 1.6        # 狙い目とみなすスコア

e = html.escape


# ---------------------------------------------------------------- 小道具
def pct(v, d=0):
    return "-" if v is None else f"{v * 100:.{d}f}%"


def yen(v):
    return "-" if v is None else f"¥{int(v):,}"


def bt(n):
    return f'<span class="bt bt{n}">{n}</span>'


def combo(c):
    return '<span class="combo">' + '<span class="sep">-</span>'.join(bt(x) for x in str(c).split("-")) + "</span>"


def day_parts(dd):
    """'9/22-9/274日目' → ('9/22〜9/27', '4日目')"""
    import re as _re
    dd = dd or ""
    m = _re.search(r"(初日|最終日|\d日目)$", dd)
    suf = m.group(1) if m else ""
    period = dd[: len(dd) - len(suf)].replace("-", "〜")
    return period, suf


def jdate(d):
    return f"{int(d[4:6])}月{int(d[6:8])}日"


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


from itertools import permutations as _perm
COMBO_LIST = [f"{a}-{b}-{c}" for a, b, c in _perm(range(1, 7), 3)]


class Page:
    """1ページ分。path はサイトルートからの相対パス（例 race/20260925/kiryu-12.html）"""

    def __init__(self, path: str):
        self.path = path
        self.depth = path.count("/")

    def u(self, target: str) -> str:
        return "../" * self.depth + target

    def render(self, title, desc, body, crumbs=(), script="", noindex=False):
        nav = [("index.html", "本日のレース", "レース", '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>'), ("targets.html", "狙い目レーサー", "狙い目", '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r=".8"/>'), ("racer/index.html", "選手", "選手", '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>'),
               ("stats.html", "的中実績", "実績", '<path d="M4 20h16M6 16l4-5 3 3 5-7"/>'), ("logic.html", "予想の根拠", "根拠", '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>')]
        navh = "".join(f'<a href="{self.u(h)}"{" aria-current=page" if h == self.path else ""}><svg class="ic" viewBox="0 0 24 24" aria-hidden="true">{ic}</svg><span class="l">{t}</span><span class="s">{st}</span></a>' for h, t, st, ic in nav)
        crumbs = [("index.html", "トップ")] + list(crumbs)
        bc = " › ".join(f'<a href="{self.u(h)}">{e(t)}</a>' if h else e(t) for h, t in crumbs)
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": t, **({"item": f"{SITE_URL}/{h}"} if h else {})} for i, (h, t) in enumerate(crumbs)]}
        return f"""<!doctype html>
<html lang="ja" data-theme="dark"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{SITE_URL}/{self.path if self.path != 'index.html' else ''}">
{'<meta name="robots" content="noindex">' if noindex else ''}
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:type" content="website">
<meta property="og:image" content="{SITE_URL}/img/og.jpg"><meta name="twitter:card" content="summary_large_image"><meta property="og:site_name" content="{SITE_NAME}">
<meta name="theme-color" content="#0B1116">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Noto+Sans+JP:wght@400;500;700;900&display=swap">
<link rel="stylesheet" href="{self.u('style.css')}">
<script>window.SITE_ROOT = "{self.u('')}";</script>
<script src="{self.u('config.js')}"></script>
<script src="{self.u('clock.js')}" defer></script>
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
</head><body>
<header class="top"><div class="wrap">
  <a class="brand" href="{self.u('index.html')}"><img src="{self.u('img/boat.webp')}" width="58" height="34" alt=""><span>{SITE_NAME}</span></a>
  {f'<span class="tagline">{e(TAGLINE)}</span>' if TAGLINE else ''}
  <nav class="nav">{navh}</nav>
</div></header>
<main class="wrap">
<p class="crumbs">{bc}</p>
{body}
</main>
<footer><div class="wrap">
  <p>掲載している買い目・データは過去の公式データと直前情報にもとづく参考情報で、的中や利益を保証するものではありません。舟券の購入はご自身の判断と責任でお願いします。</p>
  <p>20歳未満の方は舟券を購入できません。のめり込みに注意し、無理のない範囲でお楽しみください。</p>
  <p>レースデータ出典：<a href="https://www.boatrace.jp/" rel="noopener" target="_blank">BOAT RACE オフィシャルウェブサイト</a>　／　<a href="{self.u('about.html')}">運営者情報・プライバシーポリシー</a></p>
</div></footer>
{script}
</body></html>"""


def _tagline():
    rep = load_json(Path(__file__).parent / "model_report.json", {}) or {}
    n = (rep.get("n_train") or 0) + (rep.get("n_test") or 0)
    per = rep.get("period") or {}
    try:
        y0 = int(per["train"][0][:4]); y1 = int(per["test"][1][:4])
        years = max(1, round((datetime.strptime(per["test"][1], "%Y%m%d") - datetime.strptime(per["train"][0], "%Y%m%d")).days / 365))
    except Exception:
        return "全場の出走表・展示・オッズから買い目を判定"
    man = f"約{n // 10000}万" if n >= 10000 else f"{n:,}"
    return f"過去{years}年・{man}レースのデータで予想"


TAGLINE = _tagline()


class Site:
    def __init__(self, now: datetime | None = None):
        self.now = now or datetime.now(JST)
        self.files: dict[str, str] = {}
        self.S = load_stats()
        self.racers = (load_json(Path(__file__).parent / "racers.json", {}) or {}).get("racers", {})
        self.idx = load_json(DATA / "index.json", {"date": self.now.strftime("%Y%m%d"), "venues": []})
        self.report = load_json(Path(__file__).parent / "model_report.json", {})
        self.op = (overperf.load() or {}).get("oe", {})

    def put(self, path, text):
        self.files[path] = text

    # ------------------------------------------------------------ 共通の計算
    def nat(self, c):
        n = self.S.nc[c]
        return [n[i] / n[0] if n[0] else 0 for i in range(10)]

    def racer_course(self, toban, c):
        me = self.S.rc[toban][c]
        return me

    def shrunk_ratio(self, toban, c):
        me, nt = self.S.rc[toban][c], self.S.nc[c]
        p = nt[1] / nt[0] if nt[0] else 0.1
        return ((me[1] + 20 * p) / (me[0] + 20)) / p if p else 1

    def op_of(self, toban, c):
        """(出走, 実際の1着, 実力どおりなら取れた1着, 実力補正スコア)"""
        v = self.op.get(toban, {}).get(str(c))
        if not v:
            return None
        return v[0], v[1], v[2], overperf.score(v[1], v[2])

    def race_link(self, page, d, jcd, rno):
        return page.u(f"race/{d}/{SLUG[jcd]}-{rno}.html")

    def racer_link(self, page, toban):
        return page.u(f"racer/{toban}.html") if toban in self.racers else None

    def racer_name(self, toban, fallback=""):
        return self.racers.get(toban, {}).get("name") or fallback

    # ------------------------------------------------------------ レース
    def reco_block(self, race, res):
        r = race.get("reco")
        if not r or r["verdict"] in ("推奨", "見送り"):
            # 基本は上の「本線・押さえ」。合成5倍に絞るのは自信ありのときだけ
            return ""
        head = f'<small>{e(r.get("at", ""))}時点のオッズ{"（暫定。締切7分前以降で確定）" if r.get("final") is False else ""}</small>'
        if r["verdict"] == "購入非推奨" and (race.get("prediction") or {}).get("in_worry"):
            return (f'<section class="panel vp skip"><h2>見送り（イン人気過剰） {head}</h2>'
                    f'<p>本命 {combo(r["top"]["combo"])} が <b class="num">{r["top"]["odds"]}倍</b> まで売れていて、人気はインの逃げに集中しています。'
                    f'一方で下の「イン不安」の材料があり、この人気ほどインが安泰とは言えません。本命を買うには安すぎ、外から組むには根拠が足りないため、このレースは見送りにしています。</p>'
                    + (f'<p class="sub">結果 {combo(res["trifecta"])} {yen(res["trifecta_payout"])}</p>' if res else "") + "</section>")
        if r["verdict"] == "購入非推奨":
            return (f'<section class="panel vp skip"><h2>購入非推奨（ガチガチ） {head}</h2>'
                    f'<p>AIの本命 {combo(r["top"]["combo"])} が <b class="num">{r["top"]["odds"]}倍</b>。人気が集中していて、合成オッズ{r["rule"]["min_comp"]:g}倍以上で組むと本命を外すことになるため、購入をおすすめしません。</p>'
                    + (f'<p class="sub">結果 {combo(res["trifecta"])} {yen(res["trifecta_payout"])}</p>' if res else "") + "</section>")
        if not r["bets"]:
            return f'<section class="panel vp skip"><h2>見送り {head}</h2><p>条件を満たす買い目が組めませんでした。</p></section>'
        total = sum(r["alloc"].values())
        fin = race.get("odds_final")
        def fo(c):
            if not fin:
                return ""
            j = COMBO_LIST.index(c)
            return f'{fin[j]}倍' if fin[j] else "-"
        rows = "".join(
            f'<tr class="{"won" if res and res["trifecta"] == b["combo"] else ""}"><td>{combo(b["combo"])}</td><td class="r num">{b["odds"]}倍</td>'
            + (f'<td class="r num"><b>{fo(b["combo"])}</b></td>' if fin else "")
            + f'<td class="r num">{yen(r["alloc"].get(b["combo"]))}</td>'
            + ("" if fin else f'<td class="r num">{yen(round(r["alloc"].get(b["combo"], 0) * b["odds"]))}</td>')
            + f'<td class="r num sub">{pct(b["p"], 1)}</td></tr>' for b in r["bets"])
        result = ""
        if res:
            hit = race.get("r_hit")
            ret = race.get("r_return", 0)
            inv = race.get("r_invest", total)
            result = (f'<p><span class="pill {"hit" if hit else "miss"}">{"的中" if hit else "不的中"}</span> 結果 {combo(res["trifecta"])} {yen(res["trifecta_payout"])}</p>'
                      f'<p><b>実際の払戻 {yen(ret)}</b>（{yen(inv)}で購入・回収率 {pct(ret / inv if inv else 0)}）。'
                      f'<span class="sub">上の配分は{e(r.get("at", ""))}時点のオッズで組んだもので、締切までに人気の目ほどオッズが下がるため、確定オッズでの払戻は見込みより少なくなることがあります。</span></p>')
        conf = r["verdict"] == "自信あり"
        return f"""<section class="panel vp go"><h2><span class="chip cf">自信あり</span> 本線・押さえから合成{r['rule']['min_comp']:g}倍以上に絞った買い目 {head}</h2>
<div class="tiles"><div class="tile"><small>合成オッズ</small><b>{r['comp']:.2f}倍</b></div><div class="tile"><small>点数</small><b>{len(r['bets'])}点</b></div>
<div class="tile"><small>的中見込み（オッズから）</small><b>{pct(r['market_hit'])}</b></div><div class="tile"><small>AIの見込み</small><b>{pct(r['ai_hit'])}</b></div></div>
<div class="tbl-wrap"><table><thead><tr><th>3連単</th><th class="r">{e(r.get("at", ""))}時点</th>{'<th class="r">確定オッズ</th>' if fin else ''}<th class="r">配分（計{yen(total)}）</th>{'' if fin else '<th class="r">当たれば</th>'}<th class="r">AI確率</th></tr></thead><tbody>{rows}</tbody></table></div>
{f'<p>この配分なら、{e(r.get("at", ""))}時点のオッズで、どれが当たっても <b class="num">{yen(r["alloc_min_return"])}</b> 以上（実質 <b class="num">{r["alloc_min_return"] / total:.2f}倍</b>）。<span class="sub">締切直前は人気の目のオッズが下がりやすいので、購入直前のオッズで確かめてください。</span></p>' if r.get('alloc_min_return') and not res else ''}
{result}
<p class="sub">本線・押さえの中から、AIの確率が高い順に合成オッズが{r['rule']['min_comp']:g}倍を下回らない範囲で選び、AIの的中見込みが{r['rule']['confident_ai'] * 100:.0f}%以上、かつオッズから見た見込みの{r['rule'].get('confident_edge', 1):g}倍以上ある（市場よりAIが強く見ている）レースだけ「自信あり」として出しています（本線・押さえ以外の目は使いません）。合成オッズ ＝ 1 ÷（1/オッズ① ＋ 1/オッズ② ＋ …）。</p></section>"""

    def oriten_block(self, race):
        """展示の数字（公式の展示タイム＋各場のオリジナル展示データ）。各項目で速い順に順位をつける"""
        ot = race.get("oriten")
        bi = race.get("before") or {}
        ex = {str(b["frame"]): b.get("exhibit_time") for b in bi.get("boats", [])}
        if not ot and not any(ex.values()):
            return ""
        items = (["展示タイム"] if any(ex.values()) else []) + (ot["items"] if ot else [])
        cols = {}
        if any(ex.values()):
            cols["展示タイム"] = ex
        for i, it in enumerate(ot["items"] if ot else []):
            cols[it] = {f: (v[i] if i < len(v) else None) for f, v in ot["rows"].items()}
        rank = {}
        for it, col in cols.items():
            vals = sorted(v for v in col.values() if v)
            rank[it] = {f: (vals.index(v) + 1 if v else None) for f, v in col.items()}
        names = {str(b["frame"]): b.get("name", "") for b in (race.get("racelist") or {}).get("boats", [])}
        head = "".join(f'<th class="r">{e(it)}</th>' for it in items)
        rows = []
        for f in map(str, range(1, 7)):
            cells = []
            for it in items:
                v, r = cols[it].get(f), rank[it].get(f)
                cls = "best" if r == 1 else ("sub" if r and r >= 5 else "")
                cells.append(f'<td class="r num {cls}">{f"{v:.2f}" if v else "-"}<small class="sub">{f" {r}位" if r else ""}</small></td>')
            rows.append(f'<tr><td>{bt(int(f))} {e(names.get(f, ""))}</td>{"".join(cells)}</tr>')
        tops = []
        for it in items:
            best = [f for f, r in rank[it].items() if r == 1]
            if best:
                tops.append(f"{it}1位 {'・'.join(best)}号艇")
        note = "展示タイムは公式、一周・まわり足・直線などは各レース場が独自に計測したオリジナル展示データ（BOATCAST掲載）。数字が小さいほど速い。" if ot else "展示タイムは公式。数字が小さいほど速い。"
        return (f'<section class="panel"><h2>展示の数字 <small>{e("・".join(tops))}</small></h2>'
                f'<div class="tbl-wrap"><table><thead><tr><th>艇</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
                f'<p class="sub">{note}</p></section>')

    def worry_block(self, p):
        w = p.get("in_worry")
        if not w:
            return ""
        inb = next((b for b in p.get("boats", []) if b.get("course") == 1), {})
        att = next((b for b in p.get("boats", []) if b.get("frame") == w["attacker"]), {})
        rs = "".join(f"<li>{e(x)}</li>" for x in w.get("reasons", []))
        if w.get("by") == "fstart":
            return f"""<section class="panel worry lv1"><h2><span class="chip iw1">イン不安</span> {bt(inb.get('frame', 1))} {e(inb.get('name', ''))}のスタートに注意</h2>
<ul class="comments">{rs}</ul>
<p class="sub">過去2年、F持ちでF後のスタートが遅めの1コースは、同じ級別の選手と比べて1着率が6〜9ポイント低く（A1 72→66%、A2 60→51%、B1 41→33%）、決まり手は差しより<b>まくり</b>が増えます（まくり 15→22%）。3連単の配当の中央値も2,490円→3,120円と高めでした。</p></section>"""
        if w.get("by") == "exdrop":
            return f"""<section class="panel worry lv1"><h2><span class="chip iw1">イン不安</span> {bt(inb.get('frame', 1))} {e(inb.get('name', ''))}の足に注意</h2>
<ul class="comments">{rs}</ul>
<p class="sub">過去3年、インの展示タイムの順位がその選手のいつもの順位より3つ以上悪かったレース（1,614件）では、インの1着は<b>50.0%</b>（全レース55.7%）。オッズはそれでもインを52%前後と見ていて、実際（46%）より高く評価しがちでした（件数が少ないため参考）。</p></section>"""
        return f"""<section class="panel worry lv{w['level']}"><h2><span class="chip iw{w['level']}">イン不安</span> {bt(inb.get('frame', 1))} {e(inb.get('name', ''))}は逃げ切れない可能性</h2>
<ul class="comments">{rs}<li>一番かみ合う攻め手は {bt(att.get('frame', 0))} {e(att.get('name', ''))}（{att.get('course', '')}コース）。</li></ul>
<p class="sub">過去1年で同じ条件（インのコース成績が下位・攻め手がかみ合う）だったレース{w['hist_races']}件では、インの1着は<b>{pct(w['hist_in_win'])}</b>（全レースでは{pct(w['hist_all'])}）。
ただし3〜4回に1回はインが逃げていて、インを買い目から外すと的中・回収率とも下がったため、推奨買い目は確率どおりに組んでいます。外から狙うかどうかの判断材料にしてください。</p></section>"""

    def fstart_block(self, p):
        fs = p.get("fstart") or []
        if not fs:
            return ""
        li = []
        for j in fs:
            head = f'{bt(j["frame"])} {e(j["name"])}（F{j.get("f_count", 1)}・{j["course"]}コース）'
            if j.get("slow") is None:
                li.append(f"<li>{head}：F後にこのコースで走ったのは{j['n']}回で、判断できるほどのデータがありません。</li>")
                continue
            pre = f"（F前は平均ST {j['pre_st'] / 100:.2f}・{j['pre_rank']:.1f}番目）" if j.get("pre_n") else ""
            base = f"F後のこのコース{j['n']}走で平均ST {j['st'] / 100:.2f}・スタート順は平均{j['rank']:.1f}番目{pre}。"
            if j["slow"] and j["course"] == 1:
                tail = "スタートで後手を踏みやすく、イン逃げには不安があります。"
            elif j["slow"] and j["course"] < 6:
                tail = f"内から壁になりにくく、{j['course'] + 1}コースの攻めが決まりやすい形です。"
            elif j["slow"]:
                tail = "スタートは控えめですが、6コースから3着に残る分にはF持ちの影響は小さめです。"
            else:
                tail = "F後もスタートは遅れておらず、F持ちの影響は小さそうです。"
            li.append(f"<li>{head}：{base}{tail}</li>")
        return f"""<section class="panel"><h2>F持ちのスタート <small>フライング後、同じコースでのスタートの変化</small></h2>
<ul class="comments">{"".join(li)}</ul>
<p class="sub">過去2年の検証：F後のスタート順が平均4番目以降の選手が2・3コースにいると、すぐ外の艇の1着率が同じ級別の平均より1〜2ポイント高くなっていました。</p></section>"""

    @staticmethod
    def follow_line(t):
        """4コースの攻め方（過去の4コース勝ちの決まり手）から、5・6コースの連れ込み"""
        sty = t.get("style")
        if not sty or sty == "両方":
            return ""
        mk, ms = t.get("style_n", [0, 0])
        if sty == "まくり":
            return (f'<br>{t["att_name"]}は4コースで勝つときの多くがまくり（まくり{mk}回・まくり差し{ms}回）。まくり切ると外の5・6コースが連れて来やすく、'
                    f'<span class="sub">この形で4がまくり型だと「4が1着で5も3着内」が12.5%（全レース平均4.6%）、6の3着内も26.5%（平均22.0%）。4-5・4-6の筋に注意。</span>')
        return (f'<br>{t["att_name"]}は4コースで勝つときの多くがまくり差し（まくり{mk}回・まくり差し{ms}回）。内に切り込むため外の5・6は残りにくく、'
                f'<span class="sub">この形でまくり差し型だと6の3着内は19.3%（平均22.0%）。</span>')

    # ------------------------------------------------------------ スタート展示（スリット図）
    BOAT = {1: ("#F4F6F8", "#1B1B1B"), 2: ("#23272B", "#FFFFFF"), 3: ("#E0362C", "#FFFFFF"),
            4: ("#2566D0", "#FFFFFF"), 5: ("#F2D231", "#1B1B1B"), 6: ("#2E9D4E", "#FFFFFF")}

    @staticmethod
    def boat_svg(nx, wy, hull, ink, num):
        """横から見た競艇ボート（舳先の先端が nx、喫水線が wy）"""
        return (f'<g transform="translate({nx:.1f},{wy})">'
                # 引き波・しぶき
                f'<path d="M-118 1 q8 -5 16 0 t16 0 t16 0" stroke="rgba(170,220,255,.55)" stroke-width="2" fill="none"/>'
                f'<path d="M-92 -2 l-10 -7 M-94 1 l-14 -3 M-90 3 l-12 3" stroke="rgba(235,248,255,.8)" stroke-width="1.6" stroke-linecap="round"/>'
                # 船体
                f'<path d="M0 -5 L-12 -12 L-74 -13 L-80 -11 L-80 -2 L-62 1 L-12 1 Z" fill="{hull}" stroke="rgba(0,0,0,.55)" stroke-width="1"/>'
                f'<path d="M-14 -9 L-72 -9.5" stroke="{ink}" stroke-opacity=".55" stroke-width="1.4"/>'
                f'<path d="M-2 -3 L-60 -2" stroke="rgba(0,0,0,.35)" stroke-width="1"/>'
                # 艇番プレート
                f'<rect x="-66" y="-12" width="11" height="9" rx="1.5" fill="{ink}"/>'
                f'<text x="-60.5" y="-4.6" text-anchor="middle" font-size="8" font-weight="900" fill="{hull}">{num}</text>'
                # 選手（前かがみ）
                f'<path d="M-50 -13 C-47 -22 -38 -25 -30 -21 L-26 -15 Z" fill="{hull}" stroke="rgba(0,0,0,.55)" stroke-width="1"/>'
                f'<circle cx="-27" cy="-24" r="6" fill="{hull}" stroke="rgba(0,0,0,.6)" stroke-width="1"/>'
                f'<path d="M-25 -26 a4 3 0 0 1 4 3 l-5 1 z" fill="#15191D"/>'
                f'<path d="M-30 -18 L-18 -13" stroke="rgba(0,0,0,.6)" stroke-width="1.6" stroke-linecap="round"/>'
                # モーター
                f'<rect x="-92" y="-25" width="14" height="10" rx="3" fill="#2B3137" stroke="rgba(255,255,255,.2)"/>'
                f'<rect x="-88" y="-16" width="6" height="18" fill="#3A424A"/>'
                f'<path d="M-90 2 h10" stroke="#8A949E" stroke-width="2"/>'
                '</g>')

    def slit_block(self, race, link="", se=None, result=False):
        bi = race.get("before") or {}
        se = se if se is not None else (bi.get("start_exhibition") or [])
        if len(se) != 6:
            return ""
        ex = {} if result else {b["frame"]: b.get("exhibit_time") for b in bi.get("boats", [])}
        exst = {x["frame"]: x.get("st") for x in (bi.get("start_exhibition") or [])} if result else {}
        W, H, ROW, TOP = 360, 0, 44, 26
        SLIT, K = 252, 400          # スリット線の位置と、ST 0.01秒あたり5.2px
        rows = []
        for i, x in enumerate(sorted(se, key=lambda z: z["course"])):
            f, c, st, flag = x["frame"], x["course"], x.get("st"), x.get("flag") or ""
            y = TOP + i * ROW
            hull, ink = self.BOAT.get(f, ("#888", "#fff"))
            if st is None:
                nose, lab, col = SLIT - 190, "L" if flag == "L" else "-", "#FF4D4D"
            else:
                nose = SLIT - st * K
                lab = (f"F{abs(st):.2f}".replace("0.", ".") if st < 0 or flag == "F" else f"{st:.2f}".replace("0.", "."))
                col = "#FF4D4D" if (st < 0 or flag == "F") else "var(--ink)"
            nose = max(130, min(W - 64, nose))
            et = ex.get(f)
            rows.append(
                f'<g><rect x="0" y="{y}" width="{W}" height="{ROW}" fill="{"rgba(255,255,255,.025)" if i % 2 else "transparent"}"/>'
                f'<rect x="8" y="{y + 9}" width="26" height="26" rx="5" fill="{hull}" stroke="rgba(255,255,255,.25)"/>'
                f'<text x="21" y="{y + 28}" text-anchor="middle" font-size="16" font-weight="800" fill="{ink}">{c}</text>'
                + self.boat_svg(nose, y + 33, hull, ink, f)
                + f'<text x="{W - 12}" y="{y + 25}" text-anchor="end" font-size="17" font-weight="800" fill="{col}" class="num">{lab}</text>'
                + (f'<text x="{W - 12}" y="{y + 39}" text-anchor="end" font-size="10" fill="var(--ink2)">展示 {et}</text>' if et else "")
                + (f'<text x="{W - 12}" y="{y + 39}" text-anchor="end" font-size="10" fill="var(--ink2)">展示ST {exst[f]:.2f}</text>'.replace("0.", ".") if result and exst.get(f) is not None and exst[f] >= 0 else "")
                + (f'<text x="{W - 64}" y="{y + 25}" text-anchor="end" font-size="12" font-weight="700" fill="#F5C542">{e(x.get("note", ""))}</text>' if x.get("note") else "")
                + '</g>')
        H = TOP + 6 * ROW + 8
        svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="スタート展示のスリット" style="display:block;max-width:560px">'
               f'<rect x="0" y="0" width="{W}" height="{H}" rx="10" fill="#0E2A3B"/>'
               f'<text x="21" y="17" text-anchor="middle" font-size="10" fill="var(--ink2)">コース</text>'
               f'<text x="{SLIT}" y="17" text-anchor="middle" font-size="10" fill="#F5C542">スリット</text>'
               f'<text x="{W - 12}" y="17" text-anchor="end" font-size="10" fill="var(--ink2)">ST</text>'
               + "".join(rows) +
               f'<line x1="{SLIT}" y1="{TOP - 2}" x2="{SLIT}" y2="{H - 6}" stroke="#F5C542" stroke-width="2.5"/></svg>')
        if result:
            return f"""<div class="slit" style="margin-top:10px"><h3 style="margin:0 0 6px;font-size:14px">本番のスタート <small class="sub">右ほど早い・黄色は決まり手</small></h3>{svg}</div>"""
        return f"""<section class="panel slit"><h2>スタート展示 <small>艇の位置＝スタートの早さ（右ほど早い）</small></h2>{svg}
<p class="sub">黄色い線がスタートライン。展示（本番前のリハーサル）で線を越えるのが早かった艇ほど右にいます。赤字のFは展示でのフライング（本番ではありません）。</p>
<p style="margin:0"><a href="{link}">この6人の「展示ST → 本番ST」のくせを見る →</a></p></section>"""

    # ------------------------------------------------------------ 1周1マークの展開イメージ（上から見た図）
    DEFAULT_MOVE = {2: "差し", 3: "まくり", 4: "まくり", 5: "まくり差し", 6: "展開待ち"}

    def turn_block(self, race, p):
        pb = p.get("boats") or []
        if len(pb) != 6:
            return ""
        bi = race.get("before") or {}
        st = {x["frame"]: x.get("st") for x in bi.get("start_exhibition") or []}
        csb = (p.get("course_stats") or {}).get("boats", {})
        boats = sorted(pb, key=lambda b: b["course"])
        top = max(pb, key=lambda b: b.get("p_win", 0))
        # スタート順（展示）
        valid = sorted((v, f) for f, v in st.items() if v is not None)
        srank = {f: i + 1 for i, (v, f) in enumerate(valid)}
        moves = {}
        for b in boats:
            f, c = b["frame"], b["course"]
            if c == 1:
                moves[f] = "逃げ"
                continue
            k = (csb.get(str(f)) or csb.get(f) or {}).get("kimarite") or {}
            cand = {m: k.get(m, 0) for m in ("差し", "まくり", "まくり差し")}
            mv = max(cand, key=cand.get) if sum(cand.values()) >= 2 else self.DEFAULT_MOVE[c]
            if c == 6 and sum(cand.values()) < 2:
                mv = "展開待ち"
            if srank.get(f, 3) >= 5 and mv != "差し":
                mv = "展開待ち"      # 展示でスタートが遅い艇は攻めきれない
            moves[f] = mv
        W, H = 360, 236
        MX, MY = 300, 46            # 1マーク
        SL = 146                    # スタートライン
        lanes = {b["frame"]: 84 + (b["course"] - 1) * 24 for b in boats}

        def bx(f):                  # 舳先の位置：展示STが早いほど前
            v = st.get(f)
            v = 0.15 if v is None else max(v, 0)
            return max(118, SL + 20 - v * 200)

        def path(mv, x, y):
            if mv == "逃げ":
                return f"M{x} {y} L{MX - 40} {y} C{MX - 6} {y}, {MX + 22} {MY + 10}, {MX + 10} {MY - 16} S{MX - 50} {MY - 32}, {MX - 90} {MY - 30}"
            if mv == "差し":
                return f"M{x} {y} L{MX - 70} {y} C{MX - 40} {y}, {MX - 30} {MY + 22}, {MX - 56} {MY + 8} S{MX - 100} {MY - 4}, {MX - 130} {MY - 4}"
            if mv == "まくり":
                return f"M{x} {y} L{MX - 60} {y} C{MX + 20} {y}, {MX + 46} {MY + 20}, {MX + 30} {MY - 26} S{MX - 50} {MY - 44}, {MX - 100} {MY - 40}"
            if mv == "まくり差し":
                return f"M{x} {y} L{MX - 60} {y} C{MX + 10} {y}, {MX + 16} {MY + 40}, {MX - 30} {MY + 22} S{MX - 90} {MY + 14}, {MX - 120} {MY + 14}"
            return f"M{x} {y} L{MX - 40} {y} C{MX + 20} {y}, {MX + 44} {y - 20}, {MX + 44} {y - 50}"

        g, lab = [], []
        for b in reversed(boats):
            f, c = b["frame"], b["course"]
            x, y = bx(f), lanes[f]
            hull, ink = self.BOAT.get(f, ("#888", "#fff"))
            line = "#AEB8C2" if f == 2 else hull
            strong = f == top["frame"]
            g.append(f'<path d="{path(moves[f], x, y)}" fill="none" stroke="{line}" stroke-width="{3.4 if strong else 2}" stroke-opacity="{1 if strong else 0.6}" '
                     f'stroke-dasharray="{"none" if strong else "5 5"}" stroke-linecap="round"/>')
        for b in boats:
            f, c = b["frame"], b["course"]
            x, y = bx(f), lanes[f]
            hull, ink = self.BOAT.get(f, ("#888", "#fff"))
            g.append(f'<g transform="translate({x},{y})"><path d="M0 0 L-10 -6 L-30 -6 L-30 6 L-10 6 Z" fill="{hull}" stroke="rgba(0,0,0,.6)"/>'
                     f'<circle cx="-17" cy="0" r="3.4" fill="#15191D" stroke="rgba(255,255,255,.55)" stroke-width=".8"/>'
                     f'<rect x="-35" y="-3" width="5" height="6" fill="#3A424A"/></g>')
            lab.append(f'<rect x="8" y="{y - 9}" width="18" height="18" rx="4" fill="{hull}" stroke="rgba(255,255,255,.25)"/>'
                       f'<text x="17" y="{y + 4.5}" text-anchor="middle" font-size="12" font-weight="800" fill="{ink}">{c}</text>'
                       f'<text x="31" y="{y + 4}" font-size="11" font-weight="700" fill="var(--ink)">{moves[f]}</text>')
        svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="1周1マークの展開イメージ" style="display:block;max-width:560px">'
               f'<rect width="{W}" height="{H}" rx="10" fill="#0E2A3B"/>'
               f'<line x1="{SL}" y1="70" x2="{SL}" y2="{H - 16}" stroke="#F5C542" stroke-width="1.5" stroke-dasharray="3 4"/>'
               f'<text x="{SL}" y="{H - 5}" text-anchor="middle" font-size="9" fill="#F5C542">スタートライン</text>'
               + "".join(g) + "".join(lab) +
               f'<circle cx="{MX}" cy="{MY}" r="9" fill="#FF7A2F" stroke="#fff" stroke-width="2"/>'
               f'<text x="{MX + 16}" y="{MY + 4}" font-size="10" fill="var(--ink)">1マーク</text></svg>')
        return f"""<section class="panel"><h2>1周1マークの展開イメージ <small>展示のスタートと、各選手がそのコースでよく決める形から</small></h2>{svg}
<p class="sub">実線がAIの1着予想（{bt(top["frame"])} {e(top.get("name", ""))}）、点線がほかの艇の動きの目安です。「差し」は内をすくう、「まくり」は外から一気に抜く、「まくり差し」は外から内に切り込む動き。展示でスタートが遅かった艇は「展開待ち」にしています。あくまでイメージで、実際のレースとは異なります。</p></section>"""

    def ana_block(self, race, p):
        a = p.get("ana_pick")
        if not a:
            return ""
        o = (race.get("odds_pre") or {}).get("v")
        def od(c):
            if not o:
                return ""
            j = next((i for i, x in enumerate(COMBO_LIST) if x == c), None)
            return f'<b class="odds">{o[j]}倍</b>' if j is not None and o[j] else ""
        res = race["result"] if race.get("result", {}).get("finished") else None
        hit = ""
        if res:
            h = res["trifecta"] in a["bets"]
            hit = f'<p><span class="pill {"hit" if h else "miss"}">{"的中" if h else "不的中"}</span> 結果 {combo(res["trifecta"])} {yen(res["trifecta_payout"])}</p>'
        cells = "".join(f'<span class="bet">{combo(c)}{od(c)}</span>' for c in a["bets"])
        return f"""<section class="panel ana"><h2><span class="chip an">高回収狙い</span> {bt(a["frame"])} {e(a["name"])}の頭 <small>検証中</small></h2>
<p>5コースの{e(a["name"])}は展示タイムが4コースより<b>{a["gap"]:.2f}秒</b>速く、外から一気に行ける足があります。頭固定・相手はAIの3着内上位3艇で{len(a["bets"])}点。</p>
<div class="bets">{cells}</div>{hit}
<p class="sub">過去1年、5コースが4コースより0.15秒以上速かった{a["n"]}レースでは、5の1着が{pct(a["win"])}（オッズの見込み{pct(a["mkt"])}）。前半・後半に分けてもどちらも頭の回収率が100%を超えていましたが、件数が少なく偶然の可能性もあるため「検証中」です。成績は実績ページで別に集計します。</p></section>"""

    @staticmethod
    def slip_body(p, cells):
        b = p["bets"]
        if b.get("mode") == "honmei" and p.get("honmei_pick"):
            hp = p["honmei_pick"]
            return (f'<div class="bet-group"><span>本命</span><div class="bets">{cells(b["main"])}</div></div>'
                    f'<p class="sub" style="margin:4px 0 0">固いレース：イン{bt(hp["in"])}の1着{pct(hp["p_in"])}、逃げたときの2着は{bt(hp["axis"])}が{pct(hp["p_axis"])}。3着も上位3艇に絞って3点（{"".join(bt(x) for x in hp.get("cut", []))}は切り）。人気ではなくAIの確率で選んでいて、3点の合成オッズが2.5倍以上あるときだけ出します。</p>')
        out = f'<div class="bet-group"><span>本線</span><div class="bets">{cells(b["main"])}</div></div>'
        if b.get("sub"):
            out += f'<div class="bet-group"><span>押さえ</span><div class="bets">{cells(b["sub"])}</div></div>'
        if b.get("mode") == "honmei_cheap":
            out += '<p class="sub" style="margin:4px 0 0">固い形ですが、3点に絞ると合成オッズが2.5倍未満で妙味がないため、いつもの6点にしています。</p>'
        if b.get("noko"):
            out += f'<p class="sub" style="margin:4px 0 0">残し：{e(b["noko"])}。</p>'
        if b.get("mode") == "attack" and b.get("attack"):
            out += f'<p class="sub" style="margin:4px 0 0">攻め：{e(b["attack"])}を入れています。</p>'
        return out

    def honmei_block(self, race, p, res):
        hp = p.get("honmei_pick")
        if not hp or p.get("stage") != "直前":
            return ""
        hk = race.get("honmei") or {}
        od = hk.get("odds") or {}
        cells = "".join(f'<span class="bet">{combo(c)}{f"<b class=odds>{od[c]}倍</b>" if od.get(c) else ""}</span>' for c in hp["bets"])
        comp = f'合成オッズ <b class="num">{hk["comp"]:.2f}倍</b>（{e(hk.get("at", ""))}時点）' if hk.get("comp") else "合成オッズは締切35分前から表示"
        hit = ""
        if res:
            h = res["trifecta"] in hp["bets"]
            hit = f'<p><span class="pill {"hit" if h else "miss"}">{"的中" if h else "不的中"}</span> 結果 {combo(res["trifecta"])} {yen(res["trifecta_payout"])}</p>'
        cut = "".join(bt(x) for x in hp.get("cut", []))
        return f"""<section class="panel honmei"><h2><span class="chip hm">厳選本命</span> {bt(hp["in"])}-{bt(hp["axis"])}-{"".join(bt(x) for x in hp["thirds"])} <small>{len(hp["bets"])}点</small></h2>
<ul class="checks"><li>✅ イン逃げが堅い：{bt(hp["in"])} {e(hp["in_name"])}の1着 {pct(hp["p_in"])}（AI）</li>
<li>✅ 逃げたときの2着の軸：{bt(hp["axis"])} {e(hp["axis_name"])}（{hp["axis_course"]}コース）が {pct(hp["p_axis"])}</li>
<li>✅ 3着は上位{len(hp["thirds"])}艇に絞り、{cut}は切り</li></ul>
<p>{comp}</p><div class="bets">{cells}</div>{hit}
<p class="sub">過去約9,000レースの検証では、この条件（イン1着70%以上・2着の軸45%以上）は1日5レース前後・的中率38%・回収率81%（日を分けても80〜81%）。全レースの本線・押さえと回収率は同じくらいで、点数は3点です。成績は実績ページで集計します。</p></section>"""

    def tsuke_block(self, race, p, res):
        tp = p.get("tsuke_pick")
        if not tp:
            return ""
        tk = race.get("tsuke") or {}
        if tk and not tk.get("active"):
            return (f'<section class="panel"><p class="sub" style="margin:0"><span class="chip tk">厳選穴</span> 見送り：{bt(tp["frame"])} {e(tp["name"])}のツケマイの形はありますが、'
                    f'オッズがインの1着を{tk.get("in_mkt", 0) * 100:.0f}%と見ていて（45%以上）、この形で外を買っても回収できていない条件です。</p></section>')
        od = tk.get("odds") or {}
        cells = "".join(f'<span class="bet">{combo(c)}{f"<b class=odds>{od[c]}倍</b>" if od.get(c) else ""}</span>' for c in tp["bets"])
        comp = (f'合成オッズ <b class="num">{tk["comp"]:.2f}倍</b>（{e(tk.get("at", ""))}時点）・インの1着の見込み（オッズ）{tk["in_mkt"] * 100:.0f}%' if tk.get("comp")
                else "締切35分前にオッズを見て最終判定（インが売れすぎていたら見送り）")
        hit = ""
        if res:
            h = res["trifecta"] in tp["bets"]
            hit = f'<p><span class="pill {"hit" if h else "miss"}">{"的中" if h else "不的中"}</span> 結果 {combo(res["trifecta"])} {yen(res["trifecta_payout"])}</p>'
        pre = "" if p.get("stage") == "直前" else '<p class="sub">※展示前の判定です。展示後に条件が崩れると消えます（成績は展示後に残ったレースだけで集計）。</p>'
        return f"""<section class="panel tsuke"><h2><span class="chip tk">厳選穴</span> {bt(tp["frame"])} {e(tp["name"])}（{tp["course"]}コース）のまくり <small>条件がすべてそろったレース</small></h2>
<ul class="checks">{"".join(f"<li>✅ {e(w)}</li>" for w in tp["why"])}<li>✅ オッズがインを信じすぎていない（締切前に判定）</li></ul>
<p>{"まくり切ったときにイン（" + bt(tp["in"]) + " " + e(tp["in_name"]) + "）ごと沈めやすい形。" if tp.get("kind", "tsuke") == "tsuke" else "外から一気に叩ける足。決まればインは残りにくい形。"}<b>頭固定の{len(tp["bets"])}点</b>。2・3着は「AIの確率（各選手の勝率・コース別の2・3着率・展示タイム・モーター）」×「まくりで決まったときに来やすい並び」で選んでいます（筋目の決め打ちではありません）。<br>{comp}</p>
<div class="bets">{cells}</div>{hit}{pre}
<p class="sub">5つの条件がすべてそろったレースだけを出しています（1日2レース前後）。過去約9,000レースの検証では、条件を重ねるほど回収率が上がり（2つ65%→3つ84%→4つ92%→5つ97%）、的中率は約20%でした。100%を約束するものではありません。成績は実績ページで集計します。</p></section>"""

    @staticmethod
    def second_line(c):
        if c != 4:
            return ""
        return ('<span class="sub">スリットの形で出目が変わります（過去3年・実際のスタート）。'
                '<b>4が3を叩いた</b>（4が3より0.05以上早く、内より早い・2.4万レース）：4の1着33%、4が勝つと2着は5が33%・1が28%で3は10%。'
                '4-156-156が15.1%、1-4-256が7.8%、裏目の5-146-146が6.0%。'
                '<b>3が先に出た</b>（1.1万レース）：4の1着は8%しかなく、4が勝っても2着は3が36%（3が内を叩いて、4がまくり差しで続く4-3の形）。'
                '事前に「どちらの形になるか」は、平均スタート順と展示STを使っても当たるのは3回に1回ほどです。</span>')

    def tenkai_block(self, p):
        tk = p.get("tenkai") or []
        if not tk:
            return ""
        li = []
        for t in tk:
            if t.get("type") == "motor":
                extra = f"前節は{t['last_n']}走でまくり・まくり差しの1着{t['last_makuri']}回。" if t.get("last_makuri") else ""
                li.append(f'<li>{bt(t["frame"])} {e(t["name"])}の<b>{t["motor_no"]}号機</b>：{"、".join(e(x) for x in t["reasons"])}。'
                          f'<span class="sub">このモーターの直近{t["n"]}走で1着{t["win"]}回（うちまくり系{t["makuri"]}回）。{extra}モーターの数字は乗り手の実力も混ざるので、参考程度に。</span></li>')
                continue
            if t.get("type") == "resist":
                ws = "・".join(f"{c}コース{pct(v)}" for c, v in t["wins"].items())
                if t["style"] == "飛び付き":
                    body = (f'インの{bt(t["in"])} {e(t["in_name"])}は<b>飛び付き型</b>（インで負けた{t["beaten"]}回のうち{t["out"]}回が4着以下）。'
                            f'{t["att_course"]}コースの{bt(t["att"])} {e(t["att_name"])}はスタートが早く、攻められると抵抗して共倒れになりやすい形。')
                else:
                    body = (f'インの{bt(t["in"])} {e(t["in_name"])}は<b>残す型</b>（インで負けても{t["beaten"] - t["out"]}/{t["beaten"]}回は2〜3着）。'
                            f'{t["att_course"]}コースの{bt(t["att"])} {e(t["att_name"])}に攻められても無理に抵抗せず、着に残しにくる形。')
                li.append(f'<li>{body}<span class="sub">過去2年、{t["att_course"]}コースがスタートの早い選手でこのタイプのイン（{t["n"]:,}レース）：インの1着{pct(t["in_win"])}・4着以下{pct(t["in_out"])}、1着は{ws}、配当の中央値{t["pay"]:,}円。</span></li>')
                continue
            if t.get("type") == "exgap":
                li.append(f'<li>{bt(t["frame"])} {e(t["name"])}（{t["course"]}コース）は展示タイムが内の{bt(t["inner"])} {e(t["inner_name"])}より<b>{t["gap"]:.2f}秒</b>速い。足で内を叩ける形で、<b>まくり</b>が決まりやすくなります。'
                          f'<span class="sub">過去1年、{t["course"]}コースが内より0.10秒以上速いとき（{t["n"]}回）の1着は{pct(t["win"])}（通常{pct(t["base_win"])}）、まくりで勝ったのは{pct(t["makuri"])}（通常{pct(t["base_makuri"])}）。</span></li>')
                continue
            if t.get("type") == "tilt":
                over = "オッズではそれ以上に売れやすく、頭で買うなら妙味は薄め" if t["mkt"] > t["win"] else "オッズの評価とほぼ同じ"
                li.append(f'<li>{bt(t["frame"])} {e(t["name"])}（{t["course"]}コース）はチルト<b>{t["tilt"]:+.1f}</b>の伸び型。スタート後の伸びで一気に攻める形があります。'
                          f'<span class="sub">過去1年、{t["course"]}コースでチルト1.0以上（{t["n"]}回）の1着は{pct(t["win"])}（通常{pct(t["base_win"])}）、3着内は{pct(t["top3"])}（通常{pct(t["base_top3"])}）。{over}（オッズの見込み{pct(t["mkt"])}）。</span></li>')
                continue
            wall = f'{bt(t["wall"])} {e(t["wall_name"])}（{t["wall_course"]}コース）は最近のスタートが平均{t["wall_rank"]:.1f}番手' + ("、しかもF持ちでF後はさらに慎重" if t["wall_f"] else "")
            wb_ = t.get("wall_beaten")
            if wb_ and wb_[0] >= 15:
                wall += f"。{t['wall_course']}コースのとき{t['att_course']}コースに勝たれた率は{wb_[1] / wb_[0] * 100:.0f}%（{wb_[0]}走・うちまくり{wb_[2]}回）"
            att = f'{bt(t["att"])} {e(t["att_name"])}（{t["att_course"]}コース）は平均{t["att_rank"]:.1f}番手と早い'
            li.append(f'<li>{wall}。{att}。<b>{t["att_course"]}コースのまくり展開</b>があります。'
                      f'<span class="sub">過去2年この形（{t["n"]:,}レース）では{t["att_course"]}コースの1着が{pct(t["win"])}（通常{pct(t["base_win"])}）、まくりで勝ったのは{pct(t["makuri"])}（通常{pct(t["base_makuri"])}）。</span>'
                      + self.follow_line(t) + self.second_line(t["att_course"]) + '</li>')
        return f"""<section class="panel"><h2>展開メモ <small>スタートの早さ・チルトから見た展開</small></h2>
<ul class="comments">{"".join(self.shorten(x) for x in li)}</ul></section>"""

    @staticmethod
    def shorten(li):
        """小さい字の根拠データは「データを見る」に畳む（本文は太字の結論だけ）"""
        import re as _re
        subs = _re.findall(r'<span class="sub">.*?</span>', li, flags=_re.S)
        if not subs:
            return li
        body = li
        for x in subs:
            body = body.replace(x, "")
        body = body.replace("</li>", "")
        det = "".join("<p>" + x[len('<span class="sub">'):-len("</span>")] + "</p>" for x in subs)
        return f'{body}<details class="more"><summary>データを見る</summary>{det}</details></li>'

    def result_block(self, d, race, p, res, page):
        """レース結果（出走表のすぐ下）。締切後で結果待ちなら、その旨だけ出す。"""
        if not res:
            dl = race.get("deadline") or ""
            if dl and d == self.idx.get("date") and dl <= self.now.strftime("%H:%M"):
                return ('<section class="panel result"><h2>レース結果</h2><p class="sub" style="margin:0">締切済み。結果は締切の15分後ごろに反映します（5分ごとに自動更新）。</p></section>')
            return ""
        names = {b["frame"]: b.get("name", "") for b in (race.get("racelist") or {}).get("boats", [])}
        order = res.get("order") or []
        if not order and res.get("trifecta"):
            order = [{"place": str(i + 1), "frame": int(x), "name": names.get(int(x), ""), "time": ""} for i, x in enumerate(res["trifecta"].split("-"))]
        orows = "".join(f'<tr><td class="num">{e(o["place"])}</td><td>{bt(o["frame"])}</td><td>{e(o["name"] or names.get(o["frame"], ""))}</td><td class="r num sub">{e(o.get("time", ""))}</td></tr>' for o in order)
        nk = res.get("trifecta_ninki")
        pay = res.get("trifecta_payout") or 0
        man = ' man' if pay >= 10000 else ''
        pays = (f'<div class="rpay"><span>3連単</span>{combo(res["trifecta"])}<b class="num{man}">{yen(res.get("trifecta_payout"))}</b><span class="sub">{f"{nk}番人気" if nk else ""}</span></div>')
        if res.get("exacta"):
            pays += f'<div class="rpay"><span>2連単</span>{combo(res["exacta"])}<b class="num">{yen(res.get("exacta_payout"))}</b><span></span></div>'
        if res.get("win"):
            pays += f'<div class="rpay"><span>単勝</span>{combo(res["win"])}<b class="num">{yen(res.get("win_payout"))}</b><span></span></div>'
        extra = []
        if res.get("kimarite"):
            extra.append(f'決まり手 <b>{e(res["kimarite"])}</b>')
        if res.get("refunded"):
            extra.append("返還 " + "".join(bt(x) for x in res["refunded"]))
        # 予想との答え合わせ
        bets = p.get("bets") or {}
        t = res["trifecta"]
        marks = []
        for key, lab in (("main", "本線"), ("sub", "押さえ"), ("ana", "穴")):
            if key == "ana" and not bets.get("ana_reason"):
                continue
            if bets.get(key):
                h = t in [b["combo"] for b in bets[key]]
                marks.append(f'<span class="pill {"hit" if h else "miss"}">{lab} {"的中" if h else "×"}</span>')
        rc = race.get("reco") or {}
        if rc.get("verdict") == "自信あり" and "r_hit" in race:
            marks.append(f'<span class="pill {"hit" if race["r_hit"] else "miss"}">自信あり {"的中" if race["r_hit"] else "×"}</span>')
        if "h_hit" in race:
            marks.append(f'<span class="pill {"hit" if race["h_hit"] else "miss"}">厳選本命 {"的中" if race["h_hit"] else "×"}</span>')
        if "t_hit" in race:
            marks.append(f'<span class="pill {"hit" if race["t_hit"] else "miss"}">穴狙い {"的中" if race["t_hit"] else "×"}</span>')
        if "a_hit" in race:
            marks.append(f'<span class="pill {"hit" if race["a_hit"] else "miss"}">高回収狙い {"的中" if race["a_hit"] else "×"}</span>')
        exh = '<p class="sub" style="margin:4px 0 0">' + "　".join(extra) + "</p>" if extra else ""
        mkh = '<div class="rmarks">' + "".join(marks) + "</div>" if marks else ""
        return (f'<section class="panel result"><h2>レース結果 <small><a href="{page.u(f"results/{d}.html")}">{jdate(d)}の払戻金一覧 →</a></small></h2>'
                f'<div class="rres"><div class="tbl-wrap"><table class="rorder"><thead><tr><th>着</th><th>枠</th><th>選手</th><th class="r">タイム</th></tr></thead><tbody>{orows}</tbody></table></div>'
                f'<div class="rpays">{pays}{exh}{mkh}</div></div>{self.slit_block(race, se=res.get("start") or [], result=True)}</section>')

    def race_page(self, d, jcd, race):
        rno = race["rno"]
        v = VENUES[jcd]["name"]
        page = Page(f"race/{d}/{SLUG[jcd]}-{rno}.html")
        p = race.get("prediction") or {}
        rl = race.get("racelist") or {"boats": []}
        bi = race.get("before") or {}
        res = race["result"] if race.get("result", {}).get("finished") else None
        bmap = {b["frame"]: b for b in rl["boats"]}
        pb = {b["frame"]: b for b in p.get("boats", [])}
        cs = (p.get("course_stats") or {}).get("boats", {})
        tilts = {bb["frame"]: bb.get("tilt") for bb in bi.get("boats", [])}
        rows = []
        for f in range(1, 7):
            b, q = bmap.get(f, {}), pb.get(f, {})
            name = b.get("name", "")
            link = self.racer_link(page, b.get("toban", ""))
            if link:
                link += f"#c{q.get('course', f)}"
            nm = f'<a href="{link}">{e(name)}</a>' if link else e(name)
            c = cs.get(str(f)) or cs.get(f) or {}
            fl = f' <span class="pill lv1">F{b["f"]}</span>' if b.get("f") else ""
            tl = tilts.get(f)
            if tl is not None and tl >= 1.0:
                fl += f' <span class="pill tilt">伸び型 チルト{tl:+.1f}</span>'
            nk = next((x for x in p.get("nokoshi") or [] if x["frame"] == f), None)
            if nk:
                fl += f' <span class="pill noko" title="{nk["course"]}コースでイン逃げのとき2・3着に残った率（{nk["n"]}走・平均{nk["base"] * 100:.0f}%）">逃げ残し{nk["rate"] * 100:.0f}%</span>'
            rows.append(f'<tr><td>{bt(f)}</td><td><strong>{nm}</strong> <span class="sub">{e(b.get("class", ""))} {e(b.get("branch", ""))}</span>{fl}</td>'
                        f'<td class="r num">{q.get("course", f)}</td><td class="r num">{b.get("nat_win") or "-"}</td><td class="r num">{b.get("loc_win") or "-"}</td><td class="r num">{b.get("motor_2") or "-"}</td>'
                        f'<td class="r num">{q.get("exhibit_time") or "-"}</td><td class="r num">{pct(c.get("win"))}<span class="sub">/{c.get("starts", 0)}走</span></td>'
                        f'<td class="r num">{pct(q.get("p_win"))}</td><td class="r num">{pct(q.get("p_top3"))}</td></tr>')
        w = bi.get("weather") or {}
        wind = p.get("wind") or {}
        comments = "".join(f"<li>{e(c)}</li>" for c in p.get("comments", []))
        ai_rows = ""
        if p.get("bets"):
            o = race.get("odds_pre") or {}

            def odds_of(c):
                if not o.get("v"):
                    return None
                a, b2, c2 = map(int, c.split("-"))
                rest = [x for x in range(1, 7) if x != a]
                pairs = [(x, y) for x in rest for y in rest if x != y]
                return o["v"][(a - 1) * 20 + pairs.index((b2, c2))]

            def cells(arr):
                out = []
                for x in arr:
                    o_ = odds_of(x["combo"])
                    oh = f'<b class="odds">{o_}倍</b>' if o_ else ""
                    out.append(f'<span class="bet">{combo(x["combo"])}{oh}<small>AI {pct(x["p"], 1)}</small></span>')
                return "".join(out)

            hitp = ""
            if res:
                hitp = f'<span class="pill {"hit" if race.get("hit") else "miss"}">{"的中" if race.get("hit") else "不的中"}</span> '
            ai_rows = f"""<section class="slip"><div class="slip-h"><b>{hitp}予想（本線・押さえ）</b><span>{e(p.get('confidence', {}).get('label', ''))}・{e(p.get('stage', ''))}予想{'・オッズ ' + e(o.get('at', '')) + '時点' if o.get('at') else ''}</span></div>
<div class="slip-b">{self.slip_body(p, cells)}
{f'<div class="bet-group"><span>穴</span><div class="bets">{cells(p["bets"]["ana"])}</div></div><p class="sub" style="margin:4px 0 0">穴：{e(p["bets"]["ana_reason"])}の艇の頭を2点だけ（的中の見込みは低めですが、決まれば高配当）。</p>' if p['bets'].get('ana_reason') and p['bets'].get('ana') else ''}</div></section>"""
        inp = (p.get("course_stats") or {}).get("in")
        loss = ""
        if inp and inp.get("starts"):
            loss = "".join(f'<tr><td>{k}</td><td class="r num">{pct(inp["loss"].get(k, 0))}</td><td class="r num sub">{pct(inp["nat_loss"].get(k, 0))}</td></tr>' for k in ("差され", "捲られ", "捲り差され", "その他"))
            loss = f'<section class="panel"><h2>1コースの負け方 <small>直近1年・{inp["starts"]}走・逃げ率 {pct(inp["escape"])}（全国 {pct(inp["nat_escape"])}）</small></h2><div class="tbl-wrap"><table><thead><tr><th></th><th class="r">この選手</th><th class="r">全国</th></tr></thead><tbody>{loss}</tbody></table></div></section>'
        title = f"{v}{rno}R 予想・オッズ・展示｜{jdate(d)}｜{SITE_NAME}"
        desc = f"{jdate(d)}のボートレース{v} {rno}R（締切{race.get('deadline', '')}）の推奨買い目、合成オッズ、展示タイム、選手のコース別成績、結果。"
        vp = Page(page.path)
        body = f"""<section class="race-head"><div><span class="eyebrow">{e(v)} · {jdate(d)} · {e(race.get('race_name', ''))}</span>
<h1 data-dl="{race.get('date', '')} {e(race.get('deadline', ''))}">{e(v)} {rno}R 予想 <span class="sub num" style="font-size:14px">締切 {e(race.get('deadline', ''))}</span></h1></div></section>
<div class="race-grid"><div style="display:grid;gap:16px;min-width:0">
<nav class="rtabs" role="tablist"><button data-t="yoso" role="tab">出走表・予想</button><button data-t="odds" role="tab">オッズ</button><button data-t="kekka" role="tab">結果{'' if res else ' <small>待ち</small>'}</button></nav>
<div class="tabp" data-p="yoso" style="display:grid;gap:16px;min-width:0">
{'' if rl['boats'] else '<section class="panel"><p style="margin:0">出走表はまだ取り込んでいません。締切の2時間前ごろから、予想・展示・オッズの順に自動で表示されます。</p></section>'}
<section style="display:grid;gap:8px"><h2>出走表と予想 <small>進入 {''.join(bt(x) for x in p.get('entry', []))}{' 進入変化あり' if p.get('entry_changed') else ''}</small></h2>
<div class="panel tbl-wrap" style="padding:4px 8px"><table><thead><tr><th>枠</th><th>選手</th><th class="r">コース</th><th class="r">全国勝率</th><th class="r">当地</th><th class="r">モーター2連</th><th class="r">展示T</th><th class="r">このコースの1着率</th><th class="r">1着確率</th><th class="r">3着内</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
{self.slit_block(race, page.u(f'race/{d}/{SLUG[jcd]}-{rno}-st.html'))}
{self.oriten_block(race)}
{ai_rows}
{self.tsuke_block(race, p, res)}
{self.ana_block(race, p)}
{self.worry_block(p)}
{self.tenkai_block(p)}
{self.fstart_block(p)}
{loss}
{f'<section class="panel"><h2>見立て</h2><ul class="comments">{comments}</ul></section>' if comments else ''}
</div>
<div class="tabp" data-p="odds" style="display:grid;gap:16px;min-width:0" hidden>
{self.reco_block(race, res) or '<section class="panel"><p class="sub" style="margin:0">オッズは締切35分前から表示します。</p></section>'}
<section id="live" class="panel" hidden></section>
<section id="pick" class="panel" hidden></section>
</div>
<div class="tabp" data-p="kekka" style="display:grid;gap:16px;min-width:0" hidden>
{self.result_block(d, race, p, res, page) or '<section class="panel"><p class="sub" style="margin:0">レースが終わると、着順・払戻・本番のスタートをここに表示します（締切の15分後ごろ）。</p></section>'}
</div>
<script>(function(){{var bs=document.querySelectorAll('.rtabs button'),ps=document.querySelectorAll('.tabp');
function sh(t){{bs.forEach(function(b){{b.classList.toggle('on',b.dataset.t===t);b.setAttribute('aria-selected',b.dataset.t===t)}});ps.forEach(function(x){{x.hidden=x.dataset.p!==t}});try{{history.replaceState(null,'','#'+t)}}catch(e){{}}}}
bs.forEach(function(b){{b.onclick=function(){{sh(b.dataset.t)}}}});var h=(location.hash||'').slice(1);sh(['yoso','odds','kekka'].indexOf(h)>=0?h:'{'kekka' if res else 'yoso'}')}})()</script>

</div>
<aside class="panel" style="display:grid;gap:6px"><h2>水面気象 <small>{e(w.get('as_of', '') or '展示前')}</small></h2>
<div class="wx"><div><small>風</small><b>{e(wind.get('type', '-'))}</b></div><div><small>風速</small><b>{w.get('wind_speed', '-')}m</b></div><div><small>波高</small><b>{w.get('wave_cm', '-')}cm</b></div>
<div><small>天候</small><b style="font-family:var(--body)">{e(w.get('weather', '-') or '-')}</b></div><div><small>気温</small><b>{w.get('air_temp', '-')}℃</b></div><div><small>水温</small><b>{w.get('water_temp', '-')}℃</b></div></div>
<p class="sub"><a href="{vp.u('venue/' + SLUG[jcd] + '.html')}">{e(v)}の水面の特徴とコース別成績 →</a></p>
<div class="ad-slot" data-slot="race_side"></div></aside></div>"""
        live = {"date": d, "jcd": jcd, "rno": rno, "deadline": race.get("deadline", ""),
                "bets": [b["combo"] for b in (race.get("reco") or {}).get("bets", [])] if (race.get("reco") or {}).get("verdict") == "自信あり" else [], "targets": self.targets_in(jcd, rno) if d == self.idx.get("date") else [],
                "odds": (race.get("odds_pre") or {}).get("v"), "odds_at": (race.get("odds_pre") or {}).get("at", ""),
                "p3": (race.get("prediction") or {}).get("p3")}
        script = f'<script>window.__RACE__={json.dumps(live)};</script><script src="{page.u("live.js")}"></script><script src="{page.u("pick.js")}"></script>'
        if not res:
            script += "<script>setTimeout(function(){location.reload()},300000)</script>"
        self.put(page.path, page.render(title, desc, body, [(f"venue/{SLUG[jcd]}.html", v), ("", f"{rno}R")], script=script))

    # ------------------------------------------------------------ トップ
    def race_rows(self, page, d, jcd, races):
        rows = []
        for r in races:
            rc = r.get("reco")
            gachi = bool(rc and rc["verdict"] == "購入非推奨")
            tg = self.targets_in(jcd, r["rno"])
            if rc:
                # 狙い目は「推奨買い目に入っている艇」だけ出す（買い目と言うことをそろえる）。ガチガチ（買い目なし）では出さない
                tg = [f for f in tg if f in (rc.get("boats") or [])] if "boats" in rc else ([] if gachi else tg)
            chips = [f'<span class="chip tg">狙い目 {bt(f)}</span>' for f in tg]
            if r.get("ana"):
                chips.insert(0, '<span class="chip an">高回収狙い</span>')
            if r.get("tsuke"):
                chips.insert(0, '<span class="chip tk">厳選穴</span>')

            if r.get("in_worry") and gachi:
                # 人気はインに集中しているのに、イン不安の材料がある → 1つのラベルにまとめる
                chips.insert(0, '<span class="chip gc">イン人気過剰</span>')
            elif r.get("in_worry"):
                chips.insert(0, f'<span class="chip iw{r["in_worry"]}">イン不安</span>')
            elif gachi:
                chips.append('<span class="chip gc">ガチガチ</span>')
            if rc and rc["verdict"] == "自信あり":
                chips.insert(0, '<span class="chip cf">自信あり</span>')
            if r.get("hit") and r.get("result") and self.finished(r):
                chips.insert(0, '<span class="chip hitc">的中</span>')
            tag = "".join(chips)
            resh = f'{combo(r["result"])}<br><span class="num sub">{yen(r.get("payout"))}</span>' if r.get("result") and self.finished(r) else ""
            rows.append(f'<tr data-dl="{d} {r["deadline"]}"><td><a href="{self.race_link(page, d, jcd, r["rno"])}"><strong>{r["rno"]}R</strong></a></td><td class="num">{r["deadline"]}</td><td>{tag}</td><td>{resh}</td></tr>')
        return "".join(rows)

    @staticmethod
    def reco_summary(rc):
        """一覧用の要約：点数と合成オッズだけ（中身はレースページで）"""
        return f'<span class="rs"><span class="sub">絞り込み</span><span class="rs-n">{rc["n"]}点</span></span><span class="num" style="white-space:nowrap">合成 {float(rc["comp"]):.2f}倍</span>'

    def finished(self, r):
        return bool(r.get("result")) and r["deadline"] <= self.now.strftime("%H:%M")

    def venue_tile(self, page, jcd, v):
        name = VENUES[jcd]["name"]
        href = page.u(f"venue/{SLUG[jcd]}.html")
        if not v:
            return f'<a class="vt off" href="{href}"><b>{e(name)}</b><span>本日開催なし</span><span class="st">&nbsp;</span><span class="bd"></span></a>'
        import re as _re
        dd = v.get("day", "")
        m = _re.search(r"(\d)日目$", dd)
        day = "初日" if dd.endswith("初日") else "最終日" if dd.endswith("最終日") else (f"{m.group(1)}日目" if m else "")
        if v.get("cancelled"):
            st = "中止"
        else:
            nxt = next((r for r in v["races"] if not self.finished(r)), None)
            st = f'<span data-dl="{self.idx.get("date")} {nxt["deadline"]}">{nxt["rno"]}R <span class="num">{nxt["deadline"]}</span></span>' if nxt else "本日終了"
        tz = {"ナイター": "ナイター", "モーニング": "モーニング", "ミッドナイト": "ミッドナイト", "サマータイム": "サマー"}.get(v.get("timezone", ""), "")
        g = v.get("grade", "")
        badges = (f'<i class="g g-{e(g)}">{e(g)}</i>' if g else "") + (f'<i class="tz">{tz}</i>' if tz else "")
        return f'<a class="vt on{" done" if st == "本日終了" else ""}" href="{href}"><b>{e(name)}</b><span>{e(day)}</span><span class="st">{st}</span><span class="bd">{badges}</span></a>'

    def index_page(self):
        page = Page("index.html")
        d = self.idx.get("date", self.now.strftime("%Y%m%d"))
        conf, gachi, checked = [], 0, 0
        held = {v["jcd"]: v for v in self.idx.get("venues", [])}
        soon = []
        for v in self.idx.get("venues", []):
            for r in v["races"]:
                rc = r.get("reco")
                if rc:
                    checked += 1
                    gachi += rc["verdict"] == "購入非推奨"
                    if rc["verdict"] == "自信あり":
                        conf.append((v, r))
                if not self.finished(r) and not v.get("cancelled"):
                    soon.append((r["deadline"], v, r))
        soon.sort(key=lambda x: x[0])
        tiles = "".join(self.venue_tile(page, jcd, held.get(jcd)) for jcd in sorted(VENUES))
        soonh = []
        for _, v, r in soon[:4]:
            rc = r.get("reco")
            if rc and rc["verdict"] == "購入非推奨":
                line = '<span class="sub">購入非推奨（ガチガチ）</span>'
            elif rc and rc["verdict"] == "自信あり":
                line = self.reco_summary(rc)
            elif r.get("pts"):
                line = f'<span class="rs"><span class="sub">本線</span><span class="rs-n">{r["pts"][0]}点</span><span class="sub">押さえ</span><span class="rs-n">{r["pts"][1]}点</span></span>'
            else:
                line = '<span class="sub">締切35分前に買い目を出します</span>'
            cfh = '<span class="chip cf">自信あり</span> ' if rc and rc["verdict"] == "自信あり" else ""
            soonh.append(f'<a data-dl="{d} {r["deadline"]}" href="{self.race_link(page, d, v["jcd"], r["rno"])}"><div class="row"><strong>{cfh}{e(v["name"])} {r["rno"]}R</strong>'
                         f'<span class="num">{r["deadline"]}締切</span></div><div class="row">{line}</div></a>')
        soonh = "".join(soonh)
        cards, done = [], []
        conf.sort(key=lambda x: x[1]["deadline"])
        for v, r in conf:
            rc = r["reco"]
            href = self.race_link(page, d, v["jcd"], r["rno"])
            if self.finished(r):
                h = rc.get("hit")
                pay = f" {yen(r.get('payout'))}" if h else ""
                done.append(f'<a href="{href}"><span class="pill {"hit" if h else "miss"}">{"的中" if h else "不的中"}</span> {e(v["name"])}{r["rno"]}R{pay}</a>')
                continue
            cards.append(f'<a class="cfc" data-dl="{d} {r["deadline"]}" href="{href}"><div class="row"><strong>{e(v["name"])} {r["rno"]}R</strong><span class="num">{r["deadline"]}締切</span></div>'
                         f'<div class="row">{self.reco_summary(rc)}</div></a>')
        n_done = len(done)
        n_hit = sum(1 for v, r in conf if self.finished(r) and r["reco"].get("hit"))
        ticker = ""
        if done:
            items = "".join(done)
            ticker = (f'<div class="ticker" aria-label="終わった自信ありレース"><span class="tk-h">本日 {n_done}R中{n_hit}的中</span>'
                      f'<div class="tk-w"><div class="tk-t" style="animation-duration:{max(12, n_done * 5)}s">{items}{items}</div></div></div>')
        cards = ("<div class=\"strip\">" + "".join(cards) + "</div>" if cards else '<p class="sub">これから締切の自信ありレースはありません。</p>') if (cards or done) else ""
        if cards:
            cards = ticker + cards
        hon_cards, hon_done = [], []
        for v in self.idx.get("venues", []):
            for r in v["races"]:
                hm = r.get("hon")
                if not hm:
                    continue
                href = self.race_link(page, d, v["jcd"], r["rno"])
                if self.finished(r):
                    hon_done.append(hm.get("hit"))
                    if hm.get("hit"):
                        hon_cards.append((1, r["deadline"], f'<a class="cfc hmc" href="{href}"><div class="row"><strong>{e(v["name"])} {r["rno"]}R</strong><span class="pill hit">的中</span></div><div class="row"><span class="sub">{bt(hm["in"])}-{bt(hm["axis"])} {hm["n"]}点</span><span class="num">{yen(r.get("payout"))}</span></div></a>'))
                    continue
                cp = f'<span class="num">合成 {hm["comp"]:.1f}倍</span>' if hm.get("comp") else '<span class="sub">オッズ待ち</span>'
                hon_cards.append((0, r["deadline"], f'<a class="cfc hmc" data-dl="{d} {r["deadline"]}" href="{href}"><div class="row"><strong>{e(v["name"])} {r["rno"]}R</strong><span class="num">{r["deadline"]}締切</span></div><div class="row"><span class="sub">{bt(hm["in"])}-{bt(hm["axis"])} {hm["n"]}点</span>{cp}</div></a>'))
        hon_cards.sort(key=lambda x: (x[0], x[1]))
        honh = (f'<section style="display:grid;gap:10px"><h2>厳選本命 <small>イン逃げが堅く、2着の軸もはっきりしたレースを3点で{f"・本日 {len(hon_done)}R中{sum(1 for x in hon_done if x)}的中" if hon_done else ""}</small></h2>'
                f'<div class="strip">{"".join(c for _, _, c in hon_cards)}</div></section>') if hon_cards else ""
        ana_cards, ana_done = [], []
        for v in self.idx.get("venues", []):
            for r in v["races"]:
                t = r.get("tsuke")
                if not t:
                    continue
                href = self.race_link(page, d, v["jcd"], r["rno"])
                if self.finished(r):
                    h = t.get("hit")
                    ana_done.append(h)
                    if not h:
                        continue
                    ana_cards.append((1, r["deadline"], f'<a class="cfc tkc" href="{href}"><div class="row"><strong>{e(v["name"])} {r["rno"]}R</strong><span class="pill {"hit" if h else "miss"}">{"的中" if h else "不的中"}</span></div><div class="row"><span class="sub">{bt(t["frame"])}の頭・{t["n"]}点</span>{("<span class=num>" + yen(r.get("payout")) + "</span>") if h else ""}</div></a>'))
                else:
                    cp = f'<span class="num">合成 {t["comp"]:.1f}倍</span>' if t.get("comp") else '<span class="sub">オッズ待ち</span>'
                    ana_cards.append((0, r["deadline"], f'<a class="cfc tkc" data-dl="{d} {r["deadline"]}" href="{href}"><div class="row"><strong>{e(v["name"])} {r["rno"]}R</strong><span class="num">{r["deadline"]}締切</span></div><div class="row"><span class="sub">{bt(t["frame"])}の頭・{t["n"]}点</span>{cp}</div></a>'))
        ana_cards.sort(key=lambda x: (x[0], x[1]))
        anah = (f'<section style="display:grid;gap:10px"><h2>厳選穴 <small>穴目の条件がすべてそろったレース{f"・本日 {len(ana_done)}R中{sum(1 for x in ana_done if x)}的中" if ana_done else ""}</small></h2>'
                f'<div class="strip">{"".join(c for _, _, c in ana_cards)}</div></section>') if ana_cards else ""
        targets = self.today_targets(page)
        body = f"""<div class="hero"><img src="{page.u('img/logo.webp')}" srcset="{page.u('img/logo-sm.webp')} 560w, {page.u('img/logo.webp')} 1000w" sizes="(max-width:720px) 92vw, 560px" width="1000" height="497" alt="{SITE_NAME}" fetchpriority="high"></div>
<section style="display:grid;gap:6px"><span class="eyebrow">{jdate(d)}のボートレース予想</span>
<h1>今日のボートレース予想｜全場の本線・押さえと自信ありレース</h1>
<p class="sub">最終更新 {e((self.idx.get('updated_at') or '')[11:])}　公式の出走表・展示・オッズからAIが着順を予想し、全レースに本線・押さえを出しています。その中から合成オッズ5倍以上に絞れて見込みも高いレースは「自信あり」、本命が売れすぎているレースは「購入非推奨」です。</p></section>
{f'<section class="conf" style="display:grid;gap:10px"><h2>自信ありレース <small>展示まで見たうえで、本線・押さえから合成オッズ5倍以上に絞れて、AIの見込みが高いレース</small></h2>{cards}</section>' if cards else ''}
{anah}
<section style="display:grid;gap:10px"><h2>本日の開催 <small>{len(held)}場・タップでレース一覧</small> <a class="h2link" href="{page.u('results.html')}">払戻金一覧 →</a></h2><div class="vtiles">{tiles}</div></section>
{f'<section style="display:grid;gap:10px"><h2>まもなく締切</h2><div class="soon">{soonh}</div></section>' if soonh else ''}
{f'<p class="sub">判定済み {checked}レース：購入非推奨（ガチガチ） {gachi}・{"自信あり " + str(len(conf)) + "・" if conf else ""}残りは通常の推奨</p>' if checked else ''}
<div class="ad-slot" data-slot="home_mid"></div>
{targets}
<section class="panel" style="display:grid;gap:8px"><h2>はじめての方へ</h2>
<ul class="comments"><li><a href="{page.u('guide/sanrentan.html')}">3連単の買い方と、長く続けると負けやすい理由（控除率）</a></li>
<li><a href="{page.u('tools/composite.html')}">合成オッズの計算ツール（どれが当たっても同じ払戻になる配分）</a></li>
<li><a href="{page.u('guide/course.html')}">コースと決まり手の基本（逃げ・差し・捲り・捲り差し）</a></li>
<li><a href="{page.u('targets.html')}">狙い目レーサーまとめ（コース巧者・捲られやすいイン）</a></li></ul></section>"""
        self.put("index.html", page.render(f"今日のボートレース予想｜全場の推奨買い目・合成オッズ｜{SITE_NAME}",
                                           "ボートレース全場の今日の予想。公式データと展示・オッズから、合成オッズ5倍以上の推奨買い目、購入非推奨レース、選手のコース別成績を毎日自動更新。", body))

    # ------------------------------------------------------------ 払戻金一覧
    def results_pages(self):
        today = self.idx.get("date")
        days = sorted(set(getattr(self, "day_races", {}) or {}) | ({today} if today else set()))
        for i, d in enumerate(days):
            if d > (today or d):
                continue
            venues = {}
            if d == today:
                for v in self.idx.get("venues", []):
                    venues[v["jcd"]] = {"name": v["name"], "day": v.get("day", ""), "grade": v.get("grade", ""), "cancelled": v.get("cancelled"),
                                        "races": [{"rno": r["rno"], "deadline": r.get("deadline", ""), "result": r.get("result") if self.finished(r) else None,
                                                   "payout": r.get("payout"), "ninki": r.get("ninki"), "hit": r.get("hit")} for r in v.get("races", [])]}
            for race in (self.day_races.get(d) or []):
                jcd = race["jcd"]
                res = race["result"] if race.get("result", {}).get("finished") else None
                row = {"rno": race["rno"], "deadline": race.get("deadline", ""), "result": res["trifecta"] if res else None,
                       "payout": res.get("trifecta_payout") if res else None, "ninki": res.get("trifecta_ninki") if res else None, "hit": race.get("hit")}
                v = venues.setdefault(jcd, {"name": VENUES[jcd]["name"], "day": "", "grade": "", "races": []})
                old = next((x for x in v["races"] if x["rno"] == row["rno"]), None)
                if old is None:
                    v["races"].append(row)
                elif row["result"] and not old.get("result"):
                    old.update({k: row[k] for k in ("result", "payout", "ninki", "hit")})
                elif row["result"] and old.get("result") and not old.get("ninki"):
                    old["ninki"] = row["ninki"]
            self.results_page(d, venues, days[i - 1] if i > 0 else None, days[i + 1] if i + 1 < len(days) else None, d == today)

    def results_page(self, d, venues, prev, nxt, is_today):
        path = f"results/{d}.html"
        page = Page(path)
        cards, n_done, n_man, n_hit, n_all = [], 0, 0, 0, 0
        for jcd in sorted(venues):
            v = venues[jcd]
            rows = []
            for r in sorted(v["races"], key=lambda x: x["rno"]):
                n_all += 1
                href = self.race_link(page, d, jcd, r["rno"])
                if r.get("result"):
                    n_done += 1
                    pay = r.get("payout") or 0
                    n_man += pay >= 10000
                    n_hit += bool(r.get("hit"))
                    hitc = '<span class="chip hitc">的中</span>' if r.get("hit") else ""
                    rows.append(f'<tr><td><a href="{href}#kekka"><b>{r["rno"]}R</b></a></td><td><a href="{href}#kekka">{combo(r["result"])}</a></td>'
                                f'<td class="r num{" man" if pay >= 10000 else ""}">{yen(r.get("payout"))}</td><td class="r num sub">{r.get("ninki") or ""}</td><td>{hitc}</td></tr>')
                else:
                    dl = r.get("deadline", "")
                    st = f'<span data-dl="{d} {dl}">{dl}締切</span>' if is_today and dl else ("中止・結果なし" if not is_today else "")
                    rows.append(f'<tr class="pend"><td><a href="{href}"><b>{r["rno"]}R</b></a></td><td colspan="4" class="sub num">{st}</td></tr>')
            if v.get("cancelled"):
                rows = ['<tr><td colspan="5" class="sub">中止</td></tr>']
            g = v.get("grade", "")
            head = f'<a href="{page.u("venue/" + SLUG[jcd] + ".html")}"><b>{e(v["name"])}</b></a>' + (f' <i class="g g-{e(g)}">{e(g)}</i>' if g else "") + f' <span class="sub">{e(v.get("day", ""))}</span>'
            cards.append(f'<section class="rcard panel"><h3>{head}</h3><table class="rtbl"><thead><tr><th>R</th><th>3連単</th><th class="r">払戻</th><th class="r">人気</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table></section>')
        nav = " ".join(x for x in (
            f'<a href="{page.u(f"results/{prev}.html")}">← {jdate(prev)}</a>' if prev else "",
            f'<a href="{page.u(f"results/{nxt}.html")}">{jdate(nxt)} →</a>' if nxt else "") if x)
        summary = (f'{len(venues)}場・{n_done}/{n_all}R 確定・万舟 <b class="man">{n_man}</b>本・本線押さえ的中 <b>{n_hit}</b>R' if venues else "この日のデータはありません。")
        body = f"""<section style="display:grid;gap:6px"><span class="eyebrow">{jdate(d)}</span>
<h1>{jdate(d)}のボートレース 払戻金一覧</h1>
<p class="sub">{summary}{'　最終更新 ' + e((self.idx.get('updated_at') or '')[11:]) + '（5分ごとに自動更新）' if is_today else ''}</p>
<p class="sub">3連単の組番・払戻金・人気。1万円以上（万舟）は赤字、「的中」は艇ろぐの本線・押さえに入っていたレースです。組番をタップするとレースの予想と結果へ。</p>
{f'<p class="rnav">{nav}</p>' if nav else ''}</section>
<div class="rgrid">{''.join(cards)}</div>"""
        script = "<script>setTimeout(function(){location.reload()},300000)</script>" if is_today else ""
        title = f"{jdate(d)}のボートレース結果・払戻金一覧（全場3連単）｜{SITE_NAME}"
        desc = f"{jdate(d)}のボートレース全場の3連単の結果・払戻金・人気の一覧。万舟の数と、艇ろぐの予想の的中レースもひと目でわかります。"
        self.put(path, page.render(title, desc, body, [("", "払戻金一覧")], script=script))
        if is_today:
            tp = Page("results.html")
            body2 = body.replace('href="../', 'href="')
            self.put("results.html", tp.render(f"今日のボートレース結果・払戻金一覧｜{SITE_NAME}", desc, body2, [("", "本日の払戻金一覧")], script=script))

    # ------------------------------------------------------------ 狙い目レーサー
    def rankings(self):
        S = self.S
        out = {}
        for c in range(2, 7):
            nt = S.nc[c]
            p = nt[1] / nt[0] if nt[0] else 0
            rows = []
            for t in self.racers:
                v = self.op_of(t, c)
                if not v or v[0] < OP_MIN:
                    continue
                me = S.rc[t][c]
                kim = {k: int(me[4 + i]) for i, k in enumerate(KIM) if me[4 + i]}
                rows.append((v[3], t, v[0], v[1] / v[0], v[2] / v[0], kim))
            rows.sort(reverse=True)
            out[c] = (p, rows[:20])
        # インの逃げ率と捲られ率
        n1 = S.nc[1]
        p1 = n1[1] / n1[0]
        nat_mk = sum(v for k, v in S.nl.items() if k.endswith("-まくり")) / S.nn
        esc, mk = [], []
        for t, d in S.rc.items():
            me = d.get(1)
            if me is None or me[0] < 30 or t not in self.racers:
                continue
            op = self.op_of(t, 1)
            if op and op[0] >= OP_MIN:
                esc.append((op[3], t, op[0], op[1] / op[0], op[2] / op[0]))
            m = sum(v for k, v in S.rl[t].items() if k.endswith("-まくり")) / me[0]
            mk.append((m, t, int(me[0]), me[1] / me[0]))
        esc.sort(reverse=True)
        mk.sort(reverse=True)
        return out, (p1, esc[:20]), (nat_mk, mk[:20])

    def targets_in(self, jcd, rno):
        """そのレースの狙い目の枠番（買われすぎ注意の組み合わせは除く）"""
        return sorted(b["frame"] for _, v, r, b, c, _ in self.target_items()
                      if v["jcd"] == jcd and r["rno"] == rno and not self.caution(b, c))

    def caution(self, b, c):
        vb = (self.report.get("overperf") or {}).get("by_course", {})
        x = vb.get(str(c), {}).get("A" if str(b.get("class", "")).startswith("A") else "B")
        return bool(x) and x[1] / x[2] < 0.9

    def target_items(self):
        if getattr(self, "_targets", None) is not None:
            return self._targets
        items = []
        d = self.idx.get("date")
        for v in self.idx.get("venues", []):
            for r in v["races"]:
                race = load_json(DATA / "races" / d / f"{v['jcd']}{r['rno']:02d}.json", {})
                p = race.get("prediction") or {}
                course_of = {b["frame"]: b["course"] for b in p.get("boats", [])}
                for b in (race.get("racelist") or {}).get("boats", []):
                    c = course_of.get(b["frame"], b["frame"])
                    if c == 1 or not b.get("toban"):
                        continue
                    op = self.op_of(b["toban"], c)
                    if not op or op[0] < OP_MIN or op[3] < OP_MARK:
                        continue
                    items.append((op[3], v, r, b, c, op))
        items.sort(key=lambda x: -x[0])
        self._targets = items
        return items

    def today_targets(self, page):
        """今日走る選手のうち、今日の枠（展示後は進入）のコースで巧者の選手"""
        d = self.idx.get("date")
        items = self.target_items()
        if not items:
            return ""
        rows = "".join(
            f'<tr><td><a href="{self.race_link(page, d, v["jcd"], r["rno"])}">{e(v["name"])} {r["rno"]}R</a> <span class="sub num">{r["deadline"]}</span></td>'
            f'<td>{bt(b["frame"])} <a href="{page.u("racer/" + b["toban"] + ".html")}">{e(b["name"])}</a> <span class="sub">{e(b.get("class", ""))} 勝率{b.get("nat_win") or "-"}</span></td>'
            f'<td class="r num">{c}コース</td><td class="r num">{pct(op[1] / op[0])}<span class="sub">/{op[0]}走</span></td><td class="r num sub">{pct(op[2] / op[0])}</td>'
            f'<td class="r num best">{sc:.2f}</td><td>{"<span class=sub>買われすぎ注意</span>" if self.caution(b, c) else ""}</td></tr>'
            for sc, v, r, b, c, op in items[:15])
        return (f'<section style="display:grid;gap:8px"><h2>今日の狙い目レーサー <small>今日のコースで、実力のわりに勝てている選手（スコア{OP_MARK}以上）</small></h2>'
                f'<div class="panel tbl-wrap" style="padding:4px 8px"><table><thead><tr><th>レース</th><th>選手</th><th class="r">コース</th><th class="r">実際の1着率</th><th class="r">実力どおりなら</th><th class="r">スコア</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>'
                f'<p class="sub">展示前は枠番のコースで判定。「買われすぎ注意」は、過去の検証でそのコース・級別の巧者がオッズの見立てより勝てていなかった組み合わせです。<a href="{page.u("targets.html")}">狙い目レーサーまとめ →</a></p></section>')

    def targets_page(self):
        page = Page("targets.html")
        cour, (p1, esc), (nat_mk, mk) = self.rankings()
        op_note = (self.report.get("overperf") or {}).get("note", "")

        def rname(t):
            return f'<a href="{page.u("racer/" + t + ".html")}">{e(self.racer_name(t))}</a> <span class="sub">{e(self.racers.get(t, {}).get("class", ""))} {e(self.racers.get(t, {}).get("branch", ""))}</span>'

        vb = (self.report.get("overperf") or {}).get("by_course", {})
        secs = []
        for c, (p, rows) in cour.items():
            tr = "".join(f'<tr><td class="r num">{i + 1}</td><td>{rname(t)}</td><td class="r num">{n}</td><td class="r num">{pct(w, 1)}</td><td class="r num sub">{pct(ex, 1)}</td>'
                         f'<td class="r num best">{sc:.2f}</td><td>{e("・".join(f"{k}{v}" for k, v in kim.items()) or "-")}</td></tr>'
                         for i, (sc, t, n, w, ex, kim) in enumerate(rows))
            chk = ""
            if str(c) in vb:
                parts = []
                for cls, lab in (("A", "A級"), ("B", "B級")):
                    n_, w_, m_ = vb[str(c)][cls]
                    r_ = w_ / m_
                    tone = "best" if r_ >= 1.1 else ("warn" if r_ < 0.9 else "")
                    parts.append(f'{lab}：実際 {pct(w_, 1)} / オッズの見立て {pct(m_, 1)} → <b class="num {tone}">{r_:.2f}倍</b>（{n_}艇）')
                chk = f'<p class="sub">過去1年の検証（スコア{OP_MARK}以上の艇）　' + "　".join(parts) + "</p>"
            secs.append(f'<section class="panel" id="c{c}"><h2>{c}コース巧者 <small>実力のわりに{c}コースで勝てる選手・{OP_MIN}走以上</small></h2>'
                        f'<div class="tbl-wrap"><table><thead><tr><th class="r">#</th><th>選手</th><th class="r">{c}コース出走</th><th class="r">実際の1着率</th><th class="r">実力どおりなら</th><th class="r">スコア</th><th>勝ち方</th></tr></thead><tbody>{tr}</tbody></table></div>{chk}</section>')
        esc_rows = "".join(f'<tr><td class="r num">{i + 1}</td><td>{rname(t)}</td><td class="r num">{n}</td><td class="r num">{pct(w, 1)}</td><td class="r num sub">{pct(ex, 1)}</td><td class="r num best">{sc:.2f}</td></tr>' for i, (sc, t, n, w, ex) in enumerate(esc))
        mk_rows = "".join(f'<tr><td class="r num">{i + 1}</td><td>{rname(t)}</td><td class="r num">{n}</td><td class="r num">{pct(r, 1)}</td><td class="r num sub">{pct(w, 1)}</td></tr>' for i, (r, t, n, w) in enumerate(mk))
        warn = ""
        body = f"""<section style="display:grid;gap:6px"><h1>狙い目レーサーまとめ｜実力以上にコースで勝てる選手・捲られやすいイン</h1>
<div class="panel" style="display:grid;gap:6px"><b>ただ強い選手ではなく「実力のわりに、そのコースで勝てる選手」</b>
<p style="margin:0">A1の選手はどのコースでもよく勝つので、コース別1着率の順位ではA1が並ぶだけです。ここでは全国勝率・級別・コースから「実力どおりなら何%勝てるか」を出し、実際の1着率がそれを何倍上回っているか（<b>スコア</b>）で並べています。スコア1.6＝実力から見込まれるより6割多く勝っている。</p>
<p class="sub" style="margin:0">{e(op_note)}</p></div>
<p class="sub">公式の競走成績（直近1年）から毎日自動で集計。出走が少ない選手ほどスコアを1に寄せています。</p>
<p class="toc">{' '.join(f'<a href="#c{c}">{c}コース</a>' for c in range(2, 7))} <a href="#esc">逃げ</a> <a href="#mk">捲られやすいイン</a></p></section>
{self.today_targets(page)}
{''.join(secs)}
<section class="panel" id="esc"><h2>実力以上にインで逃げる選手 <small>1コース{OP_MIN}走以上・全国の1コース1着率 {pct(p1, 1)}</small></h2><div class="tbl-wrap"><table><thead><tr><th class="r">#</th><th>選手</th><th class="r">1コース出走</th><th class="r">実際の1着率</th><th class="r">実力どおりなら</th><th class="r">スコア</th></tr></thead><tbody>{esc_rows}</tbody></table></div></section>
<section class="panel" id="mk"><h2>捲られやすいイン <small>1コースで他艇の捲りに負けた割合・全国 {pct(nat_mk, 1)}</small></h2><div class="tbl-wrap"><table><thead><tr><th class="r">#</th><th>選手</th><th class="r">1コース出走</th><th class="r">捲られ率</th><th class="r">逃げ率</th></tr></thead><tbody>{mk_rows}</tbody></table></div>
<p class="sub">この選手がインのときは、3・4コースの捲りが決まりやすい傾向があります（過去2年の検証で、捲られやすいイン×捲りの多い3コースの組み合わせは捲り勝ち率が約6倍）。</p></section>
{warn}"""
        self.put("targets.html", page.render(f"狙い目レーサーまとめ｜コース別巧者ランキング・捲られやすいイン｜{SITE_NAME}",
                                             "ボートレースの狙い目レーサー。2〜6コースのコース巧者ランキング、インの逃げが強い選手、捲られやすいインを公式データから毎日集計。", body, [("", "狙い目レーサー")]))

    # ------------------------------------------------------------ 選手
    def recent_index(self):
        since = (self.now - timedelta(days=365)).strftime("%Y%m%d")
        rec = defaultdict(list)
        for r in load_all(since):
            w = next((y for y in r[11] if y[5] == 1), None)
            s2 = next((y for y in r[11] if y[5] == 2), None)
            for x in r[11]:
                # (日付, 場, R, 枠, コース, 着, 決まり手(自分が1着のとき), ST, 1着艇のコース, 2着艇のコース, レースの決まり手)
                rec[x[1]].append((r[0], r[1], r[2], x[0], x[2], x[5], r[3] if x[5] == 1 else "",
                                  (x[3] / 100 if x[3] is not None else None), (x[4] or ""), w[2] if w else None, s2[2] if s2 else None, r[3] or ""))
        for t in rec:
            rec[t].sort(reverse=True)
        return rec

    # ------------------------------------------------------------ 展示ST と 本番ST
    COURSE_COL = {1: "#E9EDF1", 2: "#8B97A3", 3: "#FF5A4E", 4: "#4C8DFF", 5: "#F2D231", 6: "#3DD68C"}

    def st_chart(self, pairs, course=None, ex_now=None, w=300, h=210):
        """横＝展示ST、縦＝本番ST。course を指定するとそのコースを強調"""
        X0, X1, Y0, Y1 = -0.12, 0.36, 0.0, 0.36
        L, R, T, B = 34, 8, 8, 26
        sx = lambda v: L + (min(max(v, X0), X1) - X0) / (X1 - X0) * (w - L - R)
        sy = lambda v: h - B - (min(max(v, Y0), Y1) - Y0) / (Y1 - Y0) * (h - T - B)
        g = [f'<rect x="{L}" y="{T}" width="{w - L - R}" height="{h - T - B}" fill="rgba(255,255,255,.02)" stroke="var(--line)"/>']
        for v in (0.0, 0.1, 0.2, 0.3):
            g.append(f'<line x1="{sx(v)}" y1="{T}" x2="{sx(v)}" y2="{h - B}" stroke="var(--line)" stroke-width=".6"/>'
                     f'<text x="{sx(v)}" y="{h - B + 12}" text-anchor="middle" font-size="9" fill="var(--ink2)">{v:.1f}</text>'
                     f'<line x1="{L}" y1="{sy(v)}" x2="{w - R}" y2="{sy(v)}" stroke="var(--line)" stroke-width=".6"/>'
                     f'<text x="{L - 4}" y="{sy(v) + 3}" text-anchor="end" font-size="9" fill="var(--ink2)">{v:.1f}</text>')
        g.append(f'<line x1="{sx(0)}" y1="{sy(0)}" x2="{sx(0.36)}" y2="{sy(0.36)}" stroke="#F5C542" stroke-dasharray="3 3" stroke-width="1"/>')
        for c, ex, st, _ in pairs:
            hi = course is None or c == course
            g.append(f'<circle cx="{sx(ex / 100):.1f}" cy="{sy(st / 100):.1f}" r="{3.4 if hi else 2.2}" fill="{self.COURSE_COL.get(c, "#888")}" '
                     f'fill-opacity="{0.9 if hi else 0.25}"/>')
        if ex_now is not None:
            g.append(f'<line x1="{sx(ex_now)}" y1="{T}" x2="{sx(ex_now)}" y2="{h - B}" stroke="#FF6B35" stroke-width="2"/>'
                     f'<text x="{sx(ex_now) + 4}" y="{T + 11}" font-size="10" font-weight="700" fill="#FF6B35">今回の展示</text>')
        g.append(f'<text x="{(L + w - R) / 2}" y="{h - 2}" text-anchor="middle" font-size="9.5" fill="var(--ink2)">展示のST →</text>'
                 f'<text x="10" y="{(T + h - B) / 2}" font-size="9.5" fill="var(--ink2)" transform="rotate(-90 10 {(T + h - B) / 2})" text-anchor="middle">本番のST →</text>')
        return f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block;max-width:420px" role="img" aria-label="展示STと本番STの関係">{"".join(g)}</svg>'

    @staticmethod
    def st_summary(pairs, course=None):
        ps = [p for p in pairs if course is None or p[0] == course]
        if len(ps) < 3:
            ps = pairs
        if len(ps) < 3:
            return None
        ex = [p[1] / 100 for p in ps]
        st = [p[2] / 100 for p in ps]
        n = len(ps)
        mx, my = sum(ex) / n, sum(st) / n
        vx = sum((a - mx) ** 2 for a in ex)
        vy = sum((b - my) ** 2 for b in st)
        cor = sum((a - mx) * (b - my) for a, b in zip(ex, st)) / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0
        sd = math.sqrt(vy / n)
        typ = "展示と本番が連動" if cor >= 0.4 and n >= 12 else "展示とはあまり連動しない"
        return {"n": n, "ex": mx, "st": my, "sd": sd, "cor": cor, "type": typ, "same_course": course is not None and len([p for p in pairs if p[0] == course]) >= 3}

    def st_pages(self):
        """各レースの「展示STと本番ST」ページ（出走6人分）"""
        pairs = fstart.load_pairs()
        d = self.idx.get("date")
        if not d:
            return
        for v in self.idx.get("venues", []):
            for r in v["races"]:
                race = load_json(DATA / "races" / d / f"{v['jcd']}{r['rno']:02d}.json", {})
                rl = (race.get("racelist") or {}).get("boats") or []
                if len(rl) != 6:
                    continue
                page = Page(f"race/{d}/{SLUG[v['jcd']]}-{r['rno']}-st.html")
                back = page.u(f"race/{d}/{SLUG[v['jcd']]}-{r['rno']}.html")
                se = {x["frame"]: x for x in (race.get("before") or {}).get("start_exhibition") or []}
                crs = {f: (se[f]["course"] if f in se else f) for f in range(1, 7)}
                cards = []
                for b in sorted(rl, key=lambda b: crs[b["frame"]]):
                    f, c = b["frame"], crs[b["frame"]]
                    ps = pairs.get(b.get("toban", ""), [])
                    sm = self.st_summary(ps, c)
                    exn = se.get(f, {}).get("st")
                    exl = ("-" if exn is None else (f'<span style="color:#FF4D4D">F{abs(exn):.2f}</span>'.replace("0.", ".") if exn < 0 else f"{exn:.2f}".replace("0.", ".")))
                    if sm:
                        where = f"{c}コース" if sm["same_course"] else "全コース"
                        info = (f'<p style="margin:4px 0">今回の展示ST <b class="num">{exl}</b> → 本番の目安 <b class="num">{sm["st"]:.2f}</b> 付近'
                                f'<span class="sub">（{where}の本番平均・ばらつき±{sm["sd"]:.2f}）</span></p>'
                                f'<p class="sub" style="margin:0">{sm["n"]}走：展示の平均 {sm["ex"]:.2f} → 本番の平均 {sm["st"]:.2f}。<b>{sm["type"]}</b>（相関 {sm["cor"]:.2f}）</p>')
                    else:
                        info = '<p class="sub">展示と本番の両方がそろったデータがまだ少ない選手です。</p>'
                    link = self.racer_link(page, b.get("toban", ""))
                    nm = f'<a href="{link}#c{c}">{e(b.get("name", ""))}</a>' if link else e(b.get("name", ""))
                    cards.append(f'<section class="panel" style="display:grid;gap:6px"><h2>{bt(f)} {nm} <small>{c}コース・{e(b.get("class", ""))}</small></h2>'
                                 f'{self.st_chart(ps, c, exn)}{info}</section>')
                body = (f'<section style="display:grid;gap:6px"><span class="eyebrow">{e(v["name"])} · {jdate(d)}</span>'
                        f'<h1>{e(v["name"])} {r["rno"]}R 展示STと本番ST</h1>'
                        f'<p class="sub">点1つが1走。横が展示のスタートタイミング、縦が本番のスタートタイミング。黄色い点線より上なら「本番の方が遅い」。色はコース（今回のコースを濃く表示）、オレンジの縦線が今回の展示ST。</p>'
                        f'<p><a href="{back}">← {e(v["name"])} {r["rno"]}R の予想に戻る</a></p></section>'
                        + "".join(cards) +
                        '<section class="panel"><h2>展示STは当てになる？</h2><p>公式データ約5万5千走で調べると、展示のSTと本番のSTの相関はほぼ0（0.05）でした。展示でFを切っても本番は普通に行く人、展示で遅くても本番は早い人がたくさんいます。'
                        '本番のSTを読むなら、展示の数字そのものより「その選手がそのコースで普段何秒で行っているか」の方がずっと当たります（誤差 0.095秒 → 0.054秒）。上のグラフで、点が縦に散らばっている選手ほど展示を気にしなくてよい選手です。</p></section>')
                self.put(page.path, page.render(f"{v['name']}{r['rno']}R 展示STと本番ST｜{SITE_NAME}",
                                                f"{jdate(d)} {v['name']}{r['rno']}Rの出走選手6人の、展示スタートと本番スタートの関係。", body,
                                                [(f"venue/{SLUG[v['jcd']]}.html", v["name"]), (f"race/{d}/{SLUG[v['jcd']]}-{r['rno']}.html", f"{r['rno']}R"), ("", "展示STと本番ST")], noindex=True))

    @staticmethod
    def course_recent(xs):
        """コースごとの最近10走（直近1年）。1コースは「逃げたときの2着のコース」も"""
        out = []
        for c in range(1, 7):
            ys = [x for x in xs if x[4] == c][:10]
            allc = [x for x in xs if x[4] == c]
            if not ys:
                continue
            def stf(x):
                if x[8] == "F":
                    return '<span style="color:#FF4D4D">F</span>'
                return f"{x[7]:.2f}".replace("0.", ".") if x[7] is not None else "-"
            rows = "".join(
                f'<tr><td class="num">{int(x[0][4:6])}/{int(x[0][6:])}</td><td>{e(VENUES.get(x[1], {}).get("name", x[1]))} {x[2]}R</td>'
                f'<td class="r num"><b>{x[5]}</b></td><td class="r num">{stf(x)}</td><td>{e(x[11])}</td>'
                f'<td class="r num">{x[9] or "-"}</td><td class="r num">{x[10] or "-"}</td></tr>' for x in ys)
            n = len(allc)
            wins = sum(1 for x in allc if x[5] == 1)
            top3 = sum(1 for x in allc if isinstance(x[5], int) and x[5] <= 3)
            sts = [x[7] for x in allc if x[7] is not None and x[8] != "F"]
            extra = ""
            if c == 1:
                sec = Counter(x[10] for x in allc if x[5] == 1 and x[10])
                if sec:
                    extra = ('<p class="sub">逃げたときの2着：' + "・".join(f"{k}コース{v}回" for k, v in sorted(sec.items())) + "</p>")
            out.append(f"""<details class="panel cr" id="c{c}"><summary><b>{c}コースのとき</b> <span class="sub">{n}走・1着{wins}・3着内{pct(top3 / n)}・平均ST {f"{sum(sts) / len(sts):.2f}" if sts else "-"}</span></summary>
{extra}<p class="sub" style="margin:0">「1着」「2着」の列は、そのレースで1着・2着になった艇のコース番号です。</p><div class="tbl-wrap"><table><thead><tr><th>日付</th><th>レース</th><th class="r">着</th><th class="r">ST</th><th>決まり手</th><th class="r">1着</th><th class="r">2着</th></tr></thead><tbody>{rows}</tbody></table></div></details>""")
        if not out:
            return ""
        return ('<section style="display:grid;gap:8px"><h2>コースごとの最近のレース <small>直近1年・各コース最新10走</small></h2>' + "".join(out) +
                '<script>(function(){var h=location.hash;var d=h&&document.querySelector("details"+h);if(d){d.open=true;d.scrollIntoView();}})()</script></section>')

    def racer_pages(self):
        self._pairs = fstart.load_pairs()
        rec = self.recent_index()
        today = self.today_entries()
        listing = []
        for t, info in self.racers.items():
            d = self.S.rc.get(t)
            if not d:
                continue
            page = Page(f"racer/{t}.html")
            name = info["name"]
            rows, tags = [], []
            for c in range(1, 7):
                me = d.get(c)
                nt = self.S.nc[c]
                if me is None or me[0] == 0:
                    rows.append(f'<tr><td>{c}コース</td><td class="r num">0</td><td colspan="5" class="sub">出走なし</td></tr>')
                    continue
                n = me[0]
                kim = "・".join(f"{k}{int(me[4 + i])}" for i, k in enumerate(KIM) if me[4 + i]) or "-"
                ratio = self.shrunk_ratio(t, c)
                op = self.op_of(t, c)
                if c >= 2 and op and op[0] >= OP_MIN and op[3] >= OP_MARK:
                    tags.append(f"{c}コース巧者（実力比{op[3]:.1f}）")
                rows.append(f'<tr><td>{c}コース</td><td class="r num">{int(n)}</td><td class="r num {"best" if ratio >= 1.3 and n >= MIN_STARTS else ""}">{pct(me[1] / n, 1)}</td>'
                            f'<td class="r num sub">{pct(nt[1] / nt[0] if nt[0] else None, 1)}</td><td class="r num">{pct((me[1] + me[2]) / n, 1)}</td><td class="r num">{pct((me[1] + me[2] + me[3]) / n, 1)}</td><td>{e(kim)}</td></tr>')
            c1 = d.get(1)
            loss = ""
            if c1 is not None and c1[0] >= 10:
                L = self.S.rl[t]
                lr = {"差され": L.get("2-差し", 0), "捲られ": sum(v for k, v in L.items() if k.endswith("-まくり")),
                      "捲り差され": sum(v for k, v in L.items() if k.endswith("-まくり差し"))}
                nl = {"差され": self.S.nl.get("2-差し", 0), "捲られ": sum(v for k, v in self.S.nl.items() if k.endswith("-まくり")),
                      "捲り差され": sum(v for k, v in self.S.nl.items() if k.endswith("-まくり差し"))}
                for k in lr:
                    r1, r0 = lr[k] / c1[0], nl[k] / self.S.nn
                    if c1[0] >= 30 and r1 >= r0 * 1.3 and r1 >= 0.06:
                        tags.append(f"インで{k}やすい")
                loss = ("<section class=\"panel\"><h2>1コースでの負け方 <small>" + f"{int(c1[0])}走・逃げ率 {pct(c1[1] / c1[0], 1)}" + "</small></h2><div class=\"tbl-wrap\"><table><thead><tr><th></th><th class=\"r\">この選手</th><th class=\"r\">全国</th></tr></thead><tbody>"
                        + "".join(f'<tr><td>{k}</td><td class="r num">{pct(lr[k] / c1[0], 1)}</td><td class="r num sub">{pct(nl[k] / self.S.nn, 1)}</td></tr>' for k in lr) + "</tbody></table></div></section>")
            st = self.S.rst[t]
            recent = "".join(
                f'<tr><td class="num">{int(x[0][4:6])}/{int(x[0][6:])}</td><td>{e(VENUES.get(x[1], {}).get("name", x[1]))} {x[2]}R</td><td class="r num">{x[3]}</td><td class="r num">{x[4] or "-"}</td><td class="r num"><b>{x[5]}</b></td><td>{e(x[6])}</td></tr>'
                for x in rec.get(t, [])[:12])
            bycourse = self.course_recent(rec.get(t, []))
            ps = self._pairs.get(t, [])
            sm = self.st_summary(ps)
            stsec = (f'<section class="panel" style="display:grid;gap:6px"><h2>展示ST → 本番ST <small>{sm["n"]}走・{sm["type"]}（相関 {sm["cor"]:.2f}）</small></h2>{self.st_chart(ps)}'
                     f'<p class="sub">展示の平均 {sm["ex"]:.2f} → 本番の平均 {sm["st"]:.2f}（ばらつき±{sm["sd"]:.2f}）。色はコース（1白・2灰・3赤・4青・5黄・6緑）。</p></section>') if sm else ""
            tod = "".join(f'<li><a href="{page.u(f"race/{dd}/{SLUG[j]}-{rn}.html")}">{e(VENUES[j]["name"])} {rn}R</a>（{f}号艇）</li>' for dd, j, rn, f in today.get(t, []))
            tagh = " ".join(f'<span class="pill lv4">{e(x)}</span>' for x in tags)
            body = f"""<section style="display:grid;gap:6px"><span class="eyebrow">登録番号 {t}</span>
<h1>{e(name)}のコース別成績</h1>
<p>{e(info.get('branch', ''))}支部・{e(info.get('birthplace', ''))}出身・{info.get('age') or '-'}歳・{e(info.get('class', ''))}級・勝率 {info.get('win') or '-'}　{tagh}</p>
{f'<div class="panel"><b>今日の出走</b><ul class="comments">{tod}</ul></div>' if tod else ''}</section>
<section class="panel"><h2>コース別成績 <small>直近1年・平均ST {f"{st[0] / st[1]:.2f}" if st[1] else "-"}</small></h2>
<div class="tbl-wrap"><table><thead><tr><th>コース</th><th class="r">出走</th><th class="r">1着率</th><th class="r">全国</th><th class="r">2連対率</th><th class="r">3連対率</th><th>1着の決まり手</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
{loss}
{bycourse}
{stsec}
<section class="panel"><h2>最近のレース <small>全コース</small></h2><div class="tbl-wrap"><table><thead><tr><th>日付</th><th>レース</th><th class="r">枠</th><th class="r">コース</th><th class="r">着</th><th>決まり手</th></tr></thead><tbody>{recent or '<tr><td colspan="6" class="empty">直近のデータなし</td></tr>'}</tbody></table></div></section>
<p class="sub">データ：BOAT RACE公式の競走成績（直近1年）・期別成績。</p>"""
            desc = f"ボートレーサー{name}（{t}・{info.get('branch', '')}支部）のコース別1着率・連対率・決まり手、インでの負け方、最近の成績。"
            self.put(page.path, page.render(f"{name}（{t}）コース別成績・決まり手｜{SITE_NAME}", desc, body, [("racer/index.html", "選手"), ("", name)]))
            listing.append((info.get("branch", ""), t, name, info.get("class", "")))
        page = Page("racer/index.html")
        by = defaultdict(list)
        for b, t, n, c in sorted(listing):
            by[b].append(f'<a href="{t}.html">{e(n)}<span class="sub">{c}</span></a>')
        body = ('<h1>ボートレーサー一覧（支部別）</h1><p class="sub">各選手のコース別成績ページへ。</p>'
                + "".join(f'<section class="panel"><h2>{e(b or "不明")}</h2><div class="racer-list">{"".join(v)}</div></section>' for b, v in by.items()))
        self.put(page.path, page.render(f"ボートレーサー一覧｜コース別成績｜{SITE_NAME}", "ボートレーサー約1,600人のコース別成績ページ一覧（支部別）。", body, [("", "選手")]))

    def today_entries(self):
        out = defaultdict(list)
        d = self.idx.get("date")
        for v in self.idx.get("venues", []):
            for r in v["races"]:
                race = load_json(DATA / "races" / d / f"{v['jcd']}{r['rno']:02d}.json", {})
                for b in (race.get("racelist") or {}).get("boats", []):
                    out[b.get("toban")].append((d, v["jcd"], r["rno"], b["frame"]))
        return out

    # ------------------------------------------------------------ 会場
    def venue_pages(self):
        for jcd, v in VENUES.items():
            page = Page(f"venue/{SLUG[jcd]}.html")
            vc, vn, vl = self.S.vc[jcd], self.S.vn[jcd], self.S.vl[jcd]
            rows = []
            for c in range(1, 7):
                a, n = vc[c], self.S.nc[c]
                if not a[0]:
                    continue
                kim = "・".join(f"{k}{a[4 + i] / a[1] * 100:.0f}%" for i, k in enumerate(KIM) if a[1] and a[4 + i] / a[1] >= 0.05)
                rows.append(f'<tr><td>{bt(c)} {c}コース</td><td class="r num"><b>{pct(a[1] / a[0], 1)}</b></td><td class="r num sub">{pct(n[1] / n[0], 1)}</td><td class="r num">{pct((a[1] + a[2]) / a[0], 1)}</td><td class="r num">{pct((a[1] + a[2] + a[3]) / a[0], 1)}</td><td>{e(kim)}</td></tr>')
            mx = max(c["win"] for c in v["courses"])
            bars = "".join(f'<div><small>{c["win"]:.1f}%</small><i style="height:{c["win"] / mx * 76:.0f}px"></i>{bt(c["course"])}</div>' for c in v["courses"])
            c1 = vc[1][1] / vc[1][0] if vc[1][0] else None
            n1 = self.S.nc[1][1] / self.S.nc[1][0]
            lead = ""
            if c1:
                diff = (c1 - n1) * 100
                lead = f"{v['name']}の1コース1着率は{c1 * 100:.1f}%で、全国平均（{n1 * 100:.1f}%）より{abs(diff):.1f}ポイント{'高く、イン有利' if diff > 0 else '低く、イン受難'}の水面です。"
            loss = ""
            if vn:
                items = {"差され": vl.get("2-差し", 0), "捲られ": sum(x for k, x in vl.items() if k.endswith("-まくり")), "捲り差され": sum(x for k, x in vl.items() if k.endswith("-まくり差し"))}
                loss = "・".join(f"{k} {x / vn * 100:.1f}%" for k, x in items.items())
            today = next((x for x in self.idx.get("venues", []) if x["jcd"] == jcd), None)
            todayh = ""
            if today:
                todayh = (f'<section class="panel venue-block"><h2>{jdate(self.idx["date"])}のレース <small>{e(today.get("title", ""))}・{e(" ".join(day_parts(today.get("day", ""))[::-1]))}</small></h2>'
                          f'<div class="tbl-wrap"><table class="rtab"><tbody>{self.race_rows(page, self.idx["date"], jcd, today["races"])}</tbody></table></div></section>')
            body = f"""<h1>{e(v['name'])}ボートレース場の特徴とコース別成績</h1>
<p>{e(lead)}{e(v.get('note', ''))}</p>
<p class="sub">水質：{e(v.get('water', ''))}・干満差：{'あり' if v.get('tide') else 'なし'}</p>
{todayh}
<section class="panel"><h2>コース別1着率 <small>公式・{e((load_json(Path(__file__).parent / 'venues.json', {}) or {}).get('period', ''))}</small></h2><div class="courses">{bars}</div></section>
<section class="panel"><h2>コース別成績と決まり手 <small>直近1年・{int(vn):,}レース</small></h2><div class="tbl-wrap"><table><thead><tr><th>コース</th><th class="r">1着率</th><th class="r">全国</th><th class="r">2連対率</th><th class="r">3連対率</th><th>1着の決まり手</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{f'<p class="sub">1コースの負け方（全レースに対する割合）：{e(loss)}</p>' if loss else ''}</section>"""
            self.put(page.path, page.render(f"{v['name']}ボートレース場の特徴・コース別成績・決まり手｜{SITE_NAME}",
                                            f"{v['name']}ボートレース場の水面の特徴、コース別1着率・連対率、決まり手、1コースの負け方を公式データから集計。", body, [("", v["name"])]))

    # ------------------------------------------------------------ ツール・解説・JSページ
    def static_pages(self):
        page = Page("tools/composite.html")
        body = """<h1>合成オッズ計算ツール</h1>
<p>複数の買い目のオッズを入れると、合成オッズと「どれが当たっても払戻がほぼ同じになる配分（100円単位）」を計算します。</p>
<section class="panel" style="display:grid;gap:10px"><div id="rows" class="calc-rows"></div>
<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" id="add" class="btn">買い目を追加</button><label>予算 <input id="budget" type="number" value="1000" step="100" min="100" inputmode="numeric"> 円</label></div>
<div id="out" class="tiles"></div><div class="tbl-wrap"><table><thead><tr><th>#</th><th class="r">オッズ</th><th class="r">配分</th><th class="r">当たれば</th></tr></thead><tbody id="alloc"></tbody></table></div></section>
<section class="panel"><h2>合成オッズとは</h2><p>複数の買い目をまとめて1つの馬券・舟券とみなしたときのオッズです。計算式は <b>1 ÷（1/オッズ① ＋ 1/オッズ② ＋ …）</b>。例えば 14.1倍・24.8倍・21倍・28.5倍・212.3倍の5点なら、1 ÷（0.071＋0.040＋0.048＋0.035＋0.005）＝ 約5.03倍です。</p>
<p>合成オッズどおりの払戻を受け取るには、オッズの低い目ほど多く買う「配分」が必要です。均等に100円ずつ買うと、当たった目によって払戻が大きく変わります。</p>
<p>合成オッズが低いほど当たりやすくなりますが、長く続けると控除率（3連単は約25%）の分だけ負けやすくなります。点数を増やしすぎて合成オッズが1〜2倍台になる買い方は、的中しても利益がほとんど出ません。</p></section>
<script>
(function(){var rows=document.getElementById('rows');function add(v){var d=document.createElement('div');d.innerHTML='<input type="number" step="0.1" min="1" placeholder="オッズ" value="'+(v||'')+'" inputmode="decimal"> 倍';rows.appendChild(d);d.querySelector('input').addEventListener('input',calc)}
function calc(){var o=[].map.call(rows.querySelectorAll('input'),function(i){return parseFloat(i.value)}).filter(function(x){return x>=1});var out=document.getElementById('out'),tb=document.getElementById('alloc');if(!o.length){out.innerHTML='';tb.innerHTML='';return}
var s=o.reduce(function(a,x){return a+1/x},0),comp=1/s,B=Math.max(100,Math.round((parseFloat(document.getElementById('budget').value)||1000)/100)*100);
var u=o.map(function(x){return Math.max(1,Math.round(B*(1/x)/s/100))}),tot=u.reduce(function(a,b){return a+b},0)*100,mn=Math.min.apply(null,u.map(function(k,i){return k*100*o[i]}));
out.innerHTML='<div class="tile"><small>合成オッズ</small><b>'+comp.toFixed(2)+'倍</b></div><div class="tile"><small>配分の合計</small><b>¥'+tot.toLocaleString()+'</b></div><div class="tile"><small>最低払戻</small><b>¥'+Math.round(mn).toLocaleString()+'</b></div><div class="tile"><small>当たる確率の目安（控除25%）</small><b>'+(75/comp).toFixed(0)+'%</b></div>';
tb.innerHTML=o.map(function(x,i){return '<tr><td>'+(i+1)+'</td><td class="r num">'+x+'倍</td><td class="r num">¥'+(u[i]*100).toLocaleString()+'</td><td class="r num">¥'+Math.round(u[i]*100*x).toLocaleString()+'</td></tr>'}).join('')}
document.getElementById('add').onclick=function(){add()};document.getElementById('budget').addEventListener('input',calc);[14.1,24.8,21,28.5,212.3].forEach(add);calc()})();
</script>"""
        self.put(page.path, page.render(f"合成オッズ計算ツール｜ボートレース・競馬の配分計算｜{SITE_NAME}",
                                        "合成オッズを自動計算。複数の買い目のオッズを入れると、合成オッズと、どれが当たっても払戻がそろう100円単位の配分を表示します。", body, [("", "合成オッズ計算")]))
        page = Page("guide/sanrentan.html")
        body = """<h1>3連単の買い方と、長く続けると負けやすい理由</h1>
<section class="panel"><h2>3連単とは</h2><p>1着・2着・3着の艇を、着順どおりに当てる買い方です。組み合わせは6×5×4＝120通り。当てるのは難しい分、配当は高くなります。</p></section>
<section class="panel"><h2>控除率（払戻率）</h2><p>ボートレースは、売上の一部を差し引いた残りを的中者で分け合う仕組みです。3連単の払戻率は約75%で、でたらめに買い続けると、平均して賭けた金額の75%しか戻らない計算になります。</p>
<p>当サイトが過去9千レースで検証したところ、オッズの高い目（300倍以上）を全部買うと回収率は約55%、オッズの低い目（1〜20倍）は約80%でした。人気薄ほど買われすぎていて、穴狙いは数字の上ではいちばん不利です。</p></section>
<section class="panel"><h2>点数と合成オッズ</h2><p>本命から10点以上広げて買うと、合成オッズが1〜2倍台になり、当たっても利益はほとんど出ません。当サイトの推奨買い目は、合成オッズが5倍を下回らない範囲で組んでいます。</p></section>"""
        self.put(page.path, page.render(f"3連単の買い方と控除率｜ボートレース初心者ガイド｜{SITE_NAME}",
                                        "ボートレース3連単の基本、払戻率（控除率）の仕組み、オッズ帯ごとの回収率の違い、点数と合成オッズの考え方を解説。", body, [("", "3連単の買い方")]))
        page = Page("guide/course.html")
        n = self.S.nc
        cr = " ".join(f"{c}コース{n[c][1] / n[c][0] * 100:.1f}%" for c in range(1, 7) if n[c][0])
        body = f"""<h1>コースと決まり手の基本</h1>
<section class="panel"><h2>コースの有利不利</h2><p>ボートレースはスタート後の最初のターン（1マーク）を内側で回れる艇が有利です。直近1年の全国の1着率は {e(cr)} です。</p></section>
<section class="panel"><h2>決まり手</h2><ul class="comments"><li><b>逃げ</b>：1コースの艇がそのまま先頭で1マークを回って勝つ。</li><li><b>差し</b>：先に回った艇の内側を突いて抜け出す。2コースに多い。</li><li><b>捲り</b>：外から内側の艇を一気に回り込む。3・4コースに多い。</li><li><b>捲り差し</b>：外の艇が内の艇を捲りつつ、その内側を差す。</li><li><b>抜き・恵まれ</b>：1マーク後に逆転する、他艇の失格などで繰り上がる。</li></ul></section>
<section class="panel"><h2>選手のコース別成績を見る</h2><p>同じ選手でもコースによって成績は大きく変わります。<a href="../targets.html">狙い目レーサーまとめ</a>や各選手のページで、コース別の1着率や決まり手を確認できます。</p></section>"""
        self.put(page.path, page.render(f"ボートレースのコースと決まり手の基本｜{SITE_NAME}", "ボートレースのコースごとの有利不利（全国の1着率）と、逃げ・差し・捲り・捲り差しなど決まり手の基本を解説。", body, [("", "コースと決まり手")]))
        for path, title, route, desc in (("stats.html", "的中実績", "stats", "艇ログの推奨買い目の的中率・回収率を、締切前に掲載した買い目だけで毎日自動集計。"),
                                         ("logic.html", "予想の根拠", "logic", "艇ログの予想モデルの仕組みと、過去データでの検証結果（的中率・回収率・コース巧者の分析）を公開。")):
            page = Page(path)
            body = '<div id="app"><p class="empty">読み込み中…</p></div>'
            script = f'<script>window.__ROUTE__="{route}";</script><script src="app.js"></script>'
            self.put(path, page.render(f"{title}｜{SITE_NAME}", desc, body, [("", title)], script=script))
        about = (OUT / "about_body.html")
        if about.exists():
            page = Page("about.html")
            self.put("about.html", page.render(f"このサイトについて｜{SITE_NAME}", "艇ログの運営者情報、予想の仕組み、免責事項、プライバシーポリシー。", about.read_text(encoding="utf-8"), [("", "このサイトについて")]))

    # ------------------------------------------------------------ 全体
    def races(self):
        base = DATA / "races"
        if not base.exists():
            return
        limit = (self.now - timedelta(days=RACE_KEEP_DAYS)).strftime("%Y%m%d")
        self.day_races = {}
        for day in sorted(base.iterdir()):
            if not day.is_dir() or day.name < limit:
                continue
            for p in sorted(day.glob("*.json")):
                race = load_json(p, {})
                if race.get("racelist") or race.get("result"):
                    self.race_page(day.name, race["jcd"], race)
                if race.get("jcd"):
                    self.day_races.setdefault(day.name, []).append(race)
        # 今日のレースは出走表がまだでもページを作る（リンク切れ防止）
        d = self.idx.get("date")
        for v in self.idx.get("venues", []):
            for r in v.get("races", []):
                path = f"race/{d}/{SLUG[v['jcd']]}-{r['rno']}.html"
                if path not in self.files:
                    stub = {"date": d, "jcd": v["jcd"], "venue": v["name"], "rno": r["rno"], "deadline": r.get("deadline", "")}
                    if r.get("result"):
                        stub["result"] = {"trifecta": r["result"], "trifecta_payout": r.get("payout"), "finished": True}
                    self.race_page(d, v["jcd"], stub)

    def not_found(self):
        page = Page("404.html")
        body = f'<h1>ページが見つかりません</h1><p>URLが変わったか、まだ作られていないページです。</p><p><a href="{page.u("index.html")}">今日のレース一覧へ</a></p>'
        self.put("404.html", page.render(f"ページが見つかりません｜{SITE_NAME}", "ページが見つかりません。", body, noindex=True))

    def sitemap(self):
        urls = [p for p in self.files if p.endswith(".html") and p != "404.html" and not p.endswith("-st.html")]
        today = self.now.strftime("%Y-%m-%d")
        body = "".join(f"<url><loc>{SITE_URL}/{'' if p == 'index.html' else p}</loc><lastmod>{today}</lastmod></url>" for p in sorted(urls))
        self.put("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>')
        self.put("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")

    def build(self):
        if self.S is None:
            raise RuntimeError("course_stats.json.gz がありません")
        self.races()
        self.results_pages()
        self.index_page()
        self.targets_page()
        self.venue_pages()
        self.racer_pages()
        self.st_pages()
        self.static_pages()
        self.not_found()
        self.sitemap()
        return self.files

    def write(self):
        for p, text in self.files.items():
            f = OUT / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        print("pages", len(self.files))


def main():
    s = Site()
    s.build()
    s.write()


if __name__ == "__main__":
    main()
