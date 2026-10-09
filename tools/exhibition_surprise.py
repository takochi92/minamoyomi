"""期別展示1位率と、普段と違う単独1位の探索。予想係数は変更しない。"""
from collections import defaultdict
import argparse
import gzip
import json
from pathlib import Path

from scraper.exhibition_profile import baseline, observations, previous_terms, profiles, surprise, term_info
from tools.player_research import ROOT, eligible, interval, load_records, strength_key


def analyze(records,split='20251001'):
    data=profiles(records);cache={}
    # 各期の比較基準もその期より前の2期のみ。実力・場・コースの粗い補正。
    controls=defaultdict(lambda:defaultdict(lambda:[0,0,0]))
    national=defaultdict(lambda:defaultdict(lambda:[0,0,0]))
    for r in records:
        if not eligible(r):continue
        key=term_info(r[0])['key']
        for e in r[11]:
            for a in (controls[key][strength_key(r,e)],national[key][e[2]]):
                a[0]+=1;a[1]+=int(e[5]==1);a[2]+=int(e[5] in (1,2,3))
    expected_cache={}
    def expected(r,e):
        term=term_info(r[0])['key'];k=strength_key(r,e);ck=(term,k)
        if ck not in expected_cache:
            parts=previous_terms(r[0]);a=[0]*3;p=[0]*3
            for prev in parts:
                for i in range(3):
                    a[i]+=controls.get(prev,{}).get(k,[0]*3)[i]
                    p[i]+=national.get(prev,{}).get(e[2],[0]*3)[i]
            expected_cache[ck]=[(a[i]+50*p[i]/p[0])/(a[0]+50) for i in (1,2)] if p[0] else [1/6,1/2]
        return expected_cache[ck]
    groups=defaultdict(lambda:{'n':0,'win':0,'top3':0,'expected_win':0.0,'expected_top3':0.0})
    coverage={'outcome_races':0,'unknown_course_entries':0}
    events=[]
    for r in records:
        if not eligible(r):continue
        obs=observations(r)
        if not obs:continue
        coverage['outcome_races']+=1
        phase='前半' if r[0]<split else '後半';term=term_info(r[0])['key']
        es={e[1]:e for e in r[11]}
        for o in obs:
            if o['course'] not in range(1,7):
                coverage['unknown_course_entries']+=1;continue
            key=(term,o['toban'])
            if key not in cache:cache[key]=baseline(data,r[0],o['toban'])
            past=cache[key];s=surprise(o,past)
            if past['n']<100:continue
            labels=[]
            if o['solo1']:labels.append('全選手の単独1位')
            if s['rare_baseline']:labels.append('普段1位率10%以下：全出走')
            if s['rare_solo1']:labels.append('普段1位率10%以下：今回単独1位')
            if s['rare_solo1_improved']:labels.append('普段1位率10%以下：今回単独1位＋本人比0.03秒速い')
            ew,et=expected(r,es[o['toban']])
            for label in labels:
                a=groups[(phase,label,o['course'])];a['n']+=1;a['win']+=int(o['win']);a['top3']+=int(o['top3'])
                a['expected_win']+=ew;a['expected_top3']+=et
            if s['rare_solo1']:
                events.append({'date':r[0],'venue':r[1],'rno':r[2],'toban':o['toban'],'frame':o['frame'],
                               'course':o['course'],'reference_terms':past['terms'],**s,
                               'win':o['win'],'top3':o['top3']})
    result=[]
    for (phase,label,c),a in sorted(groups.items()):
        n=a['n'];result.append({'phase':phase,'rule':label,'course':c,**a,
                                'win_rate':a['win']/n,'top3_rate':a['top3']/n,
                                'baseline_win_rate':a['expected_win']/n,'baseline_top3_rate':a['expected_top3']/n,
                                'win_ci95':interval(a['win'],n)})
    return {'profiles':data,'period':[records[0][0],records[-1][0]],'split':split,'coverage':coverage,
            'parameters':{'previous_terms':2,'minimum_reference_starts':100,'rare_top1_rate_max':.10,'improvement_seconds_min':.03},
            'groups':result,'rare_solo1_events':events}


def report(d,names):
    ts=sorted(d['profiles']['terms'].values(),key=lambda t:t['from']);latest=ts[-1]
    lines=['# 期別展示1位率と「普段と違う速さ」の初回統計','',
           f'保存期間：{d["period"][0]}〜{d["period"][1]}。6艇の展示タイムが揃う {d["profiles"]["eligible_races"]:,} レース。',
           '級別適用期の名前と、展示を集計する審査期間を分けて保存します。養成期ではありません。',
           '公式：[級別審査](https://www.boatrace.jp/owsp/sp/extra/enjoy/guide/jiten/07/y_048.html)。5〜10月の成績は翌年の前期、11月〜翌4月は翌年の後期の審査対象です。', '',
           '## 期別の集計範囲', '', '|級別適用期|審査対象期間|記録のある範囲|展示6艇が揃うレース数|', '|---|---|---|---:|']
    for t in ts:lines.append(f'|{t["key"]}|{t["from"]}〜{t["to"]}|{t["available_from"]}〜{t["available_to"]}|{t["races"]:,}|')
    lines+=['', '期の途中の集計・保存開始前の欠測は、そのまま範囲を表示します。全公式レースが網羅されたという意味ではありません。',
            '全選手について、出走数、同率を含む展示1位数、単独1位数、平均展示順位、レース平均からの展示差、1着数・3着内数を保存。', '',
            '## 普段の展示1位が少ないA1選手の例', '',
            '現行名簿がA1で、最新の集計期に展示40走以上の選手から、展示1位率が低い順に表示。本人の意図や隠すタイプの認定ではありません。', '',
            '|選手|最新期の展示数|展示1位数|展示1位率|単独1位数|平均展示順位|', '|---|---:|---:|---:|---:|---:|']
    candidates=[(a['top1']/a['n'],t,a) for t,a in latest['players'].items() if a['n']>=40 and names.get(t,{}).get('class')=='A1']
    for _,t,a in sorted(candidates)[:10]:
        lines.append(f'|{t} {names[t]["name"]}|{a["n"]}|{a["top1"]}|{a["top1"]/a["n"]:.1%}|{a["solo1"]}|{a["rank_sum"]/a["n"]:.2f}|')
    lines+=['', '## 固定条件：普段1位率10%以下の選手が今回単独1位', '',
            '直前2期の展示100走以上・同率を含む展示1位率10%以下を「普段1位が少ない」と定義。判定に当該期の未来の成績を使いません。',
            '追加条件は、レース平均との差が本人の直前2期平均より0.03秒以上速いこと。絶対展示タイムの場間比較はしません。',
            f'前半／後半境界：{d["split"]}。当該走は直前2期のみで判定し、閾値を最も儲かった条件へ調整していません。', '',
            '|コース|前半の単独1位件数|前半1着率|後半の単独1位件数|後半1着率|後半基準1着率|後半3着内率|後半1着率95%区間|',
            '|---|---:|---:|---:|---:|---:|---:|---|']
    lookup={(a['phase'],a['rule'],a['course']):a for a in d['groups']}
    label='普段1位率10%以下：今回単独1位'
    for c in range(1,7):
        a=lookup.get(('前半',label,c));b=lookup.get(('後半',label,c))
        if not a and not b:continue
        av=f'{a["win_rate"]:.1%}' if a else '—'
        bv=[str(b['n']),f'{b["win_rate"]:.1%}',f'{b["baseline_win_rate"]:.1%}',f'{b["top3_rate"]:.1%}',f'{b["win_ci95"][0]:.1%}〜{b["win_ci95"][1]:.1%}'] if b else ['0','—','—','—','—']
        lines.append(f'|{c}|{a["n"] if a else 0}|{av}|'+ '|'.join(bv)+'|')
    lines+=['', '### 後半：本人比の改善を追加した場合', '',
            '|コース|条件|件数|1着率|3着内率|基準1着率|', '|---|---|---:|---:|---:|---:|']
    for label in ('全選手の単独1位','普段1位率10%以下：全出走','普段1位率10%以下：今回単独1位＋本人比0.03秒速い'):
        for c in range(1,7):
            a=lookup.get(('後半',label,c))
            if a:lines.append(f'|{c}|{label}|{a["n"]:,}|{a["win_rate"]:.1%}|{a["top3_rate"]:.1%}|{a["baseline_win_rate"]:.1%}|')
    lines+=['', '## 判断と使い方', '',
            '- 今回の0.03秒条件は、普段1位が少ない選手の単独1位の大半ですでに満たされる。独立した追加材料と考えず、直線・周回との一致などを別に検証する。',
            '- 一般的な「展示1位」の効果と、普段1位が少ない選手だけの追加効果は分けて確認する。率の差だけでは後者の優位性を証明しない。',
            '- 基準は直前2期の場×実進入コース×当時級別×当時全国勝率の粗い成績。相手の実力、モーター更新、選手の調整、気象などの交絡は残る。',
            '- 公式結果に記録された展示タイムでの事後探索。本番進入を使った成績を、そのまま締切前の予想成績としない。',
            '- 同率1位を全員に加算するため、全選手合計の展示1位数はレース数を超える。単独1位を別に保存し、タイで発生する偽の珍しさを避ける。',
            '- 表示例：「本人比：普段の展示1位率8%／過去150走 → 今回単独1位」「本人の通常展示差より0.04秒速い」。実在レースの数値ではない。',
            '- 展示で隠す意図・行き足の良さを断定しない。今節の直線・周回・まわり足との一致、乗り手を差し引いたモーター評価、内側艇とのST差を合わせて追跡する。',
            '- 前期・後期の集計を既存の展示統計に追加するが、買い目・モデル係数・金銀枠は変更しない。回収率の改善は未検証。', '',
            '再実行：`python -m tools.exhibition_surprise`', '']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--split',default='20251001')
    p.add_argument('--output',type=Path,default=ROOT/'research/exhibition-surprise');args=p.parse_args()
    records,_=load_records();d=analyze(records,args.split)
    names=json.loads((ROOT/'scraper/racers.json').read_text())['racers']
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'REPORT.md').write_text(report(d,names),encoding='utf-8')
    (args.output/'statistics.json.gz').write_bytes(gzip.compress(json.dumps(d,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    print(json.dumps({'profile_races':d['profiles']['eligible_races'],'rare_solo1_events':len(d['rare_solo1_events']),**d['coverage']},ensure_ascii=False))


if __name__=='__main__':main()
