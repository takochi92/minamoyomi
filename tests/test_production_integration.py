from copy import deepcopy
import json
import numpy as np
from scraper import model,predict as P,parse
from scraper.motoradj import OnlineMotorAdj,current_context
from scraper.prediction_context import signals
from tests.test_player_research import race


def boats():
    return [{'frame':f,'toban':str(4000+f),'course':f,'ex':660 if f==3 else 680+f,'cls':'B1','nat':5.,'loc':5.,'motor':30.,'boat':30.,
             'ex_reference':{'n':100,'top1':0,'dev_sum':0.},'motor_ex':.2} for f in range(1,7)]


def test_personal_features_have_no_duplicate_point03_signal_and_ties_neutral():
    bs=boats();s=model.Stats();x=model.features(s,'01',0,0,bs);idx=model.FEATS.index
    assert x[2,idx('ex_rare_first')]==1 and x[2,idx('ex_personal')]>0
    assert x[2,idx('motor_ex')]==.2
    assert not any('.03' in f for f in model.FEATS)
    bs[1]['ex']=660
    assert not model.features(s,'01',0,0,bs)[:,idx('ex_rare_first')].any()
    for b in bs:b['ex_reference']['n']=99
    assert not model.features(s,'01',0,0,bs)[:,idx('ex_personal')].any()


def test_online_motor_updates_only_after_day_and_requires_rider_support():
    old=[]
    for i in range(30):
        r=race('20240101');r[2]=i+1
        for e in r[11]:e[8]=None
        old.append(r)
    today=[]
    for i in range(5):
        r=race('20260901',zero=True);r[2]=i+1;today.append(r)
    ma=OnlineMotorAdj();ma.finish_day(old);ma.start_day(today,739860)
    assert ma.value('01',11)==0 and ma.ex_value('01',11)==0
    ma.finish_day(today)
    assert ma.ex_value('01',11)>0
    assert current_context(today)['01']['11']['ex_adj']==0 # 基準のある乗り手が不足
    context=current_context(old+today)['01']['11']
    assert context['adj_method']=='prior_days_v2' and context['ex_rider_ready_n']==5


def test_prediction_probabilities_use_learned_personal_feature_and_explicit_date(monkeypatch):
    import fixtures as fx
    from scraper import prediction_context
    rl=parse.parse_racelist(fx.racelist_html());bi=parse.parse_beforeinfo(fx.beforeinfo_html())
    for b in bi['boats']:b['exhibit_time']=6.6 if b['frame']==3 else 6.8+.01*b['frame']
    ref={b['toban']:{'n':100,'top1':0,'dev_sum':0.} for b in rl['boats']}
    dates=[]
    def refs(day,ids):dates.append(day);return ref
    monkeypatch.setattr(prediction_context,'references',refs)
    monkeypatch.setattr(P,'load_stats',lambda:model.Stats())
    def fitted(weight):return {'coef':{s:{'base_w':1.,'ex_rare_first':weight} for s in ('1','2','3')},'races':100000,'trained_on':['20240101','20260101']}
    monkeypatch.setattr(P,'load_model',lambda:fitted(0))
    before=P.predict('01',rl,bi,race_date='20260901')
    monkeypatch.setattr(P,'load_model',lambda:fitted(1))
    after=P.predict('01',rl,bi,race_date='20260901')
    assert after['boats'][2]['p_win']>before['boats'][2]['p_win']
    assert all(d=='20260901' for d in dates)
    assert abs(sum(after['p3'])-1)<.0001
    assert after['version']==31 and after['research_signals']
    json.dumps(after,ensure_ascii=False)


def test_exhibition_facts_need_six_valid_values_and_ignore_results():
    bs=[{'frame':f,'toban':str(f)} for f in range(1,7)]
    bi={'boats':[{'frame':f,'exhibit_time':6.6+.02*f} for f in range(1,7)]}
    ori={'items':['一周','まわり足'],'rows':{str(f):[36+.1*f,4+.02*f] for f in range(1,7)}}
    result=signals(bs,bi,ori,{},dict(zip(range(1,7),range(1,7))))
    assert any('一周＋まわり足' in fact for r in result for fact in r['facts'])
    bi['result']={'trifecta':'6-5-4'}
    assert signals(bs,bi,ori,{},dict(zip(range(1,7),range(1,7))))==result
    ori['rows'].pop('6')
    assert not any('一周＋まわり足' in fact for r in signals(bs,bi,ori,{},dict(zip(range(1,7),range(1,7)))) for fact in r['facts'])


def test_future_motor_context_is_neutral_in_live_prediction(monkeypatch):
    import fixtures as fx
    from scraper import prediction_context,motor
    rl=parse.parse_racelist(fx.racelist_html())
    monkeypatch.setattr(P,'load_stats',lambda:model.Stats())
    monkeypatch.setattr(prediction_context,'references',lambda day,ids:{})
    monkeypatch.setattr(P,'load_model',lambda:{'coef':{s:{'base_w':1.,'motor_ex':1.} for s in ('1','2','3')},'races':100000})
    record={'adj_method':'prior_days_v2','as_of':'20270101','ex_adj':1.,'adj':0}
    monkeypatch.setattr(motor,'load',lambda:{'01':{str(rl['boats'][2]['motor_no']):record}})
    future=P.predict('01',rl,race_date='20260901')
    assert abs(future['boats'][2]['p_win']-1/6)<.0001
    record['as_of']='20260831'
    prior=P.predict('01',rl,race_date='20260901')
    assert prior['boats'][2]['p_win']>future['boats'][2]['p_win']


def test_training_features_do_not_change_when_future_results_change(monkeypatch):
    from scraper import train_model as train
    monkeypatch.setattr(train,'WARMUP',0)
    rows=[]
    for day in ('20240101','20260901','20260902'):
        for i in range(5):
            r=race(day,zero=day=='20260901');r[2]=i+1;rows.append(r)
    x,_,d,*_=train.build_dataset(deepcopy(rows))
    changed=deepcopy(rows)
    for r in changed:
        if r[0]=='20260902':
            r[11][0][5],r[11][5][5]=6,1;r[11][2][6]=620
    other,_,dates,*_=train.build_dataset(changed)
    assert np.allclose(x[d<20260902],other[dates<20260902])
