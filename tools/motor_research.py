"""日付順の機力探索。開催名で節境界を補強し、未知の更新日を明示。"""
from collections import defaultdict, Counter
from datetime import datetime, timedelta
import math
from scraper.exhibition_profile import observations
from scraper.motoradj import renewed_venues
from tools.player_research import eligible, strength_key


def analyze(records, race_files):
    titles=defaultdict(set)
    for r in race_files:
        title=(r.get('racelist') or {}).get('title')
        if title:titles[(r['date'],r['jcd'])].add(title)
    day_rows=defaultdict(list)
    for r in records:day_rows[r[0]].append(r)
    epochs={};last_zero={};last_day={};session={};session_titles={}
    rider=defaultdict(lambda:[0,0.,0.]);base=defaultdict(lambda:[0,0]);prior=defaultdict(lambda:[0,0])
    motors=defaultdict(list);audit=Counter();boundaries=[]
    for day,rs in sorted(day_rows.items()):
        ordinal=datetime.strptime(day,'%Y%m%d').toordinal()
        for j in sorted(renewed_venues(rs)):
            if ordinal-last_zero.get(j,-99)>3:
                epochs[j]=day
                audit['inferred_renewal_events']+=1
            last_zero[j]=ordinal
        for j in sorted({r[1] for r in rs}):
            names=titles.get((day,j),set());title=next(iter(names)) if len(names)==1 else None
            changed=bool(title and session_titles.get(j) and title!=session_titles[j])
            gap=ordinal-last_day.get(j,-99)>2
            if gap or changed:
                session[j]=day
                session_titles[j]=title
                boundaries.append({'venue':j,'date':day,'reason':'saved_official_title_change' if changed else 'calendar_gap_inferred',
                                   'title':title,'official_calendar_verified':False})
            elif title and not session_titles.get(j):session_titles[j]=title
            last_day[j]=ordinal
        pending=[]
        for r in rs:
            obs=observations(r)
            if not eligible(r) or not obs:
                audit['invalid_outcome_or_exhibition_races']+=1;continue
            by={o['toban']:o for o in obs}
            for e in r[11]:
                o=by[e[1]];k=(r[1],e[1]);rn,rd,rq=rider[k];dev=o['dev']
                b=base[strength_key(r,e)];p=prior[e[2]]
                expected=(b[1]+50*(p[1]/p[0] if p[0] else 1/3))/(b[0]+50)
                adj=dev-rd/(rn+20)
                pending.append((k,dev,strength_key(r,e),e[2],int(e[5] in (1,2))))
                mno=e[8] if len(e)>8 else None
                if mno is None:audit['missing_motor_entries']+=1;continue
                if r[1] not in epochs:audit['unknown_renewal_entries']+=1;continue
                key=(r[1],mno,epochs[r[1]])
                ms=motors[key]
                if not ms or ms[-1]['session_key']!=session[r[1]]:
                    ms.append({'session_key':session[r[1]],'from':day,'to':day,'title':session_titles.get(r[1]),
                               'n':0,'raw_sum':0.,'adj_sum':0.,'adj_sq':0.,'reference_ready_n':0,
                               'top2':0,'expected_top2':0.,'users':Counter(),'oriten':{}})
                m=ms[-1];m['to']=day;m['n']+=1;m['raw_sum']+=dev;m['adj_sum']+=adj;m['adj_sq']+=adj*adj
                m['reference_ready_n']+=rn>=20;m['top2']+=e[5] in (1,2);m['expected_top2']+=expected;m['users'][e[1]]+=1
                audit['usable_motor_entries']+=1
        # 当日の展示・結果を当日の参照に戻さない。
        for k,dev,b,c,top2 in pending:
            rider[k][0]+=1;rider[k][1]+=dev;rider[k][2]+=dev*dev
            base[b][0]+=1;base[b][1]+=top2;prior[c][0]+=1;prior[c][1]+=top2
    # オリジナル展示は6艇が同じ項目で揃う場合だけ。各期の号機へ接続する。
    from tools.exhibition_research import features,valid_time
    motor_index=defaultdict(list)
    for (j,no,epoch),ms in motors.items():
        for m in ms:motor_index[(j,no)].append((epoch,m))
    for r in race_files:
        f=features(r)
        if not f:continue
        ori=r.get('oriten') or {};items=ori.get('items',[]);rows=ori.get('rows',{})
        for item in ('直線','一周','まわり足'):
            if item not in items:continue
            idx=items.index(item)
            vals={int(fr):v[idx] for fr,v in rows.items() if len(v)>idx}
            if set(vals)!=set(range(1,7)) or not all(valid_time(x) for x in vals.values()):continue
            mean=sum(vals.values())/6
            for fr,b in f['boats'].items():
                mno=b.get('motor_no')
                found=[m for epoch,m in motor_index.get((r['jcd'],mno),[]) if epoch<=r['date'] and m['from']<=r['date']<=m['to']]
                if len(found)!=1:continue
                a=found[0]['oriten'].setdefault(item,{'n':0,'sum':0.,'timestamped_n':0})
                a['n']+=1;a['sum']+=vals[fr]-mean;a['timestamped_n']+=r.get('provenance')=='timestamped_pre_deadline'
    def pack(m):
        n=m['n'];v=max(0,(m['adj_sq']-m['adj_sum']**2/n)/(n-1)) if n>1 else None
        span=(datetime.strptime(m['to'],'%Y%m%d')-datetime.strptime(m['from'],'%Y%m%d')).days+1
        return {**{k:m[k] for k in ('session_key','from','to','title','n','reference_ready_n','top2')},
                'observed_span_days':span,'session_boundary_status':'uncertain_long_span' if span>10 else 'inferred_not_calendar_verified',
                'users':dict(m['users']),'raw_ex_dev_seconds':m['raw_sum']/n,
                'rider_adjusted_ex_dev_seconds':m['adj_sum']/n,
                'ex_mean_se':math.sqrt(v/n) if v is not None else None,
                'expected_top2_prior_days':m['expected_top2']/n,
                'top2_above_baseline_shrunk':(m['top2']-m['expected_top2'])/(n+20),
                'oriten':{k:{'n':a['n'],'mean_deviation_seconds':a['sum']/a['n'],'timestamped_n':a['timestamped_n']} for k,a in m['oriten'].items()}}
    recent=[];cutoff=(datetime.strptime(records[-1][0],'%Y%m%d')-timedelta(days=14)).strftime('%Y%m%d')
    for (j,mno,epoch),ms in motors.items():
        if len(ms)<2 or ms[-1]['to']<cutoff or min(ms[-1]['n'],ms[-2]['n'])<5:continue
        p,c=map(pack,ms[-2:]);delta=c['rider_adjusted_ex_dev_seconds']-p['rider_adjusted_ex_dev_seconds']
        recent.append({'venue':j,'motor':mno,'renewal':epoch,'renewal_source':'zero_rate_inferred',
                       'official_renewal_verified':False,'previous':p,'latest':c,'delta_seconds':delta,
                       'comparison_usable':p['observed_span_days']<=10 and c['observed_span_days']<=10,
                       'display_status':'research_only','foot_type':'unclassified'})
    return {'audit':dict(audit),'method':'prior_days_only;venue_calendar_gap_or_saved_title_boundary',
            'boundaries':boundaries,'recent_changes':sorted(recent,key=lambda r:r['delta_seconds']),
            'limits':['正式なモーター更新日・開催日程との照合は未完了','標準誤差は走間の相関を無視した参考値','直線・周回の差は乗り手未補正で伸び型・出足型を断定しない']}
