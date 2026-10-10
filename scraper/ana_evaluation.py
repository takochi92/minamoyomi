"""根拠付きの外艇をオッズで絞る前向き仮想購入。未検証・本番券は変更しない。"""
import itertools
import math

PROTOCOL='evidence_value_outer_v1'
COMBOS=['-'.join(map(str,c)) for c in itertools.permutations(range(1,7),3)]
PARAMS={'min_probability':.01,'min_odds':20.,'min_expected_return':1.10,'max_tickets':4,'amount':100}


def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)


def classify(race):
    """予想時の保存済み根拠だけを使う。結果・新しい機歴は読まない。"""
    p=race.get('prediction') or {};tags={}
    facts={s['frame']:s.get('facts',[]) for s in p.get('research_signals',[])}
    for b in p.get('boats',[]):
        if b.get('course',1)<2:continue
        f=b['frame'];labels=[];parts=b.get('parts') or {}
        if parts.get('乗り手補正の機力展示',0)>0:labels.append('motor_model_support')
        if any(x.startswith('本人比：') for x in facts.get(f,[])):labels.append('rare_solo_first')
        if any('ともに上位2位' in x for x in facts.get(f,[])):labels.append('paired_exhibition')
        if parts.get('選手のコース別成績',0)>0:labels.append('course_model_support')
        if labels:tags[str(f)]=labels
    return tags


def shadow_decision(race):
    p=race.get('prediction') or {};tags=classify(race)
    ps=p.get('p3') or [];odds=(race.get('odds_pre') or {}).get('v') or []
    out={'protocol':PROTOCOL,'simulation':True,'params':dict(PARAMS),'evidence_tags':tags,
         'model_version':p.get('version'),'model_revision':p.get('model_revision'),'tickets':[]}
    if p.get('stage')!='直前' or not p.get('model_revision') or len(ps)!=120 or len(odds)!=120:return out
    if not all(finite(x) and 0<=x<=1 for x in ps) or abs(sum(ps)-1)>.002:return out
    if not all(finite(x) and x>0 for x in odds):return out
    ranked=[]
    for c,prob,o in zip(COMBOS,ps,odds):
        if c.split('-')[0] not in tags:continue
        ev=prob*o
        if prob>=PARAMS['min_probability'] and o>=PARAMS['min_odds'] and ev>=PARAMS['min_expected_return']:
            ranked.append({'combo':c,'amount':100,'probability':prob,'odds':o,'expected_return':round(ev,6)})
    out['tickets']=sorted(ranked,key=lambda x:(-x['expected_return'],x['combo']))[:PARAMS['max_tickets']]
    return out
