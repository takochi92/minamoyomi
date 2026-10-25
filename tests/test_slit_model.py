from copy import deepcopy

import pytest

from scraper import slit_model as M


def sample(st, ex, lap=None, straight=None, sd=None, tilt=None):
    return [{'frame': i+1, 'course': i+1, 'name': f'選手{i+1}', 'st': st[i], 'exhibit': ex[i],
             'lap': lap[i] if lap else None, 'straight': straight[i] if straight else None,
             'sd': sd[i] if sd else None, 'tilt': tilt[i] if tilt else None} for i in range(6)]


def test_specification_sample_a():
    boats = sample([.17,.12,.15,.18,.18,.23], [6.82,6.77,6.76,6.73,6.78,6.82],
                   [36.72,36.88,36.68,37.43,37.10,37.34], [7.63,7.64,7.71,7.69,7.64,7.69], [.04,.04,.05,.04,.05,.06])
    d = M.calculate(boats, {'wind_speed':0,'wave_cm':1})
    assert [b['arrival'] for b in d['boats']] == pytest.approx([7.06,7.09,7.07,7.33,7.22,7.34], abs=.05)
    assert [b['gap'] for b in d['boats']] == pytest.approx([0,-.7,-.3,-6.1,-3.6,-6.2], abs=.3)
    assert d['overlap'] and not d['rough']
    for b in d['boats']:
        assert M.position(b,b['st']) == 0
        assert M.position(b,b['st']+b['t_acc']) == pytest.approx(60)
        assert M.position(b,b['arrival']) == pytest.approx(150)


def test_specification_sample_b_signed_exhibition_f():
    d = M.calculate(sample([.18,.36,.38,-.19,-.03,.16], [7.19,7.36,7.14,7.12,7.14,7.28], tilt=[0,0,-.5,0,0,0]))
    assert d['lead_time'] == pytest.approx(7.18,abs=.05)
    assert [b['gap'] for b in d['boats']] == pytest.approx([-10.7,-17.7,-12.1,0,-3.8,-10.6],abs=.3)
    assert d['uncertainty_missing'] and all(b['error_m'] is None for b in d['boats'])
    assert M.position(d['boats'][3],0) > 0


def test_rough_and_ties_and_partial_detail():
    b = sample([.15]*6,[6.8]*6,lap=[37]*6,straight=[7.6]*6,sd=[.04]*6)
    a = M.calculate(b, {'wind_speed':0,'wave_cm':1})
    rough = M.calculate(b, {'wind_speed':4,'wave_cm':1})
    assert rough['rough'] and all(x['gap']==0 for x in rough['boats'])
    assert rough['boats'][0]['error_m'] == pytest.approx(a['boats'][0]['error_m']*1.5)
    assert rough['boats'][0]['arrival'] == a['boats'][0]['arrival']
    b[2]['lap']=None;b[3]['straight']=None
    d=M.calculate(b)
    assert not d['lap_used'] and not d['straight_used'] and d['weather_incomplete']


def race():
    return {'date':'20261025','jcd':'22',
        'racelist':{'boats':[{'frame':f,'name':str(f),'toban':str(4000+f),'avg_st':.2} for f in range(1,7)]},
        'before':{'boats':[{'frame':f,'exhibit_time':6.8,'tilt':0} for f in range(1,7)],
                  'start_exhibition':[{'frame':f,'course':7-f,'st':-.19 if f==4 else .18} for f in range(1,7)]}}


def test_build_entry_fallback_and_no_result_leak(monkeypatch):
    monkeypatch.setattr(M,'references',lambda:({},{}))
    r=race()
    d=M.build(r)
    assert [b['frame'] for b in d['boats']]==[6,5,4,3,2,1]
    fourth=next(b for b in d['boats'] if b['frame']==4)
    assert fourth['st']==pytest.approx(.044)
    assert d['fukuoka']
    r['result']={'start':[{'st':.99}], 'winner':6}
    assert M.build(r)==d
    r['before']['boats'][0]['exhibit_time']=None
    assert M.build(r)['status']=='waiting'


def test_primary_st_not_blended_and_average_priority(monkeypatch):
    monkeypatch.setattr(M,'references',lambda:({},{}))
    r=race()
    r['start_timing']={'boats':{'4':{'course':3,'toban':'4004','st':.16,'sd':.05,'n':20}},
                      'averages':{'1':{'course':.1,'meeting':.3,'local':.4},'2':{'course':None,'meeting':.1,'local':.4}}}
    d=M.build(r)
    by={b['frame']:b for b in d['boats']}
    assert by[4]['st']==.16
    assert by[1]['st']==by[2]['st']==pytest.approx(.132)
    assert by[1]['st_source']=='course_average_blend'
    assert by[2]['st_source']=='meeting_average_blend'
    for b in r['racelist']['boats']:b['avg_st']=None
    r['start_timing']={}
    assert next(b for b in M.build(r)['boats'] if b['frame']==4)['st']==-.19


def test_duplicate_entry_and_half_lap_not_one_lap(monkeypatch):
    monkeypatch.setattr(M,'references',lambda:({},{}))
    r=race()
    r['oriten']={'items':['半周ラップ','まわり足'], 'rows':{str(f):[18,7.8] for f in range(1,7)}}
    assert not M.build(r)['lap_used']
    r['before']['start_exhibition'][1]['course']=6
    assert M.build(r)['status']=='waiting'
