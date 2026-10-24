import gzip,json
from pathlib import Path
from scraper import database_sources as source, database_build as build, database_views as views
from scraper import racer_database as rd


def official_record(year=2026,half=2):
    raw=bytearray(b'0'*416)
    def put(a,b,value):raw[a:b]=str(value).encode('cp932').ljust(b-a,b' ')
    put(0,4,'4001');put(4,20,'公式テスト');put(20,35,'ｺｳｼｷﾃｽﾄ')
    put(35,39,'広島');put(39,41,'A1');put(41,42,'S');put(42,48,'600101')
    put(48,49,'1');put(49,51,'40');put(51,54,'170');put(54,56,'52');put(56,58,'A')
    put(58,62,'0700');put(62,66,'0500');put(66,69,'030');put(69,72,'020');put(72,75,'100')
    put(75,77,'02');put(77,79,'01');put(79,82,'015')
    put(174,178,year);put(178,179,half);put(179,187,'20251101');put(187,195,'20260430');put(195,198,'085')
    put(410,416,'広島')
    return bytes(raw)+b'\r\n'


def test_official_period_layout_and_old_location_are_not_branch():
    p=source.parse_period(official_record())
    s=p['players']['4001']
    assert p['id']=='2026-2' and p['from']=='20251101'
    assert s['win']==7 and s['top2']==50 and s['starts']==100 and s['titles']==1
    assert s['branch']=='広島' and s['ki']==85 and len(s['courses'])==6
    old=source.parse_period(official_record(2002,1))['players']['4001']
    assert old['branch'] is None and old['location']=='広島'
    rendered=views.period_panel([dict(p,source='https://www.boatrace.jp/file',stats=s)])
    assert '2026年後期' in rendered and '公式勝率' in rendered and '事故内訳' in rendered


def test_roster_union_keeps_historical_status_and_period_values():
    a=source.parse_period(official_record(2025,2));b=source.parse_period(official_record())
    a['players']['3999']={**a['players']['4001'],'name':'過去選手'}
    for term in (a,b):term['source']='https://www.boatrace.jp/file'
    roster,terms=build.roster_catalog([a,b])
    assert roster['3999']['historical'] and not roster['4001']['historical']
    assert len(terms['4001'])==2 and terms['3999'][0]['id']=='2025-2'


def test_sqlite_merge_prefers_richer_official_row_and_excludes_future(tmp_path):
    ents=[[i,str(4000+i),i,15,'',i,680+i,None,20+i,50+i,'選手'] for i in range(1,7)]
    basic=['20261023','01',12,'逃げ','北',2,1,0,'1-2-3',1200,1,ents]
    rich=basic+[{'title':'公式開催','day':1,'race_name':'優 勝 戦','grade':None}]
    paths=[]
    for i,rows in enumerate(([basic],[rich],[basic])):
        p=tmp_path/f'{i}.jsonl.gz';p.write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in rows)+'\n').encode()));paths.append(p)
    db=build.open_cache(tmp_path/'cache.sqlite');build.ingest(db,paths)
    assert db.execute('SELECT count(*) FROM races').fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM entries').fetchone()[0]==6
    assert len(json.loads(db.execute('SELECT payload FROM races').fetchone()[0]))==13
    result=build.event_summary(db,'20261024')
    assert result['events'][0]['final']['winners']==['4001']
    assert result['venues']['01']['payout_n']==1
    assert build.event_summary(db,'20261023')['events']==[]
    db.close()


def test_final_classification_does_not_count_semifinal_as_title():
    data=views.titles_panel([{'title':'テスト<script>','venue':'01','grade':None,'final':{'date':'20261023','entrants':['4001'],'winners':['4002']}}],'4001',{'01':{'name':'桐生'}})
    assert '格付未確認' in data and 'テスト&lt;script&gt;' in data and '優出' in data
    assert '<b class="db-gold">優勝</b>' not in data


def test_ninety_day_window_is_separate_from_year():
    row=['20260101','01',1,1,1,1,15,'',680,20,50,'逃げ',1,1200,1]
    p=rd.profile([row],'20261024')
    assert p['windows']['90']['total']['n']==0 and p['windows']['365']['total']['n']==1


def test_old_k_dates_weather_spacing_and_payout_decision():
    lines=['24KBGN','＊＊＊ 競走成績 ＊＊＊','公式テスト','第 1日 97/ 1/ 1',
           ' 1R 予 選 H1800m は れ 風 南東 4m 波 3cm',
           ' 着 艇 登番 選手名 ﾓｰﾀｰ ﾎﾞｰﾄ 展示 進入 ｽﾀｰﾄﾀｲﾐﾝｸﾞ ﾚｰｽﾀｲﾑ','---------------',
           ' 01 3 4001 テスト一 53 66 6.76 1 0.33 1.50.7',
           ' 02 2 4002 テスト二 50 53 6.73 4 0.18 1.51.6',
           ' 連複 2-3 1500 人気 8 決まり手 抜き']
    records=source.parse_database_k(('\r\r\n\r\r\n'.join(lines)).encode('cp932'))
    assert len(records)==1 and records[0][:4]==['19970101','24',1,'抜き']
    assert records[0][8] is None and records[0][9] is None # never relabel 2連複 as 3連単
    assert len(records[0][11])==2 and records[0][11][0][2]==1
    assert records[0][12]['race_name']=='予選'
    calm=source.parse_database_k(('\n'.join(lines).replace('南東 4m','無　風 0m')).encode('cp932'))
    assert calm[0][4]=='無風' and calm[0][5]==0
    import pytest
    with pytest.raises(ValueError,match='Official race sections missing'):
        source.parse_database_k(('\n'.join(lines).replace('は れ','')).encode('cp932'))


def test_complete_official_day_removes_cancelled_legacy_race(tmp_path,monkeypatch):
    official=tmp_path/'database';raw=official/'races';raw.mkdir(parents=True)
    old=tmp_path/'history';old.mkdir()
    monkeypatch.setattr(build,'BASE',official)
    ents=[[i,str(4000+i),i,15,'',i,680,None,20,50] for i in range(1,7)]
    r=['20261023','01',1,'逃げ','北',2,0,0,'1-2-3',1200,1,ents]
    cancelled=[*r];cancelled[2]=2
    baseline=old/'202610.jsonl.gz';updated=raw/'202610.jsonl.gz'
    baseline.write_bytes(gzip.compress(('\n'.join(json.dumps(x) for x in [r,cancelled])+'\n').encode()))
    updated.write_bytes(gzip.compress((json.dumps(r+[{'title':'公式'}])+'\n').encode()))
    db=build.open_cache(tmp_path/'cache.sqlite');build.ingest(db,[baseline,updated])
    assert db.execute('SELECT count(*) FROM races').fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM entries').fetchone()[0]==6
    # Even a subsequently changed legacy source cannot resurrect that race.
    baseline.write_bytes(gzip.compress(('\n'.join(json.dumps(x) for x in [cancelled,r])+'\n').encode()))
    build.ingest(db,[baseline])
    assert db.execute('SELECT count(*) FROM races').fetchone()[0]==1
    db.close()


def test_temporary_download_failures_retry_without_repeated_404_requests():
    from datetime import datetime,timedelta
    now=datetime(2026,10,24,tzinfo=source.JST)
    failed={'status':'unavailable','error':'ReadTimeout','parser_version':source.PARSER_VERSION,'checked_at':(now-timedelta(days=2)).isoformat()}
    assert source.needs_update('20200101',failed,now)
    assert not source.needs_update('20200101',{**failed,'http_status':404},now)
    assert not source.needs_update('20200101',{**failed,'status':'saved'},now)
    assert source.needs_update('19970101',{'status':'saved','parser_version':1},now)


def test_git_friendly_cache_is_readable_by_existing_profile_loader(tmp_path):
    row=['20261023','01',1,1,1,1,15,'',680,20,50,'逃げ',1,1200,1]
    data=rd.profile([row],'20261024')
    source.write_json(tmp_path/'4001.json.gz',data,compression=0)
    assert source.read_json(tmp_path/'4001.json.gz')==data
    assert rd.ProfileFiles(tmp_path)['4001']==data


def test_double_championship_keeps_both_finals(tmp_path):
    rows=[]
    for race_no,label,start in [(10,'準優勝戦',4000),(11,'優勝戦',4010),(12,'優勝戦',4020)]:
        entries=[[i,str(start+i),i,15,'',i,680,None,20,50] for i in range(1,7)]
        rows.append(['20261023','01',race_no,'逃げ','北',2,0,0,'1-2-3',1200,1,entries,{'title':'男女W優勝戦','day':6,'race_name':label}])
    source_file=tmp_path/'races.jsonl.gz'
    source_file.write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in rows)+'\n').encode()))
    db=build.open_cache(tmp_path/'cache.sqlite');build.ingest(db,[source_file])
    result=build.event_summary(db,'20261024')
    assert {e['final']['race'] for e in result['events'] if e['final']}=={11,12}
    assert {t for e in result['events'] for t in e['final']['winners']}=={'4011','4021'}
    db.close()
