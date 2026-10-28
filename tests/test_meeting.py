import copy
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from scraper import meeting as M, meeting_views as V, meeting_update as U, sitegen


def compact(day='20261027', rno=1, sts=None):
    sts = sts or [10,10,15,20,25,30]
    return [day,'23',rno,'逃げ',0,0,0,0,None,None,None,
            [[f,str(4000+f),f,sts[f-1],'',f,670+f,None,10+f,20+f] for f in range(1,7)]]


def test_periods_use_actual_meeting_and_cross_year():
    assert M.bounds('20260101','12/29-1/3 4日目') == ('20251229','20260103')
    assert M.bounds('20261028','10/27-10/31 2日目') == ('20261027','20261031')
    assert M.bounds('20261028','10/21-10/25 最終日') is None
    assert M.bounds('20261028','開催日不明') is None
    idx={'date':'20261028','venues':[{'jcd':'23','day':'10/27-10/31 2日目','title':'今回'}]}
    assert M.profile([],idx,'20261025','23') is None


def test_aggregation_deduplicates_and_does_not_mix_meetings_or_future():
    r=compact()
    saved={'date':'20261027','jcd':'23','rno':1,
           'racelist':{'boats':[{'frame':1,'toban':'4001'}]},
           'before':{'boats':[{'frame':1,'exhibit_time':6.80}]}}
    data=M.MeetingIndex([compact('20261024'),r,compact('20261029')],[saved])
    s=data.summary('23','4001','20261027','20261031','20261028')
    assert s['ex_n']==s['st_n']==s['rank_n']==1
    assert s['ex']==6.80 and s['st']==.10 and s['rank']==1
    assert len(s['results'])==1
    assert data.summary('23','4002','20261027','20261031','20261028')['rank']==1


def test_f_l_missing_and_invalid_st_do_not_create_false_ranks():
    r=compact();r[11][0][4]='F';r[11][1][4]='L'
    x=M.MeetingIndex([r])
    for t in ('4001','4002'):
        s=x.summary('23',t,'20261027','20261031','20261028')
        assert s['st_n']==s['rank_n']==0 and len(s['results'])==1
    assert x.summary('23','4003','20261027','20261031','20261028')['rank']==1
    r[11][0][4]='';r[11][0][3]=None
    assert M.MeetingIndex([r]).summary('23','4003','20261027','20261031','20261028')['rank_n']==0
    r[11][0][3]=float('nan')
    assert M.MeetingIndex([r]).summary('23','4003','20261027','20261031','20261028')['rank_n']==0


def test_changed_athlete_does_not_inherit_old_stats():
    saved={'date':'20261027','jcd':'23','rno':1,'racelist':{'boats':[{'frame':1,'toban':'4999'}]}}
    s=M.MeetingIndex([compact()],[saved]).summary('23','4999','20261027','20261031','20261028')
    assert not s['results'] and s['ex_n']==s['st_n']==s['rank_n']==0


def header(title='テスト杯', day='20261028'):
    return f'<h2>{title}</h2><a href="?hd={day}&jcd=23">当日</a>'


def cells(values): return '<tr>'+''.join(f'<td>{v}</td>' for v in values)+'</tr>'


def test_official_parsers_validate_meeting_date_and_unique_athletes():
    row=cells([1,'4001','選手','A1',11,'40.0',22,'30.0','6.75'])
    html=header()+'<table><thead><tr><th>前検タイム</th></tr></thead><tbody>'+row+'</tbody></table>'
    assert M.parse_precheck(html,'20261028','23','テスト杯')=={'4001':{'time':6.75,'motor_no':11}}
    assert M.parse_precheck(html,'20261029','23','テスト杯') is None
    assert M.parse_precheck(html,'20261028','23','別の杯') is None
    assert M.parse_precheck(html.replace(row,row+row),'20261028','23','テスト杯') is None
    row=cells([2,'4001','選手','A1','8.25','123','33','0'])
    html=header()+'<li>初日終了時点 ※注意</li><table><thead><tr><th>登録番号 得点率</th></tr></thead><tbody>'+row+'</tbody></table>'
    out=M.parse_points(html,'20261028','23','テスト杯')
    assert out['as_of']=='初日終了時点' and out['rows']['4001']=={'rank':2,'rate':8.25,'n':None}
    row=cells([3,'4001 / A1 選手','6.00',12,0,2])
    html='<h3>テスト杯</h3><div class="day">2026年10月28日 ２日目 第2R終了時点</div><table><thead><tr><th>登番 得点率</th></tr></thead><tbody>'+row+'</tbody></table>'
    assert M.parse_points(html,'20261028','23','テスト杯',karatsu=True)['rows']['4001']['n']==2
    assert M.parse_points(html,'20261029','23','テスト杯',karatsu=True) is None


def test_refresh_keeps_last_good_values_on_failure_and_never_changes_race(tmp_path):
    day='20261028';title='テスト杯'
    idx={'date':day,'venues':[{'jcd':'23','day':'10/27-10/31 2日目','title':title}]}
    folder=tmp_path/'meetings';folder.mkdir()
    path=folder/'20261027-23.json'
    initial={'start':'20261027','end':'20261031','jcd':'23','title':title,
             'precheck':{'rows':{'4001':{'time':6.75,'motor_no':11}}},
             'points':{day:{'as_of':'初日終了時点','rows':{'4001':{'rank':1,'rate':9.0}}}}}
    path.write_text(json.dumps(initial),encoding='utf-8')
    race={'date':day,'jcd':'23','rno':3,'deadline':'09:27','prediction':{'frozen':True},
          'before':{'boats':[{'frame':1,'exhibit_time':6.70}]},
          'racelist':{'boats':[{'frame':f,'toban':str(4000+f),'name':f'選手{f}'} for f in range(1,7)]}}
    rf=tmp_path/'races'/day/'2303.json';rf.parent.mkdir(parents=True)
    rf.write_text(json.dumps(race),encoding='utf-8');before=rf.read_bytes()
    class Fetch:
        exhausted=False
        def get(self,*a,**kw):raise RuntimeError('offline')
        def _slot(self):raise RuntimeError('offline')
        def oriten(self,*a):return '1\t1\n一周\n'+ '\n'.join(f'{f}\t選手{f}\t36.70' for f in range(1,7))
    U.refresh(tmp_path,idx,datetime(2026,10,28,9,40,tzinfo=U.JST),Fetch(),workers=1)
    out=json.loads(path.read_text(encoding='utf-8'))
    assert out['precheck']==initial['precheck'] and out['points']==initial['points']
    assert rf.read_bytes()==before
    assert out['late_exhibition']['20261028-3']['rows']['1']==[36.70]


def test_late_exhibition_is_display_only_and_new_tab_has_counts(tmp_path,monkeypatch):
    feed={'jcd':'23','start':'20261027','end':'20261031','title':'テスト杯',
          'late_exhibition':{'20261028-3':{'items':['一周'],'rows':{'1':[36.37]}}},
          'precheck':{'rows':{'4001':{'time':6.75,'motor_no':11}}},
          'points':{'20261028':{'as_of':'2日目第2R終了時点','rows':{'4001':{'rank':3,'rate':7.50,'n':2}}}}}
    s=sitegen.Site.__new__(sitegen.Site);s.idx={'date':'20261028'};s._meeting_feeds=[feed]
    s._meeting_index=M.MeetingIndex([compact()]);s.day_means=lambda *_:{}
    monkeypatch.setattr(sitegen,'DATA',tmp_path)
    race={'date':'20261028','jcd':'23','rno':3,'racelist':{'boats':[{'frame':1,'toban':'4001','name':'テスト選手','motor_no':11}]},
          'before':{'boats':[{'frame':1,'exhibit_time':6.70}]},'prediction':{'locked':True}}
    before=copy.deepcopy(race)
    html=s.oriten_block(race)
    assert '36.37' in html and '締切後に補完' in html and '詳細展示は未取得' not in html
    html=s.meeting_block('20261028','23',race,sitegen.Page('race/20261028/karatsu-3.html'))
    for text in ('6.75','6.71','.10','1回','1走','3位','7.50','1着','公式の得点率一覧'):
        assert text in html
    assert race==before
    a=copy.deepcopy(V.cache_inputs(s,tmp_path,'20261028'))
    feed['attempts']={'points':{'at':'changed'}};feed['updated_at']='changed'
    assert V.cache_inputs(s,tmp_path,'20261028')==a
    feed['points']['20261028']['rows']['4001']['rate']=8.5
    assert V.cache_inputs(s,tmp_path,'20261028')!=a


def test_backfilled_exhibition_merges_by_athlete_without_duplicate_results(tmp_path):
    s=SimpleNamespace(idx={'date':'20261028'},_meeting_feeds=[{
        'jcd':'23','start':'20261027','end':'20261031','title':'テスト杯',
        'exhibitions':{'20261027-1':{'date':'20261027','rno':1,
            'boats':[{'frame':1,'toban':'4001','exhibit_time':6.78}]}}}])
    x=V.index(s,tmp_path,lambda **_: [compact()])
    stats=x.summary('23','4001','20261027','20261031','20261028')
    assert stats['ex']==6.78 and stats['ex_n']==1
    assert stats['st_n']==1 and len(stats['results'])==1

