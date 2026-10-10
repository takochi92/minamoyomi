"""締切前の研究材料。本番モデルへ渡す本人参照と、展示の事実メモ。"""
from datetime import datetime,timedelta,timezone
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path
from .exhibition_profile import baseline,term_info

EX_PATH=Path(__file__).parent/'exstats.json.gz'
JST=timezone(timedelta(hours=9))


@lru_cache(maxsize=2)
def _load(stamp):
    with gzip.open(EX_PATH,'rt',encoding='utf-8') as f:return json.load(f).get('term_profiles',{'terms':{}})


def references(day,tobans):
    if not EX_PATH.exists():return {}
    data=_load(EX_PATH.stat().st_mtime_ns)
    return {t:baseline(data,day,t) for t in tobans}


def ranks(values):
    if set(values)!=set(range(1,7)) or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in values.values()):return {}
    return {f:1+sum(v<values[f]-1e-9 for v in values.values()) for f in values}


def evidence(boats, before, refs, motors, day):
    """予想作成時の参照値を保存。後日の表示で機歴や本人参照を再計算しない。"""
    times={b['frame']:b.get('exhibit_time') for b in (before or {}).get('boats',[])}
    complete=bool(ranks(times))
    mean=sum(round(v*100) for v in times.values())/600 if complete else None
    out={}
    for b in boats:
        f=b['frame'];ref=refs.get(b.get('toban'),{});n=ref.get('n',0)
        ready=complete and n>=100
        m=motors.get(str(b.get('motor_no')), {})
        out[str(f)]={'reference_n':n,'reference_terms':ref.get('terms',[]),
                     'reference_top1_rate':ref.get('top1',0)/n if n else None,
                     'personal_ready':ready,
                     'personal_change_seconds':round(round(times[f]*100)/100-mean-ref['dev_sum']/n,4) if ready else None,
                     'motor_no':b.get('motor_no'),'motor_ready':bool(m),
                     'motor_ex_seconds':m.get('ex_adj') if m else None,
                     'motor_reference_n':m.get('ex_reference_n',0),
                     'motor_as_of':m.get('as_of'),
                     'renewal_source':m.get('renewal_source')}
    return out


def signals(boats,before,oriten,refs,course_of):
    times={b['frame']:b.get('exhibit_time') for b in before.get('boats',[])}
    rr={'展示':ranks(times)};ori=oriten or {}
    for item in ('直線','一周','まわり足'):
        if item in ori.get('items',[]):
            idx=ori['items'].index(item)
            rr[item]=ranks({int(f):v[idx] for f,v in ori.get('rows',{}).items() if len(v)>idx})
        else:rr[item]={}
    result=[]
    for b in boats:
        f=b['frame'];a=refs.get(b.get('toban'),{})
        labels=[]
        if rr['展示'] and a.get('n',0)>=100 and a['top1']/a['n']<=.1 and rr['展示'].get(f)==1 and sum(r==1 for r in rr['展示'].values())==1:
            labels.append(f"本人比：普段の展示1位率{a['top1']/a['n']:.0%}（過去{a['n']}走）→今回は単独1位")
        for pair in (('展示','直線'),('展示','一周'),('一周','まわり足'),('直線','まわり足')):
            if all(rr[k].get(f,99)<=2 for k in pair):labels.append('＋'.join(pair)+'がともに上位2位')
        if labels:result.append({'frame':f,'course':course_of[f],'facts':labels,'source':'pre_race_inputs','foot_type':None})
    return result
