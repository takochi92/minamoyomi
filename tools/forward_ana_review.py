"""締切前に固定した根拠付き穴券と本線＋押さえを比較。旧記録を昇格しない。"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path

from scraper.ana_evaluation import PROTOCOL,PARAMS,COMBOS,finite
from scraper.research_ledger import audit,summarize
from tools.exhibition_research import source_races


def shadow_audit(row):
    bad=audit(row)
    d=row.get('decision') or {};s=d.get('ana_shadow') or {}
    if s.get('protocol')!=PROTOCOL or s.get('params')!=PARAMS or s.get('simulation') is not True:
        bad.append('missing_or_changed_shadow_protocol')
    if not d.get('model_revision') or s.get('model_revision')!=d.get('model_revision') or s.get('model_version')!=d.get('model_version'):
        bad.append('missing_or_mismatched_fingerprint')
    ps=d.get('p3') or [];odds=(row.get('odds_pre') or {}).get('v') or []
    tickets=s.get('tickets',[]);tags=s.get('evidence_tags') or {};entry=d.get('entry') or []
    if not tickets:bad.append('no_shadow_tickets')
    if len(entry)!=6 or set(entry)!=set(range(1,7)):bad.append('invalid_entry')
    if len(ps)!=120 or not all(finite(x) and 0<=x<=1 for x in ps) or abs(sum(ps)-1)>.002:
        bad.append('invalid_fixed_probabilities')
    elif len(odds)==120 and all(finite(x) and x>0 for x in odds) and len(entry)==6:
        # 固定されたタグ・確率・オッズから券の完全一致を監査。結果を参照しない。
        eligible={f for f,v in tags.items() if f in map(str,entry[1:]) and v}
        expected=[]
        for c,p,o in zip(COMBOS,ps,odds):
            if c.split('-')[0] in eligible and p>=PARAMS['min_probability'] and o>=PARAMS['min_odds'] and p*o>=PARAMS['min_expected_return']:
                expected.append({'combo':c,'amount':100,'probability':p,'odds':o,'expected_return':round(p*o,6)})
        expected=sorted(expected,key=lambda x:(-x['expected_return'],x['combo']))[:PARAMS['max_tickets']]
        if tickets!=expected:bad.append('fixed_shadow_tickets_mismatch')
    return sorted(set(bad))


def review(rows):
    exclusions=Counter();paired=[];shadow=[];groups=defaultdict(list)
    for r in rows:
        bad=shadow_audit(r)
        if bad:exclusions.update(bad);continue
        paired.append(r)
        sr=deepcopy(r);sr['decision']['tickets']=deepcopy(r['decision']['ana_shadow']['tickets']);shadow.append(sr)
        labels={x for v in r['decision']['ana_shadow']['evidence_tags'].values() for x in v}
        for label in labels:groups[label].append(sr)
    sh=summarize(shadow);sh['strategy']=PROTOCOL
    return {'protocol':PROTOCOL,'params':PARAMS,'simulation':True,
            'baseline_all':summarize(rows),'baseline_on_same_races':summarize(paired),'shadow':sh,
            'excluded_reason_counts':dict(exclusions),
            'overlapping_evidence_groups':{k:summarize(v) for k,v in sorted(groups.items())},
            'limits':['学習確率×締切前オッズはモデル上の見込みであり利益を保証しない',
                      '根拠タグの複数該当は重複集計。独立した加点ではない',
                      '決済・返還未確認は除外。旧記録の券を後から生成しない',
                      '影の仮想購入であり実購入・購入推奨ではない']}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=Path('research/improvements/forward_ana.json'))
    args=ap.parse_args();report=review(source_races())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'baseline_settled':report['baseline_all']['races'],'shadow_settled':report['shadow']['races']}))


if __name__=='__main__':main()
