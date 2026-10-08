"""結果履歴の探索統計。予想モデルには接続しない。

python -m tools.player_research --output research/player-statistics
前半で候補を選び、固定した基準を後半に適用する。進入・決まり手・本番STは
事後の分類に限る。この集計をそのまま締切前の予想特徴量として使わない。
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METHODS = ('逃げ', '差し', 'まくり', 'まくり差し', '抜き', '恵まれ')


def load_records(root=ROOT):
    records, seen, duplicates = [], set(), 0
    for path in sorted((root / 'history').glob('*.jsonl.gz')):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                key = tuple(r[:3])
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                records.append(r)
    return sorted(records, key=lambda r: tuple(r[:3])), duplicates


def eligible(r):
    """成立した6艇レース。事故艇は着外として残し、進入不明は除外。"""
    es = r[11]
    return (len(es) == 6 and {e[2] for e in es} == set(range(1, 7))
            and {e[0] for e in es} == set(range(1, 7))
            and all(sum(e[5] == p for e in es) == 1 for p in (1, 2, 3))
            and r[3] in METHODS and bool(r[8]) and (r[9] or 0) > 0)


def strength_key(r, e):
    b = e[7] if len(e) > 7 else None
    return (r[1], e[2], b[0] if b else '?', int(b[1]) if b and b[1] is not None else -1)


def rate(k, n):
    return round(k / n, 6) if n else None


def interval(k, n):
    if not n:
        return None
    z, p = 1.96, k / n
    den = 1 + z*z/n
    mid = (p + z*z/(2*n)) / den
    half = z*((p*(1-p)/n + z*z/(4*n*n))**0.5)/den
    return [round(mid-half, 6), round(mid+half, 6)]


def analyze(records, split):
    train = [r for r in records if r[0] < split and eligible(r)]
    test = [r for r in records if r[0] >= split and eligible(r)]
    base, national = defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0])
    for r in train:
        for e in r[11]:
            for v in (base[strength_key(r, e)], national[e[2]]):
                v[0] += 1; v[1] += int(e[5] == 1); v[2] += int(e[5] in (1, 2))

    def expected(r, e, top2=False):
        i = 2 if top2 else 1
        nn = national[e[2]]
        prior = nn[i]/nn[0] if nn[0] else (1/3 if top2 else 1/6)
        n, w, t = base.get(strength_key(r, e), (0, 0, 0))
        return ((t if top2 else w) + 50*prior)/(n+50)

    phases = {}
    for label, rs in (('train', train), ('test', test)):
        course = defaultdict(lambda: [0, 0, 0, 0, 0.0])
        escape, loss = defaultdict(Counter), defaultdict(Counter)
        attack, muscles, matchup = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
        for r in rs:
            es = r[11]; by = {e[2]: e for e in es}
            winners = {p: next(e for e in es if e[5] == p) for p in (1, 2, 3)}
            win, sec, third = (winners[p] for p in (1, 2, 3))
            inc = by[1]; kim = r[3]
            for e in es:
                c = course[(e[1], e[2])]
                c[0] += 1
                for p in (1, 2, 3):
                    c[p] += int(e[5] == p)
                c[4] += expected(r, e)
            if win[2] == 1 and kim == '逃げ':
                for k in (inc[1], 'ALL'):
                    escape[k]['n'] += 1
                    escape[k][f'second_{sec[2]}'] += 1
                    escape[k][f'third_{third[2]}'] += 1
            else:
                for k in (inc[1], 'ALL'):
                    loss[k]['n'] += 1
                    loss[k][f'{win[2]}_{kim}'] += 1
            if kim in ('まくり', 'まくり差し'):
                for k in ((win[1], win[2], kim), ('ALL', win[2], kim)):
                    a = attack[k]; a['n'] += 1
                    a['in_out'] += int(inc[5] not in (1, 2, 3))
                    a[f'pair_{sec[2]}-{third[2]}'] += 1
                    a['payout_sum'] += r[9]
                muscles[(win[2], kim)][f'{sec[2]}-{third[2]}'] += 1
            b3 = by[3][7] if len(by[3]) > 7 else None
            if b3:
                tag = '3コースA1' if b3[0] == 'A1' else '3コース非A1'
                for k in ((inc[1], tag), ('ALL', tag)):
                    m = matchup[k]; m['n'] += 1
                    m['in_win'] += int(inc[5] == 1)
                    m['two_sashi'] += int(win[2] == 2 and kim == '差し')
                    m['in_and_three_out'] += int(inc[5] not in (1, 2, 3) and by[3][5] not in (1, 2, 3))
                    m['three_out'] += int(by[3][5] not in (1, 2, 3))
        phases[label] = {'races': len(rs), 'course': course, 'escape': escape,
                         'loss': loss, 'attack': attack, 'muscles': muscles, 'matchup': matchup}
    candidates = []
    # 後半成績を見て候補を絞らない。前半の件数・縮約差のみで固定する。
    for (t, c), a in phases['train']['course'].items():
        n, w, _, _, ex = a
        if c == 1 or n < 100 or w/n <= ex/n:
            continue
        score = (w-ex)/(n+100)
        candidates.append((score, t, c))
    candidates.sort(reverse=True)
    phases['candidates'] = candidates[:50]
    return phases, expected


def motor_changes(records, expected):
    """同一場・号機・更新期の節比較。選手の展示差基準は前日以前のみ。"""
    from scraper.motoradj import renewed_venues
    grouped = defaultdict(list)
    for r in records:
        grouped[r[0]].append(r)
    epochs, zero_last, rider = {}, {}, defaultdict(lambda: [0, 0.0])
    meetings = defaultdict(list)
    usable, unknown_epoch = 0, 0
    for day, rs in sorted(grouped.items()):
        ordinal = datetime.strptime(day, '%Y%m%d').toordinal()
        for j in renewed_venues(rs):
            if ordinal-zero_last.get(j, -99) > 3:
                epochs[j] = day
            zero_last[j] = ordinal
        pending = []
        for r in rs:
            es = r[11]
            exs = [e[6] for e in es if len(e) > 6 and e[6]]
            if len(exs) != 6:
                continue
            avg = sum(exs)/600
            for e in es:
                dev = e[6]/100-avg
                rn, rd = rider[(r[1], e[1])]
                adj = dev-rd/(rn+20)
                pending.append(((r[1], e[1]), dev))
                mno = e[8] if len(e) > 8 else None
                if mno is None:
                    continue
                if r[1] not in epochs:
                    unknown_epoch += 1
                    continue
                key = (r[1], mno, epochs[r[1]])
                arr = meetings[key]
                if not arr or ordinal-arr[-1]['last_day'] > 2:
                    arr.append({'from': day, 'to': day, 'last_day': ordinal, 'n': 0,
                                'ex_sum': 0.0, 'rider_adjusted_ex_sum': 0.0,
                                'top2': 0, 'expected_top2': 0.0, 'users': Counter()})
                m = arr[-1]; m['to'] = day; m['last_day'] = ordinal; m['n'] += 1
                m['ex_sum'] += dev; m['rider_adjusted_ex_sum'] += adj
                m['top2'] += int(e[5] in (1, 2)); m['expected_top2'] += expected(r, e, True)
                m['users'][e[1]] += 1; usable += 1
        for k, dev in pending:
            rider[k][0] += 1; rider[k][1] += dev
    output = []
    for (j, mno, epoch), ms in meetings.items():
        if len(ms) < 2 or ms[-1]['to'] < (datetime.strptime(records[-1][0], '%Y%m%d')-timedelta(days=14)).strftime('%Y%m%d'):
            continue
        prev, cur = ms[-2:]
        if min(prev['n'], cur['n']) < 5:
            continue
        def pack(m):
            n = m['n']
            return {'from': m['from'], 'to': m['to'], 'n': n, 'users': dict(m['users']),
                    'ex_dev_seconds': round(m['ex_sum']/n, 4),
                    'rider_adjusted_ex_dev_seconds': round(m['rider_adjusted_ex_sum']/n, 4),
                    'top2_rate': rate(m['top2'], n),
                    'top2_above_baseline': round((m['top2']-m['expected_top2'])/(n+20), 4)}
        p, c = pack(prev), pack(cur)
        output.append({'venue': j, 'motor': mno, 'renewal': epoch, 'previous': p, 'latest': c,
                       'delta_seconds': round(c['rider_adjusted_ex_dev_seconds']-p['rider_adjusted_ex_dev_seconds'], 4)})
    return {'usable_entries': usable, 'unknown_epoch_entries': unknown_epoch,
            'recent_changes': sorted(output, key=lambda x: x['delta_seconds'])}


def serializable(phases):
    out = {}
    for label in ('train', 'test'):
        phase = phases[label]
        out[label] = {k: ({'|'.join(map(str, key)) if isinstance(key, tuple) else str(key):
                          dict(v) if isinstance(v, Counter) else v for key, v in val.items()}
                         if isinstance(val, dict) else val) for k, val in phase.items()}
    out['candidate_keys_selected_on_train'] = [[t, c, round(s, 6)] for s, t, c in phases['candidates']]
    return out


def report(records, duplicate, phases, motors, split, names):
    lo, hi = records[0][0], records[-1][0]
    good = phases['train']['races']+phases['test']['races']
    lines = ['# 艇ろぐ：選手・筋目の初回統計', '',
             f'対象：{lo}〜{hi}。保存済み {len(records):,} レース／延べ {sum(len(r[11]) for r in records):,} 艇。',
             f'6艇・進入判明・3着まで確定した成立レース {good:,} 件を分析。除外 {len(records)-good:,} 件。重複 {duplicate} 件。',
             f'前半：{lo}〜{(datetime.strptime(split,"%Y%m%d")-timedelta(days=1)).strftime("%Y%m%d")}、後半：{split}〜{hi}。', '',
             '本番進入と決まり手による**事後の探索統計**。締切前の予測精度・回収率を示すものではありません。',
             '事故艇は着外として含めます。欠場や進入不明のレースは除外します。対象は全レースと異なるため分母を併記します。', '',
             '## まくり・まくり差しの筋目', '',
             '前半で最頻だった2・3着コースを固定して、後半の出現率を確認。数字は艇番ではなく実際の進入コースです。', '',
             '|勝ちコース|決まり手|前半件数|前半の最多2→3着|前半率|後半件数|後半率|後半イン着外率|',
             '|---|---|---:|---|---:|---:|---:|---:|']
    for c in range(2, 7):
        for kim in ('まくり', 'まくり差し'):
            a = phases['train']['attack'].get(('ALL', c, kim), Counter())
            b = phases['test']['attack'].get(('ALL', c, kim), Counter())
            pairs = [(v,k) for k,v in a.items() if k.startswith('pair_')]
            if not pairs or not b['n']:
                continue
            v,k = max(pairs)
            lines.append(f'|{c}|{kim}|{a["n"]:,}|{k[5:]}|{v/a["n"]:.1%}|{b["n"]:,}|{b[k]/b["n"]:.1%}|{b["in_out"]/b["n"]:.1%}|')
    lines += ['', '## コース巧者の候補（前半で選定）', '',
              '場×進入コース×当時の級別×当時の全国勝率（1点刻み）を基準に比較。基準は前半で固定。相手の強さ・モーターなどは未補正。',
              '前半100走以上、1着率が基準を上回る候補を縮約差で順位付け。後半を見て候補を選び直していません。',
              '下表は上位15候補。全50候補と全選手・全コースはJSONに保存。多数の候補を探索したため確証ではありません。', '',
              '|登番・選手|コース|前半走数|前半1着率|後半走数|後半1着率|後半基準|後半95%区間|',
              '|---|---:|---:|---:|---:|---:|---:|---|']
    for score,t,c in phases['candidates'][:15]:
        a = phases['train']['course'][(t,c)]; b = phases['test']['course'].get((t,c), [0]*5)
        ci = interval(b[1],b[0])
        vals = [f'{b[1]/b[0]:.1%}', f'{b[4]/b[0]:.1%}', f'{ci[0]:.1%}〜{ci[1]:.1%}'] if b[0] else ['—']*3
        lines.append(f'|{t} {names.get(t,{}).get("name","名称未登録")}|{c}|{a[0]}|{a[1]/a[0]:.1%}|{b[0]}|'+ '|'.join(vals)+'|')
    lines += ['', '## イン逃げ時の相手コース', '', '|相手コース|前半2着率|後半2着率|後半3着率|', '|---|---:|---:|---:|']
    a,b = (phases[p]['escape']['ALL'] for p in ('train','test'))
    for c in range(2,7):
        lines.append(f'|{c}|{a[f"second_{c}"]/a["n"]:.1%}|{b[f"second_{c}"]/b["n"]:.1%}|{b[f"third_{c}"]/b["n"]:.1%}|')
    lines += ['', '### イン選手ごとの「逃げたときの2着」の偏り', '',
              '前半の逃げ100件以上から、全国分布より多かった相手コースを選定。相手選手の実力は未補正。', '',
              '|イン選手|相手2着コース|前半逃げ数|前半率|後半逃げ数|後半率|', '|---|---:|---:|---:|---:|---:|']
    escape_candidates=[]
    for t,v in phases['train']['escape'].items():
        if t=='ALL' or v['n']<100:
            continue
        for c in range(2,7):
            delta=(v[f'second_{c}']-v['n']*a[f'second_{c}']/a['n'])/(v['n']+100)
            escape_candidates.append((delta,t,c))
    for _,t,c in sorted(escape_candidates,reverse=True)[:8]:
        u=phases['train']['escape'][t];v=phases['test']['escape'].get(t,Counter())
        later=f'{v[f"second_{c}"]/v["n"]:.1%}' if v['n'] else '—'
        lines.append(f'|{t} {names.get(t,{}).get("name", "名称未登録")}|{c}|{u["n"]}|{u[f"second_{c}"]/u["n"]:.1%}|{v["n"]}|{later}|')
    lines += ['', '### まくり成功時にインが着外になりやすかった選手', '',
              '前半の同一コースまくり勝ち25件以上から、コース別平均を上回る縮約差で選定。攻め方の断定ではなく、成功したレースの条件付き分布。', '',
              '|攻め選手|コース|前半まくり勝ち数|前半イン着外率|後半まくり勝ち数|後半イン着外率|後半コース平均|', '|---|---:|---:|---:|---:|---:|---:|']
    attack_candidates=[]
    for (t,c,k),v in phases['train']['attack'].items():
        if t=='ALL' or k!='まくり' or v['n']<25:
            continue
        avg=phases['train']['attack'][('ALL',c,k)]
        delta=(v['in_out']-v['n']*avg['in_out']/avg['n'])/(v['n']+30)
        if delta>0:attack_candidates.append((delta,t,c))
    for _,t,c in sorted(attack_candidates,reverse=True)[:8]:
        u=phases['train']['attack'][(t,c,'まくり')];v=phases['test']['attack'].get((t,c,'まくり'),Counter())
        avg=phases['test']['attack'][('ALL',c,'まくり')]
        later=f'{v["in_out"]/v["n"]:.1%}' if v['n'] else '—'
        lines.append(f'|{t} {names.get(t,{}).get("name", "名称未登録")}|{c}|{u["n"]}|{u["in_out"]/u["n"]:.1%}|{v["n"]}|{later}|{avg["in_out"]/avg["n"]:.1%}|')
    lines += ['', f'逃げの分母：前半 {a["n"]:,}、後半 {b["n"]:,}。選手別の相手分布・負け方もJSONに保存。', '',
              '## 3コースA1とインの関係（後半・全選手）', '',
              '|条件|レース数|イン1着|2コース差し勝ち|インと3コースが共に着外|3コース着外|', '|---|---:|---:|---:|---:|---:|']
    for tag in ('3コースA1','3コース非A1'):
        a=phases['test']['matchup'][('ALL',tag)]
        lines.append(f'|{tag}|{a["n"]:,}|'+ '|'.join(f'{a[k]/a["n"]:.1%}' for k in ('in_win','two_sashi','in_and_three_out','three_out'))+'|')
    lines += ['', 'これは相関です。抵抗・張り合い・ツケマイの実行は結果データだけでは判定できません。相手の実力や場なども異なります。', '',
              '## モーターの節間変化', '',
              f'更新を確認した期間内で使えた展示付き記録 {motors["usable_entries"]:,} 艇。更新期不明で除外 {motors["unknown_epoch_entries"]:,} 艇。',
              '同じ場・号機・更新期の直近2節を比較。節は使用日間隔が2日以下のまとまりで推定し、公式の節IDではありません。',
              '展示タイムはレース平均との差を取り、乗り手の前日までの場別展示差を20走相当で縮約して差し引きます。負の変化は速い方向。',
              '全国成績から見た2連対の上振れも保存。伸び型・出足型の断定はしません。', '',
              '|場コード|号機|前節期間|前節走数|最新節期間|最新節走数|補正展示差の変化（秒）|', '|---|---:|---|---:|---|---:|---:|']
    for x in motors['recent_changes'][:10]:
        p,c=x['previous'],x['latest']
        lines.append(f'|{x["venue"]}|{x["motor"]}|{p["from"]}〜{p["to"]}|{p["n"]}|{c["from"]}〜{c["to"]}|{c["n"]}|{x["delta_seconds"]:+.4f}|')
    lines += ['', '## 次の検証と保存した統計', '',
              '- 選手×実進入コース：出走数、1・2・3着数、基準期待勝数。',
              '- イン選手：逃げ時の2・3着コース、負けた相手コースと決まり手。',
              '- 攻め選手×コース×決まり手：成功時の相手2・3着コース、イン着外数。成功時だけの条件付き分布なので攻めの成功確率ではありません。',
              '- イン選手×3コース当時級別：イン1着、2コース差し、共倒れの相関。',
              '- モーター：前節・最新節の使用選手、補正展示差、2連対上振れ。',
              '- 後半を検証に使用済み。今後この結果を見てルールを改定する場合、さらに未使用の将来期間で検証する。',
              '- 回収率は未検証。締切前の展示進入とオッズで買い目を固定し、金額・払戻・返還を記録する検証が次の段階。',
              '- 最新の級別を過去レースに当てはめない。選手名は表示用の現行名簿、級別は各レースの番組表。',
              '- 伸び・出足はオリジナル展示の各項目と映像の照合が必要。通常展示タイムのみで代用しない。', '',
              '## 再実行', '', '```bash', f'python -m tools.player_research --split {split} --output research/player-statistics', '```', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split',default='20251001')
    parser.add_argument('--output',type=Path,default=ROOT/'research/player-statistics')
    args=parser.parse_args()
    records,dup=load_records()
    if not records or not (records[0][0] < args.split <= records[-1][0]):
        parser.error('前半・後半ともデータがある分割日を指定してください')
    phases,expected=analyze(records,args.split)
    motors=motor_changes(records,expected)
    args.output.mkdir(parents=True,exist_ok=True)
    names=json.loads((ROOT/'scraper/racers.json').read_text())['racers']
    summary=report(records,dup,phases,motors,args.split,names)
    (args.output/'REPORT.md').write_text(summary,encoding='utf-8')
    audit={'start':records[0][0],'end':records[-1][0],'split':args.split,
           'source_races':len(records),'duplicates':dup,'excluded_races':len(records)-sum(phases[p]['races'] for p in ('train','test'))}
    data={'audit':audit,'statistics':serializable(phases),'motors':motors}
    with (args.output/'statistics.json.gz').open('wb') as f:
        f.write(gzip.compress(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    print(json.dumps(audit,ensure_ascii=False))
    print(args.output/'REPORT.md')


if __name__=='__main__':
    main()
