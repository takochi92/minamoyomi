import re
import pytest
from scraper import overperf, target_methods as tm


def entry(t,course,place):
    return [course,t,course,15,'',place,680,['B1',5.0]]


def race(day='20261024', method='差し', fixed=False, missing=False, boats=6):
    entries=[entry(str(4000+i),i+1,1 if i==1 else i+2) for i in range(boats)]
    if missing: entries[0][7]=None
    return [day,'01',1,method,None,0,0,fixed,None,None,None,entries]


def test_methods_use_the_same_eligible_races_and_handle_unknown_winners():
    races=[race(),race(method='まくり'),race(method='不明'),race(fixed=True),race(missing=True),race(boats=5)]
    methods,through,n=overperf.course_methods(overperf._rows(races))
    assert n==3 and through=='20261024'
    assert methods['4001']['2']==[3,3,0,1,1,0,0,0,1]
    assert methods['4000']['1']==[3,0,0,0,0,0,0,0,0]


def test_bar_denominator_is_all_matching_starts_not_only_wins():
    text=tm.render([32,11,0,8,3,0,0,0,0],32,11)
    widths=[float(x) for x in re.findall(r'width:([0-9.]+)%',text)]
    assert widths==[25,9.375,65.625]
    assert sum(widths)==100
    assert '対象32走を100％' in text and '1着以外21走' in text
    assert '差し <b>8回</b> <small>25.0%' in text
    assert '1着以外21回' in text


def test_unknown_win_is_separate_from_other_and_nonwinning():
    text=tm.render([10,3,0,1,0,0,1,0,1],10,3)
    assert 'tm-unknown' in text and '決まり手未確認 <b>1回' in text
    assert 'その他 <b>1回' in text and '1着以外7走' in text
    assert abs(sum(float(x) for x in re.findall(r'width:([0-9.]+)%',text))-100)<1e-5


@pytest.mark.parametrize('record,n,w',[(None,32,11),([32,11,0,8,3,0,0,0,0],31,11),
    ([32,11,0,8,3,0,0,0,0],32,10),([32,11,0,9,3,0,0,0,0],32,11),
    ([32,11,0,-1,12,0,0,0,0],32,11),([0,0,0,0,0,0,0,0,0],0,0)])
def test_missing_or_incompatible_counts_are_not_drawn_as_valid(record,n,w):
    text=tm.render(record,n,w)
    assert 'tm-track' not in text and ('再確認' in text or '確認中' in text)


def test_no_wins_still_shows_a_complete_nonwinning_bar():
    text=tm.render([10,0,0,0,0,0,0,0,0],10,0)
    assert 'width:100.000000%' in text and '1着以外10走' in text
