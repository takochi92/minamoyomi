"""展示の期別傾向。意図・機力を認定せず、本人の通常値との違いを数値化する。"""
from datetime import datetime, timedelta
import math


def term_info(day):
    """級別適用期の名称と審査対象期間を別々に保存する。"""
    dt=datetime.strptime(day,'%Y%m%d');y,m=dt.year,dt.month
    if 5<=m<=10:
        return {'key':f'{y+1}前期','from':f'{y}0501','to':f'{y}1031',
                'applies_from':f'{y+1}0101','applies_to':f'{y+1}0630'}
    end=y+1 if m>=11 else y
    return {'key':f'{end}後期','from':f'{end-1}1101','to':f'{end}0430',
            'applies_from':f'{end}0701','applies_to':f'{end}1231'}


def previous_terms(day):
    info=term_info(day);out=[]
    for _ in range(2):
        before=(datetime.strptime(info['from'],'%Y%m%d')-timedelta(days=1)).strftime('%Y%m%d')
        info=term_info(before);out.append(info['key'])
    return out


def observations(r):
    es=r[11]
    if len(es)!=6 or {e[0] for e in es}!=set(range(1,7)):
        return []
    vals=[e[6] if len(e)>6 else None for e in es]
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in vals):
        return []
    best=min(vals);ties=sum(v==best for v in vals);avg=sum(vals)/6
    return [{'toban':e[1],'frame':e[0],'course':e[2],
             'top1':v==best,'solo1':v==best and ties==1,
             'rank':1+sum(x<v for x in vals),'dev':(v-avg)/100,
             'win':e[5]==1,'top3':e[5] in (1,2,3)} for e,v in zip(es,vals)]


def empty():
    return {'n':0,'top1':0,'solo1':0,'rank_sum':0,'dev_sum':0.0,'dev_sq':0.0,'wins':0,'top3':0}


def add(a,o):
    a['n']+=1
    for k in ('top1','solo1'):a[k]+=int(o[k])
    a['rank_sum']+=o['rank'];a['dev_sum']+=o['dev'];a['dev_sq']+=o['dev']**2
    a['wins']+=int(o['win']);a['top3']+=int(o['top3'])


def profiles(records):
    terms={};used=0
    for r in records:
        obs=observations(r)
        if not obs:continue
        info=term_info(r[0]);k=info['key']
        term=terms.setdefault(k,{**info,'available_from':r[0],'available_to':r[0],'races':0,'players':{}})
        term['available_from']=min(term['available_from'],r[0]);term['available_to']=max(term['available_to'],r[0])
        term['races']+=1;used+=1
        for o in obs:add(term['players'].setdefault(o['toban'],empty()),o)
    return {'schema':1,'source':'保存済み公式競走成績の展示タイム','eligible_races':used,
            'tie_policy':'同タイム1位は全員top1、solo1は単独1位のみ','terms':terms}


def baseline(data, day, toban):
    """当該期は使わず、直前2期だけ。完成後の当該期成績による未来混入を防ぐ。"""
    total=empty();used=[]
    for key in previous_terms(day):
        term=data['terms'].get(key)
        if term and term['to']<day:
            a=term['players'].get(toban)
            if a:
                for k in total:total[k]+=a[k]
                used.append(key)
    return {**total,'terms':used}


def surprise(o, past, minimum=100, rare_rate=.10, improvement=.03):
    """固定条件。現在の着順は使用しない。"""
    n=past['n']
    ready=n>=minimum
    rare=ready and past['top1']/n<=rare_rate
    change=o['dev']-past['dev_sum']/n if n else None
    return {'reference_n':n,'reference_top1_rate':past['top1']/n if n else None,
            'rank_improvement':past['rank_sum']/n-o['rank'] if n else None,
            'dev_change_seconds':change,'rare_baseline':rare,
            'rare_solo1':rare and o['solo1'],
            'rare_solo1_improved':rare and o['solo1'] and change<=-improvement+1e-9}
