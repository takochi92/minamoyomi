"""展示の組み合わせと外側への展開候補。固定条件の探索統計（回収率ではない）。"""
import argparse
from collections import defaultdict
import gzip
import itertools
import json
import math
from pathlib import Path

from tools.player_research import ROOT, eligible, interval, load_records, strength_key
from scraper.research_snapshot import archived_records

TIMES = ('展示', '直線', '一周', 'まわり足')
RULES = [(t,) for t in TIMES]+list(itertools.combinations(TIMES, 2))+[('直線', '一周', 'まわり足')]
COMBOS = list(itertools.permutations(range(1,7),3))


def valid_time(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0


def ranks(values):
    """6艇が揃う項目のみ。タイは同順位。"""
    if set(values)!=set(range(1,7)) or not all(valid_time(v) for v in values.values()):
        return {}
    return {f:1+sum(v<values[f]-1e-9 for v in values.values()) for f in values}


def features(r):
    bs=(r.get('racelist') or {}).get('boats') or []
    se=(r.get('before') or {}).get('start_exhibition') or []
    if len(bs)!=6 or {b['frame'] for b in bs}!=set(range(1,7)) or len(se)!=6 or {e['course'] for e in se}!=set(range(1,7)) or {e['frame'] for e in se}!=set(range(1,7)):
        return None
    by={e['course']:e for e in se}
    ex={b['frame']:b.get('exhibit_time') for b in (r.get('before') or {}).get('boats') or []}
    rr={'展示':ranks(ex)}
    ori=r.get('oriten') or {}
    for k in ('直線','一周','まわり足'):
        if k not in ori.get('items',[]):
            rr[k]={};continue
        idx=ori['items'].index(k)
        vals={int(f):vs[idx] for f,vs in (ori.get('rows') or {}).items() if len(vs)>idx}
        rr[k]=ranks(vals)
    return {'course':by,'boats':{b['frame']:b for b in bs},'ranks':rr}


def matches(feat, f, rule):
    return all(feat['ranks'][t].get(f,99)<=2 for t in rule)


def external_candidates(feat):
    """結果未参照。展示F/LはST比較から除外。ST差0.03秒を固定する。"""
    def st(e):
        v=e.get('st')
        return v if isinstance(v,(float,int)) and math.isfinite(v) and v>=0 and not e.get('flag') else None
    output=set()
    for c in (3,4):
        attack=feat['course'][c];at=st(attack)
        inner=[st(feat['course'][i]) for i in range(1,c)]
        if at is None or any(x is None for x in inner) or min(inner)-at<0.03-1e-9:
            continue
        if not matches(feat,attack['frame'],('展示',)):
            continue
        for oc in range(c+1,7):
            f=feat['course'][oc]['frame']
            for receiver in (('一周','まわり足'),('直線','まわり足')):
                if matches(feat,f,receiver):
                    output.add((c,oc,'＋'.join(receiver),f))
    return sorted(output)


def market_win(r):
    odds=(r.get('odds_pre') or {}).get('v') or []
    if len(odds)!=120 or not all(valid_time(o) for o in odds):
        return {}
    inv=[1/o for o in odds];total=sum(inv)
    result=defaultdict(float)
    for combo,x in zip(COMBOS,inv):result[combo[0]]+=x/total
    return result


def source_races(root=ROOT):
    rs=archived_records(root)
    for p in sorted((root/'site'/'data'/'races').glob('*/*.json')):
        r=json.loads(p.read_text())
        key=(r['date'],r['jcd'],r['rno'])
        if key not in rs:
            r['provenance']='legacy_unverified'
            rs[key]=r
    return sorted(rs.values(),key=lambda r:(r['date'],r['jcd'],r['rno']))


def analyze(rs, history, split):
    good=[r for r in rs if (r.get('result') or {}).get('finished') and features(r)]
    if not good:raise ValueError('展示進入と結果が揃ったレースがありません')
    before=min(r['date'] for r in good)
    base=defaultdict(lambda:[0,0,0]);prior=defaultdict(lambda:[0,0,0])
    for r in history:
        if r[0]>=before or not eligible(r):continue
        for e in r[11]:
            for a in (base[strength_key(r,e)],prior[e[2]]):
                a[0]+=1;a[1]+=int(e[5]==1);a[2]+=int(e[5] in (1,2,3))
    def expected(r,b,c):
        key=(r['jcd'],c,b.get('class','?'),int(b.get('nat_win',0)))
        v=base.get(key,[0,0,0]);p=prior[c]
        return [(v[i]+50*p[i]/p[0])/(v[0]+50) for i in (1,2)] if p[0] else [1/6,1/2]
    groups=defaultdict(lambda:{'n':0,'win':0,'top3':0,'expected_win':0.0,'expected_top3':0.0,
                                'market_n':0,'market_win':0.0,'races':set()})
    outer_details=[];coverage=defaultdict(int)
    for r in good:
        feat=features(r);phase='前半' if r['date']<split else '後半'
        order={int(x['frame']):str(x['place']) for x in (r['result'].get('order') or [])}
        if len(order)!=6 or sum(p=='1' for p in order.values())!=1 or any(sum(p==str(i) for p in order.values())!=1 for i in (2,3)):
            coverage['invalid_order']+=1;continue
        coverage['races']+=1;coverage[r.get('provenance','legacy_unverified')]+=1
        for t in TIMES:coverage[t+'_complete']+=bool(feat['ranks'][t])
        market=market_win(r)
        key=f'{r["date"]}-{r["jcd"]}-{r["rno"]}'
        def add(label,c,f):
            a=groups[(phase,label,c)];a['n']+=1;a['win']+=int(order[f]=='1');a['top3']+=int(order[f] in ('1','2','3'))
            ew,et=expected(r,feat['boats'][f],c);a['expected_win']+=ew;a['expected_top3']+=et;a['races'].add(key)
            if f in market:a['market_n']+=1;a['market_win']+=market[f]
        for c,e in feat['course'].items():
            f=e['frame']
            for rule in RULES:
                if matches(feat,f,rule):add('＋'.join(rule),c,f)
        for ac,c,label,f in external_candidates(feat):
            tag=f'{ac}コース攻め候補→外側：{label}'
            add(tag,c,f)
            attacker=feat['course'][ac]['frame']
            outer_details.append({'key':key,'phase':phase,'attack_course':ac,'receiver_course':c,'receiver_frame':f,
                                  'receiver_rule':label,'receiver_place':order[f],'attacker_place':order[attacker],
                                  'kimarite':r['result'].get('kimarite'),'trifecta':r['result'].get('trifecta'),
                                  'provenance':r.get('provenance')})
    output=[]
    for (phase,rule,c),v in sorted(groups.items()):
        v={**v,'races':len(v['races'])};n=v['n']
        v.update({'phase':phase,'rule':rule,'course':c,'win_rate':v['win']/n,'top3_rate':v['top3']/n,
                  'baseline_win_rate':v['expected_win']/n,'baseline_top3_rate':v['expected_top3']/n,
                  'win_ci95':interval(v['win'],n),'top3_ci95':interval(v['top3'],n),
                  'market_win_rate':v['market_win']/v['market_n'] if v['market_n'] else None})
        output.append(v)
    player=defaultdict(lambda:{'n':0,'wins':0,'makuri_wins':0,'makurisashi_wins':0,'outer_wins':0,'outer_sashi_wins':0})
    for r in history:
        if not eligible(r):continue
        actor=next((e for e in r[11] if e[1]=='4294' and e[2] in (3,4)),None)
        if actor is None:continue
        phase='前半' if r[0]<'20251001' else '後半'
        a=player[(phase,actor[2])];winner=next(e for e in r[11] if e[5]==1)
        a['n']+=1;a['wins']+=int(actor[5]==1)
        a['makuri_wins']+=int(actor[5]==1 and r[3]=='まくり')
        a['makurisashi_wins']+=int(actor[5]==1 and r[3]=='まくり差し')
        a['outer_wins']+=int(winner[2]>actor[2])
        a['outer_sashi_wins']+=int(winner[2]>actor[2] and r[3] in ('差し','まくり差し'))
    return {'coverage':dict(coverage),'period':[min(r['date'] for r in good),max(r['date'] for r in good)],
            'split':split,'rules':RULES,'groups':output,'external_candidate_details':outer_details,
            'koga_hypothesis_descriptive':{'period':[history[0][0],history[-1][0]] if history else None,'split':'20251001',
                                          'groups':[{'phase':p,'course':c,**v} for (p,c),v in sorted(player.items())]}}


def report(data):
    coverage=data['coverage'];rows=data['groups']
    lines=['# 展示タイムの組み合わせ・外側への展開候補：初回探索', '',
           f'期間：{data["period"][0]}〜{data["period"][1]}。展示進入と6艇の結果が揃った {coverage["races"]:,} レース。',
           f'前半／後半の境界：{data["split"]}。厳密な締切前取得時刻を確認できる記録 {coverage.get("timestamped_pre_deadline",0)} 件、旧形式 {coverage.get("legacy_unverified",0)} 件。',
           '**約2週間の探索に限ります。優位性・回収率・伸び型／出足型が確立した結果ではありません。旧形式は展示とオッズの同時刻性を保証しません。**', '',
           '## 計測項目の件数', '', '|項目|6艇が揃うレース数|','|---|---:|']
    for t in TIMES:lines.append(f'|{t}|{coverage.get(t+"_complete",0):,}|')
    lines+=['', '## 3・4・5・6コース：複数タイムが同時に上位2位', '',
            '同じレースの6艇内で比較。全候補のルールを事前に固定し、最も良かった組み合わせだけを採用しません。タイは同順位。',
            '基準はこの展示データ期間より前の履歴で固定した、場×コース×当時級別×全国勝率区分の成績。相手の実力などは未補正。', '',
            '|条件|コース|前半件数|前半1着率|後半件数|後半1着率|後半基準1着率|後半3着内率|後半3着内95%区間|',
            '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    lookup={(r['phase'],r['rule'],r['course']):r for r in rows}
    for rule in RULES:
        if len(rule)<2:continue
        label='＋'.join(rule)
        for c in (3,4,5,6):
            a=lookup.get(('前半',label,c));b=lookup.get(('後半',label,c))
            if not a and not b:continue
            ci=b['top3_ci95'] if b else None
            later=[str(b['n']),f'{b["win_rate"]:.1%}',f'{b["baseline_win_rate"]:.1%}',f'{b["top3_rate"]:.1%}',f'{ci[0]:.1%}〜{ci[1]:.1%}'] if b else ['0','—','—','—','—']
            lines.append(f'|{label}|{c}|{a["n"] if a else 0}|'+(f'{a["win_rate"]:.1%}' if a else '—')+'|'+'|'.join(later)+'|')
    lines+=['', '## 3・4コースの攻め候補から、外側の艇を拾う仮説', '',
            '締切前の条件：攻め候補が展示タイム上位2位、展示STがすべての内側艇より0.03秒以上早い。F/L・ST欠損がある比較は除外。',
            'その外側に、周回＋まわり足または直線＋まわり足が同時上位2位の艇がいる場合を追跡。',
            '「抵抗された」「ツケマイした」とは認定していません。攻め候補の実際の動きは映像確認が必要です。', '',
            '|条件|受け手コース|前半件数|後半件数|後半1着率|後半3着内率|', '|---|---:|---:|---:|---:|---:|']
    tags=sorted({r['rule'] for r in rows if '攻め候補' in r['rule']})
    for tag in tags:
        for c in (4,5,6):
            a=lookup.get(('前半',tag,c));b=lookup.get(('後半',tag,c))
            if not a and not b:continue
            lines.append(f'|{tag}|{c}|{a["n"] if a else 0}|{b["n"] if b else 0}|'+(f'{b["win_rate"]:.1%}|{b["top3_rate"]:.1%}|' if b else '—|—|'))
    lines+=['', '## 古賀繁輝（4294）：ユーザーの観察仮説を登録', '',
            '本人をユーザーに確認済み。「3・4コースからの攻めが内側に抵抗され、外側に展開が向く」という仮説として記録。',
            '以下は過去約3年の実進入別成績。外側勝ちは攻めの試行・抵抗の証拠ではなく、古賀選手が攻めなかったレースも含みます。',
            '前半／後半境界は20251001（展示分析の分割とは別）。', '',
            '|期間|実進入|出走数|本人1着|まくり勝ち数|まくり差し勝ち数|外側艇1着|外側艇の差し・まくり差し勝ち|',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
    for x in data['koga_hypothesis_descriptive']['groups']:
        n=x['n']
        lines.append(f'|{x["phase"]}|{x["course"]}|{n}|{x["wins"]/n:.1%}|{x["makuri_wins"]}|{x["makurisashi_wins"]}|{x["outer_wins"]/n:.1%}|{x["outer_sashi_wins"]/n:.1%}|')
    lines+=['', '## 表示案と検証の進め方', '',
            '- 既存の金銀枠とは別に「直線＋周回上位」「周回＋まわり足上位」の**事実タグ**を出せる。現段階で「穴確定」「有利」とは表示しない。',
            '- 全コース・単項目・複数項目の分母、着率、基準、参考市場確率はJSONに保存。多数の重複条件・同じレースの艇を含むため、独立な試験ではない。',
            '- 時刻付きの締切前入力を固定し、月別履歴に保存する処理を追加。旧データを時刻確認済みに書き換えない。',
            '- 個別の場・選手・モーターでも追跡し、今後の未使用期間で再検証。展示タイムは選手の展示の仕方・調整・気象も含む。',
            '- 穴の最終判定には、展開確率の校正、判断時オッズ、固定買い目、購入額、返還を含む前向き回収率の検証が必要。',
            '- 古賀繁輝の仮説は hypotheses.json に保存。攻め方を確定した個人タグにはせず、映像・本人の展示傾向・壁選手との組み合わせで検証する。', '',
            '再実行：`python -m tools.exhibition_research --split 20261003`', '']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',default='20261003');p.add_argument('--output',type=Path,default=ROOT/'research/exhibition-statistics')
    args=p.parse_args();rs=source_races();history,_=load_records()
    result=analyze(rs,history,args.split)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'REPORT.md').write_text(report(result),encoding='utf-8')
    (args.output/'statistics.json.gz').write_bytes(gzip.compress(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    print(json.dumps(result['coverage'],ensure_ascii=False))


if __name__=='__main__':main()
