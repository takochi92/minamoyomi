import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402
from scraper import parse, predict as P, run  # noqa: E402


def test_index():
    v = parse.parse_index(fx.INDEX)
    assert [x["jcd"] for x in v] == ["01", "11"]
    assert v[0]["grade"] == "一般" and v[0]["timezone"] == "ナイター" and "最終日" in v[0]["day"]
    assert v[1]["grade"] == "G3"


def test_racelist():
    r = parse.parse_racelist(fx.racelist_html())
    assert r["deadlines"][1] == "15:21" and r["deadlines"][12] == "20:35"
    assert r["race_name"] == "一般 1800m"
    b = r["boats"]
    assert len(b) == 6 and b[0]["frame"] == 1 and b[5]["frame"] == 6
    assert b[0]["class"] == "A1" and b[0]["f"] == 1 and b[0]["avg_st"] == 0.18
    assert b[0]["nat_win"] == 6.1 and b[0]["motor_2"] == 31.0 and b[0]["weight"] == 53.0
    assert b[0]["name"] == "山下 流心" and b[0]["branch"] == "広島/広島"


def test_beforeinfo():
    bi = parse.parse_beforeinfo(fx.beforeinfo_html())
    assert bi["exhibition_done"]
    assert [b["exhibit_time"] for b in bi["boats"]] == [6.83, 6.71, 6.88, 6.89, 6.66, 6.81]
    assert bi["boats"][2]["propeller"] == "新" and bi["boats"][5]["parts"] == ["ピストン"]
    assert bi["boats"][3]["adjust_weight"] == 1.0
    st = bi["start_exhibition"]
    assert [s["frame"] for s in st] == [1, 2, 3, 5, 6, 4]
    assert st[0]["st"] == -0.08 and st[0]["flag"] == "F" and st[5]["st"] == 0.05
    w = bi["weather"]
    assert w == {"as_of": "14:55", "air_temp": 24.0, "weather": "曇り", "wind_speed": 4.0,
                 "water_temp": 23.0, "wave_cm": 3.0, "wind_dir": 10}


def test_beforeinfo_not_yet():
    bi = parse.parse_beforeinfo(fx.beforeinfo_html(exhibited=False))
    assert not bi["exhibition_done"] and bi["start_exhibition"] == []


def test_result():
    r = parse.parse_result(fx.RESULT)
    assert r["trifecta"] == "1-5-4" and r["trifecta_payout"] == 5060
    assert r["exacta"] == "1-5" and r["exacta_payout"] == 1230 and r["kimarite"] == "逃げ"
    assert r["win"] == 1 and r["win_payout"] == 150


def test_wind():
    assert P.wind_info(5, 4)["type"] == "追い風"
    assert P.wind_info(13, 4)["type"] == "向かい風"
    assert P.wind_info(1, 4)["type"] == "横風"
    assert P.wind_info(9, 0)["type"] == "無風"


def test_predict():
    rl = parse.parse_racelist(fx.racelist_html())
    bi = parse.parse_beforeinfo(fx.beforeinfo_html())
    p = P.predict("01", rl, bi)
    assert p["stage"] == "直前" and p["entry"] == [1, 2, 3, 5, 6, 4] and p["entry_changed"]
    assert abs(sum(b["p_win"] for b in p["boats"]) - 1) < 1e-3
    assert abs(sum(b["p_top3"] for b in p["boats"]) - 3) < 1e-2
    assert 3 <= len(p["bets"]["main"]) <= 6 and len(p["bets"]["sub"]) == 4
    assert len({b["combo"] for b in p["bets"]["main"] + p["bets"]["sub"]}) == p["points"]
    # 1号艇は A1・全国勝率トップ・イン → 最有力
    assert max(p["boats"], key=lambda b: b["p_win"])["frame"] == 1
    json.dumps(p, ensure_ascii=False)
    pre = P.predict("01", rl, None)
    assert pre["stage"] == "事前" and pre["entry"] == [1, 2, 3, 4, 5, 6]


class FakeFetcher:
    def __init__(self, finished=True):
        self.count = 0
        self.exhausted = False
        self.finished = finished

    def index(self, hd):
        self.count += 1
        return fx.INDEX

    def racelist(self, jcd, rno, hd):
        self.count += 1
        return fx.racelist_html()

    def beforeinfo(self, jcd, rno, hd):
        self.count += 1
        return fx.beforeinfo_html()

    def odds3t(self, jcd, rno, hd):
        self.count += 1
        # 1着が1号艇の目は安く、それ以外は高い架空オッズ（公式の並び：列=1着艇）
        cells = []
        for row in range(20):
            for col in range(6):
                o = 8.0 + row * 2 if col == 0 else 150.0 + row * 10
                cells.append(f'<td class="oddsPoint">{o:.1f}</td>')
        return "<table>" + "".join(cells) + "</table>"

    def odds2tf(self, jcd, rno, hd):
        self.count += 1
        return "".join(f'<td class="oddsPoint">{5.0 + i}</td>' for i in range(45))

    def oddstf(self, jcd, rno, hd):
        self.count += 1
        return "".join(f'<td class="oddsPoint">{o}</td>' for o in ("1.8", "4.5", "6.0", "12.0", "25.0", "40.0", "1.0-1.2"))

    def result(self, jcd, rno, hd):
        self.count += 1
        return fx.RESULT if self.finished else "<main></main>"


def test_run_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "DATA", tmp_path)
    fake = FakeFetcher()
    monkeypatch.setattr(run, "Fetcher", lambda max_requests: fake)
    # 1R 締切 15:21 の 7 分前：直前予想が出る
    run.main(["--now", "2026-09-25T15:14"])
    idx = json.loads((tmp_path / "index.json").read_text())
    r1 = idx["venues"][0]["races"][0]
    assert r1["stage"] == "直前" and r1["honmei"]
    race = json.loads((tmp_path / "races/20260925/0101.json").read_text())
    assert race["before_final"] and race["prediction"]["made_at"] == "15:14"
    assert race["value"]["at"] == "15:14" and "bets" in race["value"] and len(race["prediction"]["p3"]) == 120
    assert race["odds_pre"]["v"][0] == 8.0 and race["odds_pre"]["v"][20] == 150.0
    assert "verdict" in race["reco"] and race["reco"]["rule"]["min_comp"] == 5.0
    assert race["odds_pre"]["ex"]["1-2"] == 5.0 and race["odds_pre"]["ex"]["2-1"] == 6.0 and race["value"]["final"]
    # 締切 20 分後：結果取得・的中判定。予想は固定されている
    run.main(["--now", "2026-09-25T15:41"])
    race = json.loads((tmp_path / "races/20260925/0101.json").read_text())
    assert race["result"]["trifecta"] == "1-5-4" and race["hit"] is not None
    assert race["prediction"]["made_at"] == "15:14"
    if race["value"]["bets"]:
        assert "value_hit" in race and race["v_invest"] == 100 * len(race["value"]["bets"])
    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats["all"]["races"] >= 1
