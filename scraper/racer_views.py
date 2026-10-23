"""Compact tables for comparison, donuts for composition, bars for magnitude."""
from html import escape as esc
from .racer_database import rate, date, section, metric

COLORS = ('#59d8c7', '#efb866', '#eb858e', '#89a8ec', '#667986', '#b497d8')
KINDS = ('差し', 'まくり', 'まくり差し', 'その他')
DECISIONS = ('逃げ', '差し', 'まくり', 'まくり差し', '抜き', '恵まれ')


def matrix(headers, rows, css=''):
    return '<table class="rv-matrix '+css+'"><thead><tr>'+''.join('<th scope="col">'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+(''.join(rows) or '<tr><td colspan="'+str(len(headers))+'">記録なし</td></tr>')+'</tbody></table>'


def heat(count, n):
    return f' style="background:rgba(89,216,199,{0.04+0.22*count/n if n else 0:.3f})"'


def stats_table(groups, label):
    rows, detail = [], []
    for key, m in sorted(groups.items()):
        n, p = m['n'], m['places']
        lead = esc(label(key))
        rows.append('<tr><th scope="row">'+lead+f'<small>{n}走'+(' · 少数' if 0<n<30 else '')+'</small></th>'+''.join('<td'+heat(sum(p[:i]),n)+'><b>'+rate(sum(p[:i]),n)+'</b></td>' for i in (1,2,3))+'</tr>')
        detail.append('<tr><th scope="row">'+lead+'</th><td>'+(f'{m["st"]:.2f}<small>{m["st_n"]}走</small>' if m['st'] is not None else '—')+f'</td><td>{m["f"]}</td><td>{m["l"]}</td></tr>')
    return matrix(('区分','1着','2連対','3連対'),rows)+ '<p class="rv-caption">2連対＝1・2着 ／ 3連対＝1〜3着</p><details class="rv-details"><summary>平均ST・F・Lを見る</summary>'+matrix(('区分','平均ST','F','L'),detail)+'</details>'


def inside_parts(w):
    n = w['inside_n']
    win = w['course'].get('1',metric([]))['places'][0]
    attacks = [sum(v for k,v in w['losses'].items() if k.partition('コース・')[2]==kind) for kind in KINDS[:3]]
    return [('1着',win),('差しで敗戦',attacks[0]),('まくりで敗戦',attacks[1]),('まくり差しで敗戦',attacks[2]),('その他・確認不可',n-win-sum(attacks))]


def donut(parts, n):
    offset, circles, legend = 0, [], []
    for (label,count),color in zip(parts,COLORS):
        portion=100*count/n if n else 0
        if count and n:
            circles.append(f'<circle cx="50" cy="50" r="40" pathLength="100" fill="none" stroke="{color}" stroke-width="13" stroke-dasharray="{portion:.5f} {100-portion:.5f}" stroke-dashoffset="{-offset:.5f}"/>')
        offset+=portion
        legend.append(f'<li><i style="background:{color}"></i><span>{esc(label)}</span><b>{count}回</b><small>{rate(count,n)}</small></li>')
    label='、'.join(f'{k}{v}回' for k,v in parts)
    center=rate(parts[0][1],n) if n else '—'
    return f'<div class="rv-composition"><div class="rv-donut" role="img" aria-label="1コース{n}走。{esc(label,quote=True)}"><svg viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="40" fill="none" stroke="#263743" stroke-width="13"/>{"".join(circles)}</svg><div><small>1コース1着</small><strong>{center}</strong><span>{n}走</span></div></div><ul class="rv-legend">'+''.join(legend)+'</ul></div>'


def loss_matrix(w):
    rows=[]
    for c in range(2,7):
        values=[sum(v for k,v in w['losses'].items() if k.startswith(str(c)+'コース・') and (k.partition('コース・')[2]==kind if kind!='その他' else k.partition('コース・')[2] not in KINDS[:3])) for kind in KINDS]
        rows.append(f'<tr><th scope="row"><span class="bt bt{c}">{c}</span></th>'+''.join('<td'+heat(v,w['inside_n'])+'>'+str(v)+'<small>回</small></td>' for v in values)+'</tr>')
    return matrix(('相手','差し','まくり','まくり差し','その他'),rows,'rv-loss-matrix')


def bars(items, n):
    return '<div class="rv-bars">'+''.join(f'<div class="rv-bar-row"><span>{esc(label)}</span><div class="rv-track"><i style="width:{100*count/n if n else 0:.3f}%;background:{COLORS[DECISIONS.index(label) if label in DECISIONS else i%len(COLORS)]}"></i></div><b>{count}<small>回</small></b><em>{rate(count,n)}</em></div>' for i,(label,count) in enumerate(items))+'</div>'


def overview_detail(w):
    m=w['total']
    parts=inside_parts(w)
    items=sorted(m['kim'].items(),key=lambda x:-x[1])
    wins=sum(m['kim'].values())
    return '<h3>1コースの結果</h3>'+donut(parts,w['inside_n'])+'<h3>負けた相手と勝ち方</h3>'+loss_matrix(w)+f'<p class="rv-caption">本番の進入コース別。数値は回数。対象：1コース{w["inside_n"]}走。</p><h3>1着の決まり手</h3>'+bars(items,wins)+f'<p class="rv-caption">決まり手を確認できた1着{wins}回の内訳。</p>'


def attack_rates(w):
    rows=[]
    for c in range(1,7):
        m=w['course'].get(str(c),metric([]));n=m['n']
        rows.append(f'<tr><th>{c}コース<small>{n}走</small></th>'+''.join('<td'+heat(m['kim'].get(k,0),n)+'><b>'+rate(m['kim'].get(k,0),n)+'</b><small>'+str(m['kim'].get(k,0))+'勝</small></td>' for k in ('差し','まくり','まくり差し'))+'</tr>')
    return matrix(('コース','差し','まくり','まくり差し'),rows)


def course_detail(w):
    wins=[]
    for c in range(1,7):
        m=w['course'].get(str(c),metric([]));n=m['n']
        pieces=''.join(f'<i style="width:{100*v/n if n else 0:.3f}%;background:{COLORS[i%len(COLORS)]}" title="{esc(k)} {v}勝"></i>' for i,(k,v) in enumerate(m['kim'].items()))
        wins.append(f'<div class="rv-method-row"><span class="bt bt{c}">{c}</span><div class="rv-track rv-stack">{pieces}</div><b>{sum(m["kim"].values())}<small>勝</small></b></div>')
    legend='<p class="rv-swatches">'+''.join(f'<span><i style="background:{COLORS[i%len(COLORS)]}"></i>{k}</span>' for i,k in enumerate(metric([])['kim']))+'</p>'
    rows=[]
    for c,m in sorted(w['remain'].items()):
        n=m['n'];p=m['places']
        rows.append(f'<tr><th>{esc(c)}コース<small>{n}走</small></th><td>{rate(p[1],n)}</td><td>{rate(p[2],n)}</td><td>{rate(sum(p[1:3]),n)}</td></tr>')
    return section('コース別成績',stats_table(w['course'],lambda c:c+'コース'),'本番の進入コース別。出走数が30未満の行には「少数」と表示。')+section('コースごとの勝ち方',legend+'<div class="rv-bars">'+''.join(wins)+'</div>','棒全体を各コースの全出走としています。色のない部分は1着以外・決まり手未確認。')+section('差し・まくり・まくり差しでの1着率',attack_rates(w),'各コースの全出走が分母です。攻めた試行に対する成功率ではありません。勝者の決まり手を本人の1着だけに集計しています。')+section('艇番別成績',stats_table(w['frame'],lambda c:c+'号艇'))+section('1コースが逃げたときの残り方',matrix(('コース','2着','3着','2・3着'),rows),'自艇が外に入り、1コースの選手が「逃げ」で勝ったレースが分母。')


def history_table(rows, venues):
    output=[]
    for r in rows:
        place=str(r[5]); numeric=isinstance(r[5],int)
        status=place+'着' if numeric else place
        fields=[('艇番',r[3]),('進入',str(r[4])+'コース' if r[4] else '—'),('ST',str(r[7])+f'{r[6]/100:.2f}' if r[6] is not None else '—'),('展示',f'{r[8]/100:.2f}' if r[8] else '—'),('モーター',r[9] if r[9] is not None else '未保存'),('ボート',r[10] if r[10] is not None else '未保存')]
        output.append(f'<details class="rv-race"><summary><time>{date(r[0])}</time><span>{esc(venues.get(r[1],r[1]))} {r[2]}R</span><b class="rv-finish rv-finish-{place if numeric else "other"}">{esc(status)}</b><i>＋</i></summary><dl>'+''.join(f'<div><dt>{k}</dt><dd>{esc(str(v))}</dd></div>' for k,v in fields)+f'</dl><p>勝者の決まり手：{esc(r[11] or "未確認")}</p></details>')
    return '<div class="rv-races">'+(''.join(output) or '<p class="rv-caption">該当する記録はありません。</p>')+'</div>'
