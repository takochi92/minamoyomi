from copy import deepcopy
from datetime import datetime, timezone

import pytest

from scraper.season_conditions import current_conditions, rank_points
from scraper.season_watch import JST, period


def sample(day='20261031'):
    now=datetime.strptime(day+' 12:00','%Y%m%d %H:%M').replace(tzinfo=JST)
    previous='20261030' if day=='20261031' else '20261026'
    player={'toban':'4001','name':'確認 選手','class':'A2','branch':'広島','n':100,'points':629,
            'top2':40,'top3':60,'accident_min':0,'unknown':0,'win':6.29,'last':previous,'f':[]}
    report={'as_of':day,'through':previous,'period':period(day),'players':[player],'missing_days':[]}
    index={'date':day,'updated_at':day[:4]+'-'+day[4:6]+'-'+day[6:]+'T11:59',
           'venues':[{'jcd':'03','name':'江戸川','races':[{'rno':i,'deadline':h} for i,h in [(1,'11:00'),(2,'15:00')]]}]}
    rows={}
    for stub in index['venues'][0]['races']:
        rows[stub['rno']]={'date':day,'jcd':'03','rno':stub['rno'],'deadline':stub['deadline'],'race_name':'予選',
                          'racelist':{'boats':[{'frame':f,'toban':str(4000+f)} for f in range(1,7)]}}
    rows[1]['result']={'finished':True,'order':[{'frame':i,'place':str(i)} for i in range(1,7)]}
    calendars=[{'year':2026,'category':c,'events':[]} for c in ('01','02','03')]
    return report,index,rows,now,calendars


def run(args):
    report,index,rows,now,calendars=args
    return current_conditions(report,index,lambda d,j,r:rows.get(r),now,calendars)


def test_live_result_is_added_once_and_last_day_remaining_is_observed_not_guessed():
    args=sample();original=deepcopy(args)
    result=run(args);p=result['players'][0]
    assert p['n']==101 and p['points']==639 and p['top2']==41 and p['top3']==61
    assert p['condition']['live_results_added']==1
    assert result['conditions_context']['last_day']
    assert p['condition']['programme_complete']
    assert len(p['condition']['races'])==1 and p['condition']['races'][0]['rno']==2
    assert run(args)==result and args==original


def test_days_left_do_not_create_unpublished_future_starts():
    result=run(sample('20261027'))
    assert not result['conditions_context']['last_day']
    assert len(result['players'][0]['condition']['races'])==1


@pytest.mark.parametrize('grade,final,expected',[('一般',False,10),('G1',False,11),('SG',True,13)])
def test_live_points_use_official_grade_and_final_rules(grade,final,expected):
    args=sample();args[2][1]['race_name']='優勝戦' if final else '予選'
    if grade!='一般':
        args[4][0]['events']=[{'jcd':'03','from':'20261001','through':'20261031','grade':grade}]
    assert run(args)['players'][0]['points']==629+expected


def test_missing_programme_and_pending_result_do_not_become_known_remaining_starts():
    args=sample();args[2].pop(1)
    p=run(args)['players'][0]
    assert not p['condition']['programme_complete'] and p['condition']['issues']
    args=sample();args[2][1].pop('result')
    p=run(args)['players'][0]
    assert p['points']==629 and p['condition']['issues']
    assert len(p['condition']['races'])==1


@pytest.mark.parametrize('place',['F','S0','1'])
def test_abnormal_or_tied_results_hold_conditions_without_inventing_points(place):
    args=sample();args[2][1]['result']['order'][1]['place']=place
    p=run(args)['players'][0]
    assert p['n']==100 and p['points']==629 and p['condition']['issues']


def test_stale_daily_archive_or_rollover_blocks_concrete_conditions():
    args=sample();args[0]['as_of']='20261030'
    assert run(args)['conditions_context']['issues']
    args=sample();args=list(args);args[3]=datetime(2026,11,1,0,1,tzinfo=JST)
    assert run(args)['conditions_context']['issues']


def test_saved_day_is_not_counted_again_and_duplicate_programme_is_not_accepted():
    args=sample();args[0]['through']='20261031'
    assert run(args)['players'][0]['n']==100
    args=sample();args[1]['venues'][0]['races'].append(args[1]['venues'][0]['races'][0])
    p=run(args)['players'][0]
    assert p['n']==101 and not p['condition']['programme_complete']


def test_grade_conflicts_and_special_finals_are_not_filled_with_general_points():
    assert rank_points(None,'予選') is None
    assert rank_points('一般','団体・優勝戦') is None
    assert rank_points('SG','優勝戦')==[13,11,9,8,6,5]
    assert rank_points('一般','準優勝戦')==[10,8,6,4,2,1]
    args=sample();args[4].pop()
    p=run(args)['players'][0]
    assert p['condition']['issues'] and p['condition']['races'][0]['points'] is None


def test_timezone_is_japan_and_input_report_stays_unchanged():
    args=list(sample());args[3]=datetime(2026,10,31,3,0,tzinfo=timezone.utc)
    assert run(args)['conditions_context']['today']=='20261031'
