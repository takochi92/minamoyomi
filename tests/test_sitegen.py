import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402
from scraper import fan, parse, predict as P, sitegen, run  # noqa: E402


def test_account_assets_refresh_cached_clients_only_when_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(sitegen, 'ROOT', tmp_path)
    assets = tmp_path / 'site'
    assets.mkdir()
    for name in ('style.css', 'config.js', 'clock.js', 'note-store.js', 'note-account.js', 'note.js'):
        (assets / name).write_text('initial-' + name, encoding='utf-8')
    page = sitegen.Page('racer/5037.html')
    before = page.asset('config.js')
    assert re.fullmatch(r'../config\.js\?v=[a-f0-9]{12}', before)
    assert page.asset('config.js') == before
    html = page.render('test', 'test', '')
    for name in ('style.css', 'config.js', 'clock.js', 'note-store.js', 'note-account.js', 'note.js'):
        assert page.asset(name) in html
    # A rollout/config change must bypass the old browser-cached script, while
    # untouched scripts keep their URL and can still use the browser cache.
    unchanged = page.asset('note.js')
    (assets / 'config.js').write_text('public account configuration', encoding='utf-8')
    assert page.asset('config.js') != before
    assert page.asset('note.js') == unchanged
    assert sitegen.Page('mynote.html').asset('config.js').startswith('config.js?v=')


def test_cached_build_matches_full_build_including_player_roster_and_links(tmp_path):
    from scraper.build_cache import BuildCache
    first, expected = _site(tmp_path)
    expected = dict(expected)
    expected_bins = dict(first.bins)
    cold = sitegen.Site(first.now)
    cold.build(BuildCache(tmp_path / 'build-cache', 'same-inputs'))
    assert cold.files == expected and cold.bins == expected_bins
    warm = sitegen.Site(first.now)
    cache = BuildCache(tmp_path / 'build-cache', 'same-inputs')
    warm.build(cache)
    assert cache.hits >= 1
    assert warm.files == expected and warm.bins == expected_bins
    assert warm.racers == cold.racers


def test_missing_detailed_exhibition_is_explicit_and_public_revision_is_checked():
    s = sitegen.Site.__new__(sitegen.Site)
    s.day_means = lambda *_: {}
    race = {'racelist': {'boats': [{'frame': 1, 'name': '確認選手'}]},
            'before': {'boats': [{'frame': 1, 'exhibit_time': 6.80}]}}
    html = s.oriten_block(race)
    assert '詳細展示は未取得' in html and '6.80' in html
    assert 'ex-data-status' in html
    race['oriten'] = {'items': ['一周', '直線'], 'rows': {'1': [36.20, 6.90]}}
    html = s.oriten_block(race)
    assert '詳細展示は未取得' not in html and '36.20' in html and '直線' in html
    fresh = s.freshness_block(sitegen.Page('race/20261026/kiryu-1.html'),
                               '2026-10-26T09:00', '20261026-01-1')
    assert 'data-revision="2026-10-26T09:00"' in fresh
    assert '../../freshness.json' in fresh and 'data-key="20261026-01-1"' in fresh


def _site(tmp_path):
    rl = parse.parse_racelist(fx.racelist_html())
    bi = parse.parse_beforeinfo(fx.beforeinfo_html())
    race = {"date": "20260925", "jcd": "01", "venue": "桐生", "rno": 12, "deadline": "20:35", "race_name": rl["race_name"],
            "racelist": {"boats": rl["boats"]}, "before": bi, "prediction": P.predict("01", {"boats": rl["boats"]}, bi)}
    d = tmp_path / "data"
    (d / "races" / "20260925").mkdir(parents=True)
    (d / "races" / "20260925" / "0112.json").write_text(json.dumps(race, ensure_ascii=False), encoding="utf-8")
    idx = {"date": "20260925", "updated_at": "2026-09-25T20:00", "venues": [
        {"jcd": "01", "name": "桐生", "title": "t", "grade": "一般", "timezone": "", "day": "", "races": [run.summarize(race)]}]}
    (d / "index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    sitegen.OUT, sitegen.DATA = tmp_path, d
    s = sitegen.Site(datetime(2026, 9, 25, 20, 0, tzinfo=sitegen.JST))
    return s, s.build()


def test_pages_and_links(tmp_path):
    s, files = _site(tmp_path)
    assert "race/20260925/kiryu-12.html" in files and "venue/omura.html" in files and "targets.html" in files
    assert len([p for p in files if p.startswith("racer/")]) > 1000
    assert 'id="page-freshness"' in files['venue/kiryu.html']
    assert 'data-revision="2026-09-25T20:00"' in files['venue/kiryu.html']
    assert 'id="page-freshness"' not in files['venue/omura.html']
    stats=files['stats.html']; logic=files['logic.html']
    assert 'id="logic-details" class="evidence-fold"' in stats
    assert '<summary>締切前に固定した研究券の成績</summary>' in stats
    assert 'window.__ROUTE__="stats"' in stats and 'app.js?v=' in stats
    assert 'window.__ROUTE__="stats"' in logic and 'window.__OPEN_LOGIC__=true' in logic
    assert 'content="noindex"' in logic
    # 相対リンクがすべて生成済みのページを指している（外部・data・アンカーは除く）
    for path in ["index.html", "race/20260925/kiryu-12.html", "targets.html", "venue/kiryu.html"]:
        base = Path(path).parent
        for href in re.findall(r'href="([^"#:]+\.html)"', files[path]):
            target = (base / href).as_posix()
            while "/../" in "/" + target:
                parts = target.split("/")
                i = parts.index("..")
                target = "/".join(parts[:i - 1] + parts[i + 1:])
            assert target in files or target in ("about.html",), (path, href)


def test_st_page_uses_saved_local_estimate_and_separates_meeting(tmp_path):
    s, _ = _site(tmp_path)
    path = tmp_path / 'data/races/20260925/0112.json'
    race = json.loads(path.read_text(encoding='utf-8'))
    b = race['racelist']['boats'][0]
    c = next(x['course'] for x in race['before']['start_exhibition'] if x['frame'] == b['frame'])
    race['start_timing'] = {'boats': {str(b['frame']): {'toban': b['toban'], 'course': c, 'st': .15, 'sd': .04,
        'course_mean': .16, 'n': 50, 'local_mean': .13, 'local_n': 12, 'meeting_mean': .12, 'meeting_n': 3}}}
    path.write_text(json.dumps(race), encoding='utf-8')
    s.st_pages()
    html = s.files['race/20260925/kiryu-12-st.html']
    assert '0.15秒' in html and '0.13秒・12走' in html
    assert '0.12秒・3走（全コース・前日まで）' in html
    assert '今節平均は参考表示のみ' in html
    race_html=s.files['race/20260925/kiryu-12.html']
    assert 'slit-animation' in race_html and 'slit.js' in race_html
    assert 'data/races/20260925/0112.json' in race_html
    assert 'img/slit-boat-1.svg' in s.bins and 'img/slit-boat-6.svg' in s.bins
    assert 'slit-zoom' in race_html and '到達差を拡大' in race_html


def test_exhibition_mobile_labels_preserve_all_values_and_missing_items():
    s = sitegen.Site()
    race = {'date': '20261025', 'jcd': '03', 'rno': 1, 'deadline': '23:59',
            'racelist': {'boats': [{'frame': f, 'name': '長い名前の選手', 'toban': str(4000 + f)} for f in range(1, 7)]},
            'before': {'boats': [{'frame': f, 'exhibit_time': 6.80, 'tilt': 3.0} for f in range(1, 7)]},
            'oriten': {'items': ['一周', 'まわり足', '直線', '半周'], 'rows': {'1': [36.72, 5.12, 7.63, None]}}}
    html = s.oriten_block(race)
    assert 'class="panel ex-compact ex-primary"' in html
    for label in ['展示タイム', '一周', 'まわり足', '直線', '半周']:
        assert html.count(f'data-label="{label}"') == 6
    assert '36.72' in html and '7.63' in html
    html = s.ex_tab('20261025', '03', 1, race, {})
    for label in ['展示タイム', '今節平均', 'いつもの1位率', 'チルト']:
        assert f'data-label="{label}"' in html
    assert html.count('data-label="展示タイム"') == 6
    assert '<details class="panel ex-reference ex-compact"' in html
    assert 'id="ex-reference" open' not in html
    assert html.index('<table class="t-ori') < html.index('id="ex-reference"')
    waiting = dict(race, before={}, oriten=None)
    fallback = s.oriten_block(waiting, {'boats': [{'frame': 1, 'exhibit_time': 6.79}]})
    assert fallback.count('data-label="展示タイム"') == 6 and '6.79' in fallback
    official = s.oriten_block(race, {'boats': [{'frame': 1, 'exhibit_time': 6.79}]})
    assert '6.79' not in official  # Existing official beforeinfo takes priority.


def test_motor_history_has_all_users_dates_and_official_result_links():
    from scraper.motor import build
    from tests.test_motor_history import race
    rows = [race('20260525', '5082'), race('20261008'), race('20261022', '4925')]
    s = sitegen.Site()
    s._motor_page('03', sitegen.VENUES['03'], build(rows, []))
    html = s.files['venue/edogawa-motor.html']
    assert '西田 和加' in html and '2026/10/08' in html and '2026/05/25' in html
    assert '全使用履歴' in html and '公式の節区分ではありません' in html
    assert 'hd=20261008&amp;jcd=03&amp;rno=1' in html
    assert '交換日不明' in html
    assert '初卸からの網羅性は未確認' in html


def test_seo_basics(tmp_path):
    _, files = _site(tmp_path)
    page = files["race/20260925/kiryu-12.html"]
    assert "<title>桐生12R 予想" in page and 'rel="canonical"' in page and "BreadcrumbList" in page
    assert "20歳未満" in page and "保証するものではありません" in page
    assert "山下 流心" in page
    sm = files["sitemap.xml"]
    assert sm.count("<url>") == len([p for p in files if p.endswith(".html") and p != "404.html" and 'content="noindex"' not in files[p]])
    assert "mynote.html" not in sm and "share.html" not in sm and "<lastmod>2026-09-25</lastmod>" in sm
    assert "Sitemap:" in files["robots.txt"]


def test_fan_parse():
    rec = "4872山下　流心　　　　　　　ﾔﾏｼﾀ ﾘｭｳｼﾝ    広島B1".encode("cp932")
    assert rec[:4] == b"4872"
    racers = json.loads((Path(fan.__file__).parent / "racers.json").read_text(encoding="utf-8"))["racers"]
    assert racers["4872"]["name"] == "山下 流心" and racers["4872"]["branch"] == "広島"


def test_overperf_score_shrinks():
    from scraper import overperf
    assert overperf.score(0, 0) == 1.0
    assert overperf.score(6, 2.0) == 2.0           # 期待2回のところ6勝
    assert overperf.score(1, 0.2) < overperf.score(6, 2.0)   # 少ない出走は1に寄せる


def test_targets_not_just_strong(tmp_path):
    s, files = _site(tmp_path)
    cour, _, _ = s.rankings()
    # 4コース上位20人のスコアは、実力（期待1着率）で割った値。A1ばかりにならない
    cls = [s.racers[t]["class"] for _, t, *_ in cour[4][1]]
    assert sum(c.startswith("B") for c in cls) >= 5
    assert "実力どおりなら" in files["targets.html"]


def test_in_worry_block():
    import numpy as np
    from scraper.model import FEATS
    X = np.zeros((6, len(FEATS)))
    X[0, FEATS.index("rc_win")] = -0.5          # インのコース成績が悪い
    X[2, FEATS.index("mu")] = 1.5               # 3コースの攻め手がかみ合う
    w = P.in_worry(X, {f: f for f in range(1, 7)}, [1, 2, 3, 4, 5, 6], ["1コースAの逃げ率30%（全国平均55%・20走）。"])
    assert w["level"] == 2 and w["attacker"] == 3 and w["hist_in_win"] < 0.3 and w["reasons"]
    X[0, FEATS.index("rc_win")] = 0.2
    assert P.in_worry(X, {f: f for f in range(1, 7)}, [1, 2, 3, 4, 5, 6], []) is None


def _fan_line(toban, ki, sex, win=550):
    name = "山田　太郎".encode("cp932").ljust(16, b" ")
    kana = "ﾔﾏﾀﾞ ﾀﾛｳ".encode("cp932").ljust(15, b" ")
    rec = (str(toban).encode() + name + kana + "広島".encode("cp932") + b"A1" + b"S" + b"600101" + str(sex).encode() + b"30"
           + b"170" + b"52" + b"A " + str(win).zfill(4).encode())
    rec = rec.ljust(fan.KI_AT, b"0") + str(ki).zfill(3).encode()
    return rec.ljust(400, b"0") + "広島".encode("cp932").ljust(6, b" ")


def test_fan_ki_and_lady():
    lines = [_fan_line(3000 + i * 10, 40 + i // 3, 2 if i % 7 == 0 else 1) for i in range(200)]
    out = fan.parse_fan(b"\r\n".join(lines))
    assert out["3000"]["ki"] == 40 and out["3990"]["ki"] == 40 + 99 // 3
    assert out["3000"].get("lady") and not out["3010"].get("lady")
    assert out["3000"]["name"].startswith("山田") and out["3000"]["win"] == 5.5
    # 期がばらばら（登番と合わない）なら入れない
    bad = [_fan_line(3000 + i * 10, (i * 37) % 120 + 1, 1) for i in range(200)]
    assert "ki" not in fan.parse_fan(b"\r\n".join(bad))["3000"]


def test_racer_search_and_fav(tmp_path):
    _, files = _site(tmp_path)
    page = files["racer/index.html"]
    assert 'id="sx-data"' in page and "search.js" in page and "支部別の全選手一覧" in page
    data = json.loads(re.search(r'<script id="sx-data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert len(data["racers"]) > 1000 and data["date"] == "20260925"
    fav = json.loads(files["fav-today.json"])
    assert fav["racers"] and all(x[2].startswith("race/20260925/") for v in fav["racers"].values() for x in v)
    assert 'class="fav-btn"' in files["racer/4872.html"] and 'id="fav-today"' not in files["index.html"]


def test_ex_counts_and_meet(tmp_path, monkeypatch):
    from scraper import history
    E = [[f, f"40{f}0", f, 15, "", f, 670 + (f > 2) * f, None] for f in range(1, 7)]
    c = history.ex_counts([["20260920", "01", 1, "逃げ", "", 0, 0, 1, "", 0, 0, E]])
    assert c["4010"] == [1, 1] and c["4020"] == [1, 1] and c["4030"] == [1, 0]   # 同タイム1位は両方1位
    s, files = _site(tmp_path)
    rl = {b["frame"]: b for b in json.loads((sitegen.DATA / "races" / "20260925" / "0112.json").read_text(encoding="utf-8"))["racelist"]["boats"]}
    t = rl[1]["toban"]
    rec = lambda d, jcd, x: [d, jcd, 1, "", "", 0, 0, 1, "", 0, 0, [[1, t, 1, 15, "", 1, x, None]]]
    # 9/24・9/23 は今節、9/20（3日あき）と別の場は入れない
    s._mx = None
    monkeypatch.setattr(sitegen, "load_all", lambda since: [rec("20260924", "01", 680), rec("20260923", "01", 690),
                                                           rec("20260920", "01", 600), rec("20260924", "02", 600)])
    m = s.meet_ex("20260925", "01", t, 12)
    assert m and m[1] == 2 and abs(m[0] - 6.85) < 1e-9
    assert s.meet_ex("20260925", "01", t, 1)[1] == 2   # 当日の展示は、そのレースより前の分だけ
    s.exs = {t: [100, 31]}
    race = json.loads((sitegen.DATA / "races" / "20260925" / "0112.json").read_text(encoding="utf-8"))
    tab = s.ex_tab("20260925", "01", 12, race, race["prediction"])
    assert "31%" in tab and "6.85" in tab and "スタート展示" in tab
    page = files["race/20260925/kiryu-12.html"]
    assert 'data-t="tenji"' in page and "このコースの成績" in page


def test_coursest():
    from scraper import coursest
    wm = {"01": {"offset": 0}}
    # 対応表のずれ0：東（アイコン5＝右向き）は追い風、西は向かい風、2m以下は弱い
    assert coursest.hist_wind("01", "東", 5, wm) == "追い風" and coursest.hist_wind("01", "西", 5, wm) == "向かい風"
    assert coursest.hist_wind("01", "北", 5, wm) == "横風" and coursest.hist_wind("02", "東", 1, wm) == "弱い"
    assert coursest.hist_wind("02", "東", 5, wm) is None
    E = [[f, f"40{f}0", f, 10 + f, "F" if f == 6 else "", f, 670, None] for f in range(1, 7)]
    j = coursest.build([["20260920", "01", 1, "逃げ", "東", 5, 4, 1, "", 0, 0, E]], wm)
    assert j["r"]["4010"]["1"]["w追い風"] == [1, 1, 1, 11, 1] and j["r"]["4010"]["1"]["h1"][0] == 1
    assert j["r"]["4060"]["6"]["a"] == [1, 0, 0, 0, 0]          # F は ST に入れない
    assert j["all"]["1"]["v01"][0] == 1


def test_race_og_image(tmp_path):
    s, files = _site(tmp_path)
    assert "og/20260925/kiryu-12.png" in s.bins and s.bins["og/20260925/kiryu-12.png"][:4] == b"\x89PNG"
    assert 'og/20260925/kiryu-12.png"' in files["race/20260925/kiryu-12.html"]


def test_share_texts(tmp_path):
    from scraper import share
    assert share.weight("あa https://example.com/very/long/path") == 2 + 1 + 1 + 23
    vs = [{"name": "桐生", "jcd": "01", "races": [{"rno": i, "deadline": f"1{i % 10}:00", "level": i % 4, "confidence": "本命",
                                                  "honmei": ["1-2-3"]} for i in range(1, 13)]}]
    t = share.morning("20261008", vs, "https://teilog.pages.dev/")
    assert share.weight(t) <= 280 and "【10/8(木) AI予想】" in t and "必ず" not in t
    h = {"20260929": {"races": 10, "hits": 4, "invest": 1000, "return": 800, "best": [{"venue": "桐生", "rno": 1, "combo": "1-2-3", "payout": 5000, "jcd": "01"}]},
         "20261005": {"races": 5, "hits": 1, "invest": 500, "return": 100}}
    ws = share.weeks(h, "20261008", 2)
    assert ws[0][0] == "20260928" and ws[0][2]["races"] == 10 and len(ws) == 1 and share.weight(share.week_text(*ws[0], "u")) <= 280
    s, files = _site(tmp_path)
    assert "share.html" in files and "weekly.html" in files and "twitter.com/intent/tweet" not in files["race/20260925/kiryu-12.html"]


def test_grade_page(tmp_path):
    s, files = _site(tmp_path)
    assert "grade.html" in files and "今日は重賞の開催がありません" in files["grade.html"]
    s.idx["venues"][0]["grade"] = "G1"
    s.grade_page()
    assert "今日のG1 予想" in s.files["grade.html"] and "kiryu-12.html" in s.files["grade.html"]
    assert "今日の重賞" in s.grade_banner(sitegen.Page("index.html"))
    brief=s.grade_banner(sitegen.Page('index.html'))
    assert 'img/grades/g1.png' in brief and '#grade-01' in brief and 'class="grade-brief-row"' in brief
    assert 'class="panel"' not in brief and '重賞レースだけの予想まとめ' not in brief
    assert 'id="grade-01"' in s.files['grade.html']


def test_buffs_and_ai_block(tmp_path):
    parts = {"展示タイム": 0.45, "モーター": 0.2, "選手のコース別成績": 0.2, "当地勝率": 0.09, "平均ST": -0.2}
    bf = sitegen.buffs(parts)
    assert bf[0] == ("展示", 2) and ("モーター", 1) in bf and ("スタート", -1) in bf
    s, files = _site(tmp_path)
    page = files["race/20260925/kiryu-12.html"]
    assert "AIの見立て" in page and 'class="ai1"' in page
    p = {"stage": "直前", "boats": [{"frame": 1, "course": 1, "p_win": 0.5, "p_top2": 0.7, "p_top3": 0.8, "parts": parts}]}
    html = s.ai_block(p, {1: "山田 太郎"})
    assert "金バフ・全部のせ" in html and "tier-gold" in html
    assert sitegen.buff_tier([("モーター", 1), ("展示", 2)]) == "silver" and sitegen.buff_tier([("モーター", 1), ("得意コース", 1)]) == "silver" and sitegen.buff_tier([("展示", 2)]) is None
    from scraper import share
    t = share.buff_all([("桐生", 1, "10:00", 1, 1, ["展示", "モーター", "得意コース", "得意場"])], "u")
    assert share.weight(t) <= 280 and "1号艇" in t


def test_arechu_shown_on_race_and_top(tmp_path):
    s, _ = _site(tmp_path)
    p = tmp_path / "data" / "races" / "20260925" / "0112.json"
    race = json.loads(p.read_text(encoding="utf-8"))
    for b in race["racelist"]["boats"]:        # 1号艇A1で外との差が小さい
        b["class"] = "A1" if b["frame"] == 1 else "B1"
        b["nat_win"] = 6.0 if b["frame"] == 1 else 5.6
    race["before"]["weather"] = {"wave_cm": 5, "wind_speed": 4}
    for b in race["before"]["boats"]:
        b["exhibit_time"] = 6.9 if b["frame"] == 1 else 6.75
    p.write_text(json.dumps(race, ensure_ascii=False), encoding="utf-8")
    assert "荒れ注意" in s.arechu_block(race)
    s._arechu = None
    assert "荒れ注意のレース" in s.arechu_top(sitegen.Page("index.html"))
    race["racelist"]["boats"][0]["class"] = "B1"
    assert s.arechu_block(race) == ""
