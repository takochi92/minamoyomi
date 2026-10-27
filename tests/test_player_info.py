from copy import deepcopy
import json
import re
import pytest
from scraper.player_info import build_f_report, programme_snapshots, f_page, prize_page
from scraper.prize_rankings import parse_omura
from scraper.season_watch import period
from scraper.sitegen import Page


def test_new_information_pages_follow_public_revision_without_a_refresh_button(tmp_path,monkeypatch):
    from datetime import datetime
    from scraper import database_sources, fl_leave, season_watch
    from scraper.sitegen import Site
    monkeypatch.setattr(database_sources,'BASE',tmp_path)
    monkeypatch.setattr(fl_leave,'published_records',lambda _: {'records':[]})
    monkeypatch.setattr(season_watch,'calendars',lambda:[])
    s=Site.__new__(Site);s.now=datetime(2026,10,27);s.idx={'updated_at':'2026-10-27T20:00'}
    s.files={};s.racers={};s.day_races={};s.player_info_pages()
    for html in s.files.values():
        assert 'data-revision="2026-10-27T20:00"' in html and 'freshness.js' in html
        block=html.split('id="page-freshness"',1)[1].split('</div>',1)[0]
        assert '<button' not in block


def ranking_html(n=20):
    return '<p>期間：2026年 1月 1日～2026年10月26日</p>'+''.join(
        f'<a href="https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban={4000+i}"><i data-rank="{i}"></i><div class="racer_info"><span>確認選手{i}</span></div><div class="prizemoney">¥{10000000-i*1000:,}</div></a>' for i in range(1,n+1))


def test_official_prizes_require_complete_consistent_date_rank_and_amount():
    raw=ranking_html()
    data=parse_omura(raw,2026)
    assert data['through']=='20261026' and len(data['players'])==20
    for bad in (raw.replace('2026年10月26日','2027年10月26日'),raw.replace('¥9,999,000','不明'),ranking_html(17),raw.replace('data-rank="20"','data-rank="21"'),raw.replace('toban=4020','toban=4019')):
        with pytest.raises(ValueError):parse_omura(bad,2026)


def test_prize_page_compares_same_snapshot_and_does_not_declare_qualification():
    data=parse_omura(ranking_html(),2026)
    data['source']='https://omurakyotei.jp/special/2026grandprix/prize_ranking/'
    text=prize_page(Page('players-prizes.html'),data,'20261027',[])
    payload=json.loads(re.search(r'id="pi-data" type="application/json">(.*?)</script>',text)[1])
    assert payload['rows'][17]['gap18']==0
    assert payload['rows'][18]['gap18']==-1000
    assert '出場確定とは判断しません' in text and '2026/10/26' in text


def test_f_snapshots_never_treat_missing_or_previous_period_f_as_zero():
    rows=[{'date':'20261027','jcd':'04','rno':1,'racelist':{'boats':[
        {'toban':'4001','f':2,'f_known':True},{'toban':'4002','f':0,'f_known':False}]}}]
    snapshots=programme_snapshots(rows,'20261027')
    assert list(snapshots)==['4001'] and snapshots['4001']['f']==2
    report={'period':period('20261027'),'f_players':[{'toban':'4002','name':'不明','events':[]}], 'f_preparing':True}
    out=build_f_report(report,snapshots,{},'20261027',{})
    assert next(r for r in out['rows'] if r['toban']=='4002')['f'] is None
    old=deepcopy(snapshots);old['4001']['date']='20260430'
    assert not build_f_report({},old,{},'20261027',{})['rows']


def test_rollover_flag_is_only_a_crosscheck_and_never_claims_unserved_leave():
    report={'period':period('20261102'),'f_period':period('20261031'),'f_preparing':False,
            'f_players':[{'toban':'4001','name':'確認選手','events':[{'date':'20261031'}]}]}
    snapshot={'4001':{'date':'20261101','jcd':'04','rno':1,'f':0}}
    data=build_f_report(report,snapshot,{},'20261102',{})
    assert data['rows'][0]['rollover'] is True and data['rows'][0]['rests']==[]
    assert '未消化とは断定できません' in f_page(Page('players-f.html'),data)
    report['f_players'][0]['current_f_known']=True
    assert not build_f_report(report,snapshot,{},'20261102',{})['rows'][0]['rollover']


def test_public_payload_escapes_html_and_leaves_keep_the_original_basis():
    rest={'toban':'4001','name':'</script><script>bad</script>','source':'https://www.boatrace-tsu.com/test.pdf','document_date':'20261026','days':30,'start':None,'end':None,'status':'snapshot_unserved'}
    data=build_f_report({}, {}, {'records':[rest]},'20261027',{})
    assert data['rows'][0]['f'] is None and data['rows'][0]['rests'][0]['start'] is None
    text=f_page(Page('players-f.html'),data)
    assert '</script><script>bad' not in text and '\\u003c/script>' in text
