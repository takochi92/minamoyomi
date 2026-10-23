from scraper import championships as ch, database_views as views


def test_official_category_is_taken_from_column_header():
    page='''<table><thead><tr><th>プレミアムG1</th><th>G1周年記念</th></tr></thead><tbody><tr><td><a href="/owpc/pc/data/record/list?category=4200">BBC</a></td><td><a href="/owpc/pc/data/record/list?category=0501">赤城</a></td></tr></tbody></table>'''
    cats=ch.parse_index(page)
    assert cats[0]['group']=='プレミアムG1' and cats[1]['group']=='G1周年記念'


def test_cancelled_event_is_not_a_winner_and_boat_divisions_preserved():
    cat={'id':'0100','name':'クラシック','group':'SG'}
    page='''<table><tbody><tr><td>第1回</td><td>2026/03/29</td><td><img alt="蒲郡"></td><td class="is-victory">峰 竜太（ハイドロ）</td><td><a href="/owpc/pc/data/record/listdetail?category=0100&amp;record_no=61">詳細</a></td></tr></tbody><tbody><tr><td>中止</td><td>2011年</td><td>戸田</td><td>震災中止</td><td>-</td></tr></tbody></table>'''
    records=ch.parse_list(page,cat)
    assert len(records)==1 and records[0]['number']=='61'
    table='''<table><thead><tr><th>着</th><th>レーサー</th><th>登番</th><th>ST</th><th>節間成績</th></tr></thead><tbody><tr><td>１</td><td>峰　竜太</td><td>4320</td><td>.11</td><td>３３１１１</td></tr></tbody></table>'''
    record=ch.parse_detail(table+table,records[0])
    assert len(record['divisions'])==2
    assert record['divisions'][0][0]['player']=='4320'
    assert record['divisions'][0][0]['place']=='1'
    assert record['divisions'][0][0]['fields']['節間成績']=='33111'


def test_official_finals_do_not_claim_all_sg_entries():
    result=views.official_finals_panel([{'date':'20260329','venue':'蒲郡','name':'クラシック','group':'SG','category':'0100','number':'61','place':'1'}])
    assert 'champion-0100-61.html' in result and '全SG出場回数とは異なり' in result


def test_birth_date_era_conversion():
    assert views.birth_date({'birth_era':'S','birth_date':'600101'})=='1985/01/01'
    assert views.birth_date({'birth_era':'H','birth_date':'011231'})=='1989/12/31'
    assert views.birth_date({'birth_era':'S','birth_date':'601333'})=='未確認'


def test_attack_rates_use_all_course_starts_not_only_wins():
    from scraper import racer_views as rv, racer_database as rd
    m=rd.metric([]);m.update(n=20,kim={'逃げ':0,'差し':2,'まくり':3,'まくり差し':0,'抜き':0,'恵まれ':0})
    rendered=rv.attack_rates({'course':{'3':m}})
    assert '20走' in rendered and '10.0%' in rendered and '15.0%' in rendered
    assert '40.0%' not in rendered and '60.0%' not in rendered
