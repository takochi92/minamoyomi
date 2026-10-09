"""締切前に固定した既存AIの仮想購入を、結果・返還で検証する。"""
from datetime import datetime
import itertools
import math
from scraper.research_snapshot import JST

COMBOS = ['-'.join(map(str,c)) for c in itertools.permutations(range(1,7),3)]


def audit(row, max_odds_age_seconds=300):
    reasons=[]
    try:
        at=datetime.fromisoformat(row['captured_at'])
        dl=datetime.fromisoformat(row['deadline_at'])
        expected_dl=datetime.strptime(row['date']+' '+row['deadline'], '%Y%m%d %H:%M').replace(tzinfo=JST)
        if dl!=expected_dl:reasons.append('deadline_mismatch')
        if at.tzinfo is None or dl.tzinfo is None or at>=dl:
            reasons.append('invalid_capture_time')
        if at.astimezone(JST).strftime('%Y%m%d')!=row['date'] or dl.astimezone(JST).strftime('%Y%m%d')!=row['date']:
            reasons.append('race_date_mismatch')
        stamps={}
        for field in ('racelist','before','prediction','odds_pre'):
            stamp=datetime.fromisoformat(row.get('fetched_at',{})[field])
            if stamp.tzinfo is None or not stamp<=at<dl:
                reasons.append('invalid_component_time:'+field)
            stamps[field]=stamp
        if (at-stamps['odds_pre']).total_seconds()>max_odds_age_seconds:
            reasons.append('stale_odds')
        if stamps['prediction']<stamps['before']:
            reasons.append('prediction_older_than_exhibition')
    except (TypeError,ValueError,KeyError):
        reasons.append('missing_or_invalid_timestamps')
    if row.get('provenance')!='timestamped_pre_deadline':reasons.append('unverified_inputs')
    d=row.get('decision') or {}
    if d.get('strategy')!='existing_ai_main_sub_100_v1' or not d.get('simulation'):
        reasons.append('missing_fixed_decision')
    if d.get('model_version') is None or d.get('stage')!='直前':
        reasons.append('missing_exhibition_model_decision')
    tickets=d.get('tickets',[])
    if not tickets:reasons.append('no_tickets')
    seen=set()
    for t in tickets:
        c=t.get('combo');a=t.get('amount')
        if c not in COMBOS or c in seen or a!=100:reasons.append('invalid_tickets')
        seen.add(c)
    odds=(row.get('odds_pre') or {}).get('v',[])
    if len(odds)!=120 or any(not isinstance(x,(float,int)) or isinstance(x,bool) or not math.isfinite(x) or x<=0 for x in odds):
        reasons.append('incomplete_odds')
    return sorted(set(reasons))


def settle(tickets,result):
    """公式返還艇を含む券のみ返還。結果未確認・不成立扱い不明は未決済。"""
    if not result.get('finished') or 'refunded' not in result:
        return {'status':'unsettled'}
    try:
        refunds={int(x) for x in result['refunded']}
    except (ValueError,TypeError):return {'status':'unsettled'}
    if not refunds<=set(range(1,7)):return {'status':'unsettled'}
    invested=sum(t['amount'] for t in tickets)
    returned=sum(t['amount'] for t in tickets if set(map(int,t['combo'].split('-')))&refunds)
    winner=result.get('trifecta');payout=result.get('trifecta_payout')
    if winner not in COMBOS or not isinstance(payout,(int,float)) or not math.isfinite(payout) or payout<=0:
        # 全券が公式返還艇を含む場合だけ、払戻不明でも返還を確定できる。
        return {'status':'settled','invested':invested,'refund':returned,'payout':0,'hit':False} if returned==invested else {'status':'unsettled'}
    if set(map(int,winner.split('-')))&refunds:return {'status':'unsettled'}
    paid=sum(payout*t['amount']/100 for t in tickets if t['combo']==winner)
    return {'status':'settled','invested':invested,'refund':returned,'payout':paid,'hit':paid>0}


def summarize(rows):
    from collections import Counter
    reasons=Counter();details=[];total={'races':0,'hits':0,'invested':0,'refund':0,'payout':0}
    cohorts={}
    for row in rows:
        bad=audit(row)
        if bad:
            reasons.update(bad);continue
        s=settle(row['decision']['tickets'],row.get('result') or {})
        if s['status']!='settled':reasons['unsettled_result']+=1;continue
        for k in ('invested','refund','payout'):total[k]+=s[k]
        total['races']+=1;total['hits']+=s['hit']
        version=row['decision'].get('model_revision') or row['decision'].get('model_version')
        details.append({'date':row['date'],'jcd':row['jcd'],'rno':row['rno'],'model_version':version,**s})
        key=(str(version),row['date'][:6])
        a=cohorts.setdefault(key,{'races':0,'hits':0,'invested':0,'refund':0,'payout':0})
        for k in ('invested','refund','payout'):a[k]+=s[k]
        a['races']+=1;a['hits']+=s['hit']
    gross=total['invested'];net=gross-total['refund']
    return {'strategy':'existing_ai_main_sub_100_v1','simulation':True,**total,
            'gross_roi':(total['payout']+total['refund'])/gross if gross else None,
            'net_roi':total['payout']/net if net else None,
            'excluded_reason_counts':dict(reasons),'settled_details':details,
            'by_model_and_month':[{'model_version':v,'month':m,**a,
                                  'gross_roi':(a['payout']+a['refund'])/a['invested'] if a['invested'] else None,
                                  'net_roi':a['payout']/(a['invested']-a['refund']) if a['invested']>a['refund'] else None}
                                 for (v,m),a in sorted(cohorts.items())]}
