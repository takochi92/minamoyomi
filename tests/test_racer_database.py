from datetime import datetime
from scraper import history, racer_database as rd, sitegen


def race(day="20261020", decision="逃げ", second=3):
    order = [1, second] + [c for c in range(2, 7) if c != second]
    entries = [[c, str(4000+c), c, 10+c, "", order.index(c)+1,
                680 if c < 3 else 680+c, None, 20+c, 50+c] for c in range(1,7)]
    return [day,"01",1,decision,"北",2,0,0,"1-3-2",10000,15,entries]


def test_database_windows_denominators_and_decisions():
    records = [race("20241020"), race(), race("20261024"), race("20261025")]
    db = rd.build_index(records,"20261024")
    assert db["races"] == 2 and db["through"] == "20261020"
    player = rd.profile(db["players"]["4003"],"20261024")
    w = player["windows"]["365"]
    assert w["total"]["n"] == 1 and w["total"]["places"] == [0,1,0,0,0,0]
    assert w["remain"]["3"]["n"] == 1 and w["remain"]["3"]["places"][1] == 1
    assert sum(w["total"]["kim"].values()) == 0  # winner's decision is not the loser's winning method
    assert player["windows"]["all"]["total"]["n"] == 2
    assert player["windows"]["730"]["total"]["n"] == 1


def test_tied_exhibitions_accidents_missing_boat_and_in_loss():
    r = race(decision="差し")
    r[11][0][5] = 2
    r[11][1][5] = 1
    r[11][4][4] = "F"
    r[11][4][5] = "F"
    r[11][4][3] = 1
    r[11][5][2] = None
    r[11][5][5] = "K0"
    r[11][5] = r[11][5][:9]  # legacy row has no boat number
    db = rd.build_index([r], "20261024")
    assert db["players"]["4001"][0][14] == 1
    assert db["players"]["4002"][0][14] == 1
    assert db["players"]["4003"][0][14] == 3
    a = rd.profile(db["players"]["4001"],"20261024")["windows"]["365"]
    assert a["losses"] == {"2コース・差し":1} and a["inside_n"] == 1
    assert not a["remain"]
    f = rd.profile(db["players"]["4005"],"20261024")["windows"]["365"]["total"]
    assert f["n"] == 1 and f["st"] is None and f["f"] == 1 and f["other"] == 1
    k = rd.profile(db["players"]["4006"],"20261024")
    assert k["windows"]["all"]["total"]["n"] == 0 and k["rows"][0][10] is None


def test_missing_exhibition_has_no_rank():
    r = race()
    r[11][-1][6] = None
    db = rd.build_index([r], "20261024")
    assert all(rows[0][14] is None for rows in db["players"].values())


def test_history_preserves_boat_number_without_shifting_model_fields():
    raw = {"date":"20261020", "jcd":"01", "rno":1, "kimarite":"逃げ", "wind_dir":"北", "wind_speed":2,
           "wave":0,"fixed":False,"entries":[{"frame":1,"toban":"4001","course":1,"st":.12,"st_flag":"",
           "place":1,"code":"","exhibit_time":6.8,"motor_no":21,"boat_no":51}]}
    rec = history.to_record(raw,{})
    assert rec[11][0][8:] == [21,51] and rec[11][0][:7] == [1,"4001",1,12,"",1,680]


def test_render_and_empty_player_are_honest_and_safe():
    db = rd.build_index([race()],"20261024")
    page = sitegen.Page("racer/4001.html")
    data = rd.profile(db["players"]["4001"],db["as_of"])
    result = rd.render("4001",{"name":"テスト</script><img>","class":"B1","win":5.1},data,db,page,sitegen.VENUES,sitegen.SLUG)
    assert 'id="rd-data"' in result and '../racer.js' in result and '保存全期間' in result
    assert '生涯通算成績ではありません' in result and '1コースが逃げたときの残り方' in result
    assert 'テスト</script><img>' not in result
    assert rd.profile([],"20261024")["windows"]["365"]["total"]["st"] is None


def test_roster_players_without_recent_records_still_get_pages(monkeypatch):
    db = rd.build_index([race()], "20261024")
    monkeypatch.setattr(rd, "load", lambda _: db)
    monkeypatch.setattr(sitegen.fstart, "load_pairs", lambda: {})
    s = sitegen.Site(datetime(2026,10,24,tzinfo=sitegen.JST))
    s.racers = {"4001":{"name":"記録あり","branch":"広島","class":"B1"},
                "9999":{"name":"記録なし","branch":"広島","class":"B2"}}
    s.idx = {"date":"20261024","venues":[]}
    listed = []
    s.racer_index = lambda listing, today: listed.extend(listing)
    s.racer_pages()
    assert listed == ["4001","9999"]
    assert "racer/9999.html" in s.files and "未保存" in s.files["racer/9999.html"]


def test_donut_parts_have_one_denominator_and_include_unknown_results():
    from scraper import racer_views as views
    records = [race("20261018"),race("20261019", "差し"),race("20261020")]
    records[1][11][0][5], records[1][11][1][5] = 2,1
    records[2][11][0][5] = 'F'
    records[2][11][0][4] = 'F'
    db = rd.build_index(records, '20261024')
    w = rd.profile(db['players']['4001'],'20261024')['windows']['365']
    parts = views.inside_parts(w)
    assert w['inside_n'] == 3 and sum(v for _,v in parts) == 3
    assert parts[0][1] == 1 and parts[1][1] == 1 and parts[-1][1] == 1
    assert all(v >= 0 for _,v in parts)
    assert 'viewBox="0 0 100 100"' in views.donut(parts,3)
    assert 'stroke-dasharray' not in views.donut([(x,0) for x,_ in parts],0)


def test_compact_history_keeps_equipment_and_start_details():
    from scraper import racer_views as views
    db = rd.build_index([race()], '20261024')
    rows = db['players']['4001']
    result = views.history_table(rows, {'01':'桐生'})
    assert '<summary>' in result and '1着' in result
    assert 'モーター' in result and '<dd>21</dd>' in result and '<dd>51</dd>' in result
    assert '勝者の決まり手：逃げ' in result
