import copy
from tools.player_research import analyze, eligible, interval, motor_changes


def race(day='20240901', kim='逃げ', winner=1, order=None, zero=False, motor=10):
    order = order or [winner]+[c for c in range(1,7) if c != winner]
    es=[]
    for c in range(1,7):
        es.append([c,str(4000+c),c,15,'',order.index(c)+1,670+c,
                   ['A1' if c==3 else 'B1',5.5,30,5,30,0 if zero else 30,30],motor+c])
    return [day,'01',1,kim,'北',2,0,0,'-'.join(map(str,order[:3])),1000,5,es]


def test_actual_course_and_accident_denominators():
    r=race(kim='まくり',winner=3,order=[3,4,5,1,2,6])
    r[11][0][0],r[11][2][0]=3,1  # 枠番と進入を入れ替え
    r[11][-1][5]='F'
    assert eligible(r)
    p,_=analyze([r,race('20261001')],'20251001')
    a=p['train']['attack'][('4003',3,'まくり')]
    assert a['n']==1 and a['pair_4-5']==1 and a['in_out']==1
    assert p['train']['course'][('4006',6)][0]==1
    assert sum(p['train']['course'][('4006',6)][1:4])==0
    r[11][-1][2]=None
    assert not eligible(r)


def test_train_selection_and_baseline_do_not_use_future():
    train=[]
    for i in range(240):
        r=race(winner=3 if i<120 else 1,kim='まくり' if i<120 else '逃げ');r[2]=i
        if i>=120:r[11][2][1]='9999'
        train.append(r)
    test=race('20261001',winner=3,kim='まくり')
    p,e=analyze(train+[test],'20251001')
    assert p['candidates']
    changed=copy.deepcopy(test);changed[11][2][5]=6;changed[11][-1][5]=1
    q,f=analyze(train+[changed]*20,'20251001')
    assert p['candidates']==q['candidates']
    assert e(test,test[11][2])==f(test,test[11][2])


def test_motor_never_compares_across_renewal():
    rows=[]
    for day,zero in [('20250901',True),('20250905',False),('20260901',True),('20260905',False)]:
        for i in range(5):
            r=race(day,zero=zero);r[2]=i+1;rows.append(r)
    _,expected=analyze(rows,'20251001')
    out=motor_changes(rows,expected)
    assert out['recent_changes']
    assert all(x['renewal']=='20260901' and x['previous']['from']=='20260901' for x in out['recent_changes'])


def test_wilson_boundary_and_escape_totals():
    assert interval(0,100)[0]==0
    assert interval(100,100)[1]==1
    p,_=analyze([race(),race('20261001')],'20251001')
    a=p['test']['escape']['ALL']
    assert sum(v for k,v in a.items() if k.startswith('second_'))==a['n']
    assert sum(v for k,v in a.items() if k.startswith('third_'))==a['n']
