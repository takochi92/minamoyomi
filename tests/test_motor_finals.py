import gzip
import json

import pytest

from scraper.motor_finals import MotorFinals, individual_final


@pytest.mark.parametrize('name,expected', [
    ('優 勝 戦 1800m', True), ('優勝戦　進入固定', True),
    ('ＧＰ優勝戦', True), ('S戦優勝戦☆', True), ('MD優勝戦', True),
    ('準優勝戦', False), ('準々優勝戦', False), ('S戦準優勝戦', False),
    ('一般戦 1800m', False), ('優勝戦出場選手紹介', False), ('', False),
])
def test_race_number_or_substring_does_not_turn_a_heat_into_a_final(name, expected):
    assert individual_final(name) is expected


def test_abbreviations_require_the_official_venue_and_event_context():
    assert individual_final('ツッキー優勝', '男女Ｗ優勝戦', '09')
    assert individual_final('ツッピー優勝', '男女Ｗ優勝戦', '09')
    assert not individual_final('ツッキー優勝', '一般競走', '09')
    assert not individual_final('ツッキー優勝', '男女Ｗ優勝戦', '04')
    assert individual_final('県内選手権優', 'ホークス杯福岡県内選手権', '20')
    assert not individual_final('県内選手権優', '福岡県内選手権', '04')
    assert individual_final('団体・優勝戦', 'レディースＶＳルーキーズバトル')
    assert not individual_final('団体・優勝戦', '一般団体競走')
    assert individual_final('賞金女王決定', '第14回クイーンズクライマックス/G3QCシリーズ', '24')
    assert not individual_final('賞金女王決定', '一般競走', '24')
    assert individual_final('決勝戦', '第7回BBCトーナメント', '13')
    assert not individual_final('準決勝戦', '第7回BBCトーナメント', '13')
    assert individual_final('ファイナル', 'ファン感謝３Ｄａｙｓボートレースバトルトーナメント', '09')
    assert not individual_final('ファイナル', '一般競走', '09')
    assert individual_final('王将位決定戦', '第64回全大阪王将戦', '12')
    assert not individual_final('王将位決定戦', '第64回全大阪王将戦', '04')


def saved_race(date='20261018', label='優勝戦', rno=12):
    es = [[i, str(4000+i), i, 10, '', i, 680, None, 20+i, 1] for i in range(1,7)]
    return [date,'04',rno,'逃げ','北',2,1,0,'1-2-3',1000,1,es,
            {'race_name':label,'title':'一般競走'}]


def archive(tmp_path, rows):
    folder=tmp_path/'scraper/database/races';folder.mkdir(parents=True,exist_ok=True)
    with gzip.open(folder/'202610.jsonl.gz','wt',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')


def history_row(i=1, date='20261018', rno=12):
    return dict(date=date,rno=rno,toban=str(4000+i),frame=i,course=i,place=i)


def test_all_finalists_and_champion_require_the_actual_motor_rider_and_result(tmp_path):
    r=saved_race();archive(tmp_path,[r]);index=MotorFinals.load(tmp_path,tmp_path/'data','20261001','20261031')
    assert index.award('04','21',history_row())=='champion'
    for i in range(2,7):assert index.award('04',str(20+i),history_row(i))=='finalist'
    assert index.award('04','99',history_row())==''  # A rider's earlier motor did not contest this final.
    assert index.award('03','21',history_row())==''
    assert index.award('04','21',{**history_row(),'toban':'4999'})==''
    assert index.award('04','21',{**history_row(),'place':2})==''  # Corrected result not yet in motor history.
    assert index.period_award('04','21',[history_row(),history_row(date='20261017')])=='champion'


def test_semi_final_win_nonstarter_and_missing_result_are_not_championships(tmp_path):
    semi=saved_race(date='20261017',label='準優勝戦')
    final=saved_race();final[11][1][5]='K0';final[11][1][2]=None
    final[11][2][5]='F'  # Entered the final; an F is never called a victory.
    archive(tmp_path,[semi,final]);index=MotorFinals.load(tmp_path,tmp_path/'data','20261001','20261031')
    assert index.award('04','21',history_row(date='20261017'))==''
    assert index.award('04','22',{**history_row(2),'course':None,'place':'K0'})==''
    assert index.award('04','23',{**history_row(3),'place':'F'})=='finalist'
    assert index.award('04','21',history_row(date='20261019'))==''


def test_both_finals_of_a_double_championship_and_tied_winners_are_kept(tmp_path):
    rows=[]
    for n,label in ((11,'ツッキー優勝'),(12,'ツッピー優勝')):
        r=saved_race(label=label,rno=n);r[1]='09';r[12]['title']='男女Ｗ優勝戦';r[11][1][5]=1;rows.append(r)
    archive(tmp_path,rows);index=MotorFinals.load(tmp_path,tmp_path/'data','20261001','20261031')
    for n in (11,12):
        assert index.award('09','21',history_row(rno=n))=='champion'
        assert index.award('09','22',{**history_row(2,rno=n),'place':1})=='champion'


def test_recent_saved_results_fill_archive_gaps_but_scheduled_races_do_not(tmp_path):
    folder=tmp_path/'data/races/20261018';folder.mkdir(parents=True)
    live={'date':'20261018','jcd':'04','rno':12,'race_name':'優勝戦 1800m',
          'racelist':{'boats':[{'frame':1,'toban':'4001','motor_no':21}]},
          'result':{'finished':True,'start':[{'frame':1,'course':1}],
                    'order':[{'frame':1,'place':'1'}]}}
    path=folder/'0412.json';path.write_text(json.dumps(live),encoding='utf-8')
    index=MotorFinals.load(tmp_path,tmp_path/'data','20261001','20261031')
    assert index.award('04','21',history_row())=='champion'
    live['result']['finished']=False;path.write_text(json.dumps(live),encoding='utf-8')
    index=MotorFinals.load(tmp_path,tmp_path/'data','20261001','20261031')
    assert index.award('04','21',history_row())==''


def test_html_incident_spelling_does_not_hide_a_confirmed_finalist(tmp_path):
    folder=tmp_path/'data/races/20261018';folder.mkdir(parents=True)
    live={'date':'20261018','jcd':'04','rno':12,'race_name':'優勝戦 1800m',
          'racelist':{'boats':[{'frame':2,'toban':'4002','motor_no':22}]},
          'result':{'finished':True,'start':[{'frame':2,'course':3}],
                    'order':[{'frame':2,'place':'転'}]}}
    (folder/'0412.json').write_text(json.dumps(live),encoding='utf-8')
    index=MotorFinals.load(tmp_path,tmp_path/'data','20261001','20261031')
    assert index.award('04','22',{**history_row(2),'course':3,'place':'S0'})=='finalist'
    assert index.award('04','22',{**history_row(2),'course':3,'place':1})==''
