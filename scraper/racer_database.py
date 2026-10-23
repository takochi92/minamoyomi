"""Read-only player database built from saved official results, separate from predictions.

Rates are observed frequencies, never predicted probabilities or lifetime records.
Only records dated before the build day are included. No network requests are made.
"""
from __future__ import annotations

import gzip
import html
import json
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

HISTORY = Path(__file__).resolve().parent.parent / "history"
KIM = ("逃げ", "差し", "まくり", "まくり差し", "抜き", "恵まれ")
WINDOWS = (("365", "直近1年"), ("730", "直近2年"), ("all", "保存全期間"))
# Row: date, venue, race, frame, course, place/code, ST centiseconds, F/L,
# exhibition centiseconds, motor, boat, winner's decision, winner's course, payout.


def metric(rows):
    n = st_sum = st_n = f = l = 0
    places, decisions = [0] * 6, dict.fromkeys(KIM, 0)
    for r in rows:
        if r[4] not in (1, 2, 3, 4, 5, 6) or r[5] in ("K0", "L0"):
            continue
        n += 1
        if isinstance(r[5], int) and 1 <= r[5] <= 6:
            places[r[5] - 1] += 1
        if r[5] == 1 and r[11] in decisions:
            decisions[r[11]] += 1
        if r[6] is not None and not r[7]:
            st_sum += r[6]
            st_n += 1
        f += r[7] == "F"
        l += r[7] == "L"
    return {"n": n, "places": places, "st": round(st_sum / st_n / 100, 3) if st_n else None,
            "st_n": st_n, "f": f, "l": l, "kim": decisions, "other": n - sum(places)}


def grouped(rows, key):
    groups = defaultdict(list)
    for r in rows:
        groups[str(key(r))].append(r)
    return {k: metric(v) for k, v in groups.items()}


def summarize(rows):
    inside = [r for r in rows if r[4] == 1 and r[5] not in ("K0", "L0")]
    losses = defaultdict(int)
    for r in inside:
        if r[12] and r[12] != 1:
            losses[f"{r[12]}コース・{r[11] or '決まり手不明'}"] += 1
    remain = [r for r in rows if r[4] in range(2, 7) and r[12] == 1 and r[11] == "逃げ"]
    return {"total": metric(rows), "course": grouped([r for r in rows if r[4] in range(1, 7)], lambda r: r[4]),
            "frame": grouped(rows, lambda r: r[3]), "venue": grouped(rows, lambda r: r[1]),
            "exhibition": grouped([r for r in rows if len(r) > 14 and r[14] is not None], lambda r: r[14]),
            "inside_n": len(inside), "losses": dict(sorted(losses.items(), key=lambda x: -x[1])),
            "remain": grouped(remain, lambda r: r[4])}


def build_index(races, as_of):
    """Compact per-player rows. Tied exhibitions use competition ranking (1,1,3...)."""
    out = defaultdict(list)
    first = last = ""
    count = 0
    for race in races:
        if race[0] >= as_of:
            continue
        first = min(first or race[0], race[0])
        last = max(last, race[0])
        count += 1
        ents = race[11]
        winners = [x for x in ents if x[5] == 1]
        winner_course = winners[0][2] if len(winners) == 1 else None
        exhibitions = [x[6] for x in ents if len(x) > 6 and x[6] is not None and x[6] > 0]
        for ent in ents:
            ex = ent[6] if len(ent) > 6 else None
            rank = 1 + sum(x < ex for x in exhibitions) if len(exhibitions) == 6 and ex else None
            row = [race[0], race[1], race[2], ent[0], ent[2], ent[5], ent[3], ent[4], ex,
                   ent[8] if len(ent) > 8 else None, ent[9] if len(ent) > 9 else None,
                   race[3], winner_course, race[9], rank]
            out[str(ent[1])].append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
    return {"from": first, "through": last, "as_of": as_of, "races": count, "players": dict(out)}


@lru_cache(maxsize=1)
def _load(signature, as_of):
    def records():
        for filename, _, _ in signature:
            with gzip.open(filename, "rt", encoding="utf-8") as f:
                yield from map(json.loads, f)
    return build_index(records(), as_of)


def load(as_of):
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(HISTORY.glob("*.jsonl.gz")))
    return _load(signature, as_of)


def profile(rows, as_of):
    day = datetime.strptime(as_of, "%Y%m%d")
    windows = {}
    for key, _ in WINDOWS:
        since = (day - timedelta(days=int(key))).strftime("%Y%m%d") if key != "all" else ""
        selected = [r for r in rows if since <= r[0] < as_of]
        windows[key] = {**summarize(selected), "from": min((r[0] for r in selected), default=""),
                        "through": max((r[0] for r in selected), default=""), "since": since}
    return {"windows": windows, "years": grouped(rows, lambda r: r[0][:4]), "rows": rows}


def date(value):
    return f"{value[:4]}/{value[4:6]}/{value[6:8]}" if value else "未保存"


def rate(n, d):
    return f"{100 * n / d:.1f}%" if d else "—"


def table(headers, rows):
    return '<div class="tbl-wrap"><table class="rd-table"><thead><tr>' + ''.join(f'<th>{html.escape(h)}</th>' for h in headers) + '</tr></thead><tbody>' + (''.join(rows) or f'<tr><td colspan="{len(headers)}">該当する記録はありません</td></tr>') + '</tbody></table></div>'


def stats_row(label, m):
    p, n = m["places"], m["n"]
    small = '<br><small>少数例</small>' if 0 < n < 30 else ''
    return '<tr><th>' + html.escape(label) + small + '</th>' + ''.join(f'<td>{v}</td>' for v in (
        n, rate(p[0], n), rate(sum(p[:2]), n), rate(sum(p[:3]), n),
        f'{m["st"]:.2f} ({m["st_n"]})' if m["st"] is not None else '—', f'{m["f"]}/{m["l"]}')) + '</tr>'


def section(title, content, note=""):
    return f'<section class="panel rd-section"><h2>{html.escape(title)}</h2>{content}' + (f'<p class="sub">{html.escape(note)}</p>' if note else '') + '</section>'


def render(toban, info, data, meta, page, venues, slugs, today_html="", extras=""):
    """Server-render a usable 1-year overview; JS adds windows, tabs and pagination."""
    esc = html.escape
    w = data["windows"]["365"]
    m = w["total"]
    n, p = m["n"], m["places"]
    head = f'''<header class="rd-hero"><a class="rd-back" href="index.html">← 選手・モーター検索</a>
<div class="rd-heading"><div><span class="eyebrow">RACER DATABASE / 登録番号 {esc(toban)}</span><h1>{esc(info['name'])}<button type="button" class="fav-btn" data-toban="{esc(toban)}" data-name="{esc(info['name'])}" aria-label="お気に入り" aria-pressed="false" hidden>☆</button></h1>
<p>{esc(info.get('branch',''))}支部 · {esc(info.get('class',''))}級{(' · '+str(info['ki'])+'期') if info.get('ki') else ''} · <a href="{page.u('motor.html')}">モーター相場を見る →</a></p></div><div class="rd-official"><small>公式期別勝率</small><strong>{format(info['win'], '.2f') if info.get('win') is not None else '—'}</strong><small>{esc(meta.get('roster_source', '適用期未確認'))}</small></div></div>
<p class="sub">公式期別勝率は着順点の平均です。下の1着率・連対率は艇ろぐの保存レースから集計した実測値です。</p></header>
<section class="rd-controls" aria-label="成績の表示期間"><div class="rd-period">{''.join(f'<button type="button" data-rd-window="{k}" aria-pressed="{str(k == "365").lower()}" class="{"on" if k == "365" else ""}">{label}</button>' for k,label in WINDOWS)}</div>
<p class="sub" id="rd-period-label">直近1年 · {date(w['from'])}〜{date(w['through'])}の保存分</p>
<p class="rd-fresh">データ収録：{date(meta['from'])}〜{date(meta['through'])} · 当日分は翌朝以降に反映</p></section>
<nav class="rd-tabs" aria-label="選手データのメニュー">{''.join(f'<a href="#{k}">{v}</a>' for k,v in [('overview','概要'),('course','コース・枠'),('venue','場別'),('year','年別'),('exhibition','展示'),('history','全出走結果')])}</nav>
<section class="panel nb" id="racer-memo" data-toban="{esc(toban)}" data-name="{esc(info['name'])}" hidden></section>'''
    if today_html:
        head += section('今日の出走', '<ul class="comments">'+today_html+'</ul>')
    cards = ''.join(f'<div><span>{label}</span><strong>{value}</strong><small>{note}</small></div>' for label,value,note in (
        ('出走数', f'{n:,}', '欠場・出遅れ返還を除く'), ('1着率', rate(p[0],n), f'{p[0]}勝 / {n}走'),
        ('2連対率',rate(sum(p[:2]),n),f'{sum(p[:2])}回 / {n}走'),('3連対率',rate(sum(p[:3]),n),f'{sum(p[:3])}回 / {n}走')))
    overview = f'<div class="rd-summary" id="rd-summary">{cards}</div><div id="rd-overview-detail">' + overview_detail(w) + '</div>'
    panels = '<div id="overview" class="rd-panel">' + section('成績の概要', overview) + '</div>'
    panels += '<div id="course" class="rd-panel">' + course_detail(w) + '</div>'
    panels += '<div id="venue" class="rd-panel">' + section('場別成績', stats_table(w['venue'], lambda j: venues.get(j,{}).get('name',j)), '各場での実測成績。少数例は変動が大きいため、出走数も確認してください。') + '</div>'
    panels += '<div id="year" class="rd-panel">' + section('年別成績',stats_table(data['years'],lambda y:y+'年'), '暦年ごとの保存分。最初と最後の年は年間の全期間が揃っていない場合があります。期間ボタンの対象外です。') + '</div>'
    panels += '<div id="exhibition" class="rd-panel">' + section('展示タイム順位別の成績',stats_table(w['exhibition'],lambda k:k+'位'), '6艇の展示タイムが揃ったレースだけ。最速を1位とし、同タイムは同順位（1位・1位・3位）。展示順位による因果効果ではありません。') + '</div>'
    years = sorted(data['years'], reverse=True)
    filters = '<div class="rd-filters"><label>年<select id="rd-year"><option value="">すべて</option>' + ''.join(f'<option>{y}</option>' for y in years) + '</select></label><label>場<select id="rd-venue"><option value="">全24場</option>' + ''.join(f'<option value="{j}">{esc(v["name"])}</option>' for j,v in sorted(venues.items())) + '</select></label><label>コース<select id="rd-course"><option value="">すべて</option>'+''.join(f'<option value="{c}">{c}コース</option>' for c in range(1,7))+'</select></label></div>'
    history = filters + '<p class="sub" id="rd-history-count" aria-live="polite">全期間の保存結果。最新30件を表示しています。</p>' + '<div id="rd-history-table">' + history_table(data['rows'][:30], venues, slugs, page.u('')) + '</div><div class="rd-pagination"><button id="rd-prev" type="button" hidden>← 前へ</button><span id="rd-page"></span><button id="rd-next" type="button" hidden>次へ →</button></div><noscript>JavaScriptを有効にすると、全件の絞り込みとページ送りを利用できます。</noscript>'
    panels += '<div id="history" class="rd-panel">'+section('全出走結果（保存分）',history,'全出走結果は期間ボタンの対象外です。決まり手はレースの勝者のもの。号機の「—」は未保存で、0号機ではありません。古い結果は場公式結果で確認してください。')+'</div>'
    notes = section('データの範囲・集計方法', f'<p>収録範囲は{date(meta["from"])}〜{date(meta["through"])}。この選手の生涯通算成績ではありません。未取得のレースがある場合があります。</p><p>1・2・3連対率は、進入コースが判明した出走を分母に計算します。欠場（K0）・出遅れ返還（L0）は除外し、F・失格等は含めます。ST平均はF・Lと未取得値を除外し、括弧内に有効件数を示します。F/Lは記録上の発生回数で、現在の未消化本数ではありません。</p><p>勝者の決まり手から全攻め試行・ツケマイ・意図は判定できません。公式の生涯記録、優勝・SG履歴、適用期別の詳細は未収録です。</p>', '出典：BOAT RACE公式の競走成績・期別成績。更新処理で保存履歴を再集計します。')
    payload = {**data, "venues":{j:v['name'] for j,v in venues.items()},"slugs":slugs,"root":page.u('')}
    encoded = json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    return head+panels+extras+notes+f'<script id="rd-data" type="application/json">{encoded}</script><script src="{page.u("racer.js")}" defer></script>'


def stats_table(groups, label):
    return table(('区分','出走','1着率','2連対率','3連対率','平均ST (件)','F/L'), [stats_row(label(k),v) for k,v in sorted(groups.items(),key=lambda x:x[0], reverse=False)])


def overview_detail(w):
    m = w['total']
    decisions = ''.join(f'<div><span>{k}</span><b>{v}勝</b><small>{rate(v,m["n"])} / 全{m["n"]}走</small></div>' for k,v in m['kim'].items())
    losses = table(('勝った相手・決まり手','回数','イン全出走比'), [f'<tr><th>{html.escape(k)}</th><td>{v}</td><td>{rate(v,w["inside_n"])}</td></tr>' for k,v in w['losses'].items()])
    return '<h3>1着の決まり手</h3><div class="rd-decisions">'+decisions+'</div><h3>1コースで負けた相手</h3>'+losses+f'<p class="sub">分母は1コース全{w["inside_n"]}走。勝者を確認できたレースの結果です。</p>'


def course_detail(w):
    bars = ''
    for c in range(1,7):
        m = w['course'].get(str(c),metric([]))
        n,p = m['n'],m['places']
        bar = ''.join(f'<i class="rd-place-{i+1}" style="width:{100*v/n if n else 0:.3f}%"></i>' for i,v in enumerate(p[:3]))
        bars += f'<div class="rd-course-bar"><span class="bt bt{c}">{c}</span><div><div class="rd-bar" aria-hidden="true">{bar}</div><small>1着 {rate(p[0],n)} · 2着 {rate(p[1],n)} · 3着 {rate(p[2],n)}</small></div><b>{n}走</b></div>'
    content = '<p class="rd-legend"><span>● 1着</span><span>● 2着</span><span>● 3着</span><small>残りは4着以下・事故等</small></p>'+bars+stats_table(w['course'],lambda c:c+'コース')
    content += '<h3>コースごとの勝ち方</h3>'+table(('コース','出走',*KIM), [f'<tr><th>{html.escape(c)}コース</th><td>{m["n"]}</td>'+''.join(f'<td>{v}勝<br><small>{rate(v,m["n"])}</small></td>' for v in m['kim'].values())+'</tr>' for c,m in sorted(w['course'].items())])
    remain = table(('コース','対象数','2着率','3着率','2・3着率'), [f'<tr><th>{html.escape(c)}コース</th><td>{m["n"]}</td><td>{rate(m["places"][1],m["n"])}</td><td>{rate(m["places"][2],m["n"])}</td><td>{rate(sum(m["places"][1:3]),m["n"])}</td></tr>' for c,m in sorted(w['remain'].items())])
    return section('進入コース別成績',content,'艇番ではなく本番の進入コースで集計。勝ち方の率はそのコース全出走が分母です。') + section('艇番別成績',stats_table(w['frame'],lambda c:c+'号艇')) + section('1コースが逃げたときの残り方',remain,'この選手が2〜6コースに入り、1コースの選手が「逃げ」で勝ったレースが分母。対象数が少ない場合は変動が大きくなります。')


def history_table(rows, venues, slugs, root):
    result = []
    for r in rows:
        label = html.escape(venues.get(r[1],{}).get('name',r[1]))+f' {r[2]}R'
        st = (str(r[7])+f'{r[6]/100:.2f}') if r[6] is not None else '—'
        result.append('<tr>'+''.join(f'<td>{x}</td>' for x in (date(r[0]),label,r[3],r[4] or '—',html.escape(str(r[5])),st,f'{r[8]/100:.2f}' if r[8] else '—',r[9] if r[9] is not None else '—',r[10] if r[10] is not None else '—',html.escape(r[11] or '—')) )+'</tr>')
    return table(('日付','場・R','艇番','進入','着','ST','展示','機','艇','勝者の決まり手'),result)
