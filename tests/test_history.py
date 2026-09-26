import base64
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json
import numpy as np
from scraper import bfile, kfile, model, predict as P, parse  # noqa: E402
from scraper.lzh import unlzh  # noqa: E402
import fixtures as fx  # noqa: E402

HERE = Path(__file__).parent


def _hash(b):
    h = 0
    for x in b:
        h = (h * 31 + x) & 0xFFFFFFFF
    return h


def test_unlzh_matches_reference():
    # 公式 k260924.lzh の先頭 2600 バイト。ブラウザ側の展開結果とハッシュ一致を確認済み
    data = base64.b64decode((HERE / "k_prefix.b64").read_text())
    out = unlzh(data, limit=8000)
    assert _hash(out[:4000]) == 161413395
    assert _hash(out[:8000]) == 4223226689


def test_parse_k_real():
    data = base64.b64decode((HERE / "k_prefix.b64").read_text())
    text = unlzh(data, limit=8000).decode("cp932", errors="replace")
    races = kfile.parse_k(text)
    r1, r2 = races[0], races[1]
    assert (r1["jcd"], r1["date"], r1["rno"]) == ("22", "20260924", 1)
    assert r1["kimarite"] == "逃げ" and r1["wind_dir"] == "北" and r1["wind_speed"] == 2 and r1["wave"] == 2
    e = r1["entries"][0]
    assert e == {"place": 1, "code": "", "frame": 1, "toban": "4607", "name": "鶴 田 勇 雄", "course": 1, "st": 0.15, "st_flag": "",
                 "exhibit_time": 6.87}
    assert (r1["trifecta"], r1["trifecta_payout"], r1["trifecta_ninki"]) == ("1-3-5", 2550, 9)
    assert r2["kimarite"] == "まくり"
    win = next(x for x in r2["entries"] if x["place"] == 1)
    assert win["frame"] == 5 and win["course"] == 4


def test_parse_k_odd_lines():
    text = """01KBGN
   第 3日          2026/ 9/24                             ボートレース桐　生
   5R       予選　　　　       進入固定       H1800m  雨　  風  無風　 0m  波　  0cm
  着 艇 登番 　選　手　名　　ﾓｰﾀｰ ﾎﾞｰﾄ 展示 進入 ｽﾀｰﾄﾀｲﾐﾝｸ ﾚｰｽﾀｲﾑ 差し　　　
-------------------------------------------------------------------------------
  01  2 4000 山　田　　太　郎 17  106  6.87   2    0.15     1.50.8
  02  1 4001 山　田　　次　郎 17  106  6.87   1    0.12     1.51.8
  03  3 4002 山　田　　三　郎 17  106  6.87   3    0.15     1.52.8
  S1  6 4941 孫　崎　　百　世 14   18  6.74   6    0.24      .  . 
  F   4 4003 山　田　　四　郎 17  106  6.87   4   F0.01      .  . 
  K0  5 4351 里　岡　　右　貴 36   21 K .         K .        .  . 
"""
    r = kfile.parse_k(text)[0]
    assert r["fixed"] and r["wind_dir"] == "無風" and r["kimarite"] == "差し"
    f = r["entries"][4]
    assert f["code"] == "F" and f["st_flag"] == "F" and f["st"] == 0.01 and f["course"] == 4
    k = r["entries"][5]
    assert k["code"] == "K0" and k["course"] is None


def test_parse_b_real():
    text = """22BBGN
　１Ｒ  カタメン１予          Ｈ１８００ｍ  電話投票締切予定１１：４６ 
-------------------------------------------------------------------------------
1 4607鶴田勇雄37福岡52A2 5.73 39.06 5.43 37.84 17 26.12106 24.78 4622        12
5 5276大島隆乃24福岡52B1 4.90 25.00 4.68 22.58 22 33.56108 32.74 1 56         8
"""
    b = bfile.parse_b(text)
    assert b[("22", 1, 1)] == ["A2", 5.73, 39.06, 5.43, 37.84, 26.12, 24.78, 37, 52]
    assert b[("22", 1, 5)][0] == "B1" and b[("22", 1, 5)][5] == 33.56


def _rec(date, k, order, tob, B=None):
    E = []
    for place, c in enumerate(order, 1):
        E.append([c, tob[c - 1], c, 15, "", place, 680, B or ["B1", 5.0, 30, 5.0, 30, 30.0, 30.0, 30, 52]])
    return [date, "01", 1, k, "北", 2, 2, 0, "-".join(map(str, order[:3])), 1000, 5, E]


def test_stats_roundtrip_and_features():
    rng = random.Random(1)
    S = model.Stats()
    for i in range(300):
        tob = ["1111" if i % 2 == 0 else "9001", "2001", "3333" if i % 2 == 0 else "8001", "4001", "5001", "6001"]
        if i % 2 == 0 and rng.random() < 0.45:
            r = _rec("20260101", "まくり", [3, 1, 2, 4, 5, 6], tob)
        else:
            r = _rec("20260101", "逃げ", [1, 2, 3, 4, 5, 6], tob)
        S.apply(r)
    S2 = model.Stats.from_json(json.loads(json.dumps(S.to_json())))
    boats = [{"frame": f, "toban": t, "course": f, "ex": 680, "cls": "B1", "nat": 5, "loc": 5, "motor": 30, "boat": 30, "f_recent": 0}
             for f, t in enumerate(["1111", "2001", "3333", "4001", "5001", "6001"], 1)]
    X1 = model.features(S, "01", 3, 2, boats)
    X2 = model.features(S2, "01", 3, 2, boats)
    assert np.allclose(X1, X2)
    fi = model.FEATS.index
    # 捲られやすいイン × 捲り屋の3コース → mu がプラス、インの rc_win はマイナス
    assert X1[2, fi("mu")] > 0.3 and X1[0, fi("rc_win")] < 0
    # 逆にした時は小さい
    boats[0]["toban"], boats[2]["toban"] = "9001", "8001"
    assert model.features(S, "01", 3, 2, boats)[2, fi("mu")] < X1[2, fi("mu")]


def test_predict_uses_learned_model():
    rl = parse.parse_racelist(fx.racelist_html())
    p = P.predict("01", rl, None)
    assert p["model"]["races"] > 100000
    calm = {"boats": [], "start_exhibition": [], "weather": {"wind_dir": 13, "wind_speed": 0, "wave_cm": 1}}
    storm = {"boats": [], "start_exhibition": [], "weather": {"wind_dir": 13, "wind_speed": 8, "wave_cm": 12}}
    # 学習結果：風・波が強いほど1コースは不利
    assert P.predict("02", rl, storm)["boats"][0]["p_win"] < P.predict("02", rl, calm)["boats"][0]["p_win"]


def test_odds_parse_order_and_value():
    from scraper import odds as O
    cells = "".join(f'<td class="oddsPoint">{i}</td>' for i in range(120))
    v = O.parse_odds3t(cells)
    # 公式の並びは 列=1着艇。1-2-3 は1マス目、2-1-3 は2マス目、1-2-4 は7マス目
    assert v[O.COMBOS.index("1-2-3")] == 0 and v[O.COMBOS.index("2-1-3")] == 1 and v[O.COMBOS.index("1-2-4")] == 6
    odds = [10.0] * 120
    model = {k: (0.2 if k == "1-2-3" else 0.8 / 119) for k in O.COMBOS}
    res = O.value_bets(model, odds, {"market": 1.0, "model": 1.0, "ev_min": 1.0, "max_odds": 200})
    assert [b["combo"] for b in res["bets"]] == ["1-2-3"] and not res["skip"]


def test_oddstf():
    from scraper import odds as O
    html = "".join(f'<td class="oddsPoint">{o}</td>' for o in ("2.7", "2.9", "2.0", "16.6", "17.5", "31.8", "1.5-2.0"))
    assert O.parse_oddstf(html) == [2.7, 2.9, 2.0, 16.6, 17.5, 31.8]


def test_odds2t_order():
    from scraper import odds as O
    ex = O.parse_odds2t("".join(f'<td class="oddsPoint">{i}</td>' for i in range(45)))
    assert ex["1-2"] == 0 and ex["2-1"] == 1 and ex["6-1"] == 5 and ex["1-3"] == 6 and ex["6-5"] == 29


def test_recommend_composite_and_gachi():
    from scraper import odds as O
    p3 = [0.0] * 120
    for k, v in {"1-2-3": 0.2, "1-2-4": 0.1, "1-3-2": 0.08, "2-1-3": 0.05}.items():
        p3[O.COMBOS.index(k)] = v
    odds = [100.0] * 120
    odds[O.COMBOS.index("1-2-3")] = 12.0
    odds[O.COMBOS.index("1-2-4")] = 20.0
    odds[O.COMBOS.index("1-3-2")] = 25.0
    odds[O.COMBOS.index("2-1-3")] = 40.0
    r = O.recommend(p3, odds, {"max_over_market": None})
    assert r["comp"] >= 5.0 and [b["combo"] for b in r["bets"]][:2] == ["1-2-3", "1-2-4"]
    total = sum(r["alloc"].values())
    assert r["verdict"] in ("推奨", "自信あり") and r["alloc_min_return"] / total >= 0.95 * r["comp"]
    odds[O.COMBOS.index("1-2-3")] = 2.8   # 本命がガチガチ
    assert O.recommend(p3, odds)["verdict"] == "購入非推奨"


def test_recommend_skips_overrated_longshots():
    # 桐生2Rの実例：AIが市場の8倍に見ていた 1-2-5（151倍）を合成オッズの穴埋めに使わない
    from scraper import odds as O
    p3 = [0.001] * 120
    odds = [200.0] * 120
    for k, (p, o) in {"1-2-3": (0.135, 8.9), "1-2-4": (0.093, 13.4), "1-3-2": (0.092, 11.5), "1-2-5": (0.041, 151.4)}.items():
        p3[O.COMBOS.index(k)], odds[O.COMBOS.index(k)] = p, o
    r = O.recommend(p3, odds)
    assert [b["combo"] for b in r["bets"]] == ["1-2-3", "1-2-4"] and r["comp"] >= 5.0
    assert "1-2-5" in [b["combo"] for b in O.recommend(p3, odds, {"max_over_market": None})["bets"]]


def test_allocate_equalizes_payout():
    from scraper import odds as O
    odds = [14.1, 24.8, 21.0, 28.5, 212.3]
    alloc, mn = O.allocate(odds, list("abcde"))
    total = sum(alloc.values())
    comp = 1 / sum(1 / o for o in odds)
    assert abs(comp - 5.03) < 0.01 and mn / total >= 0.97 * comp


def test_parse_oriten():
    from scraper import parse
    t = "data=\n1\t3\n一　周\tまわり足\t直　線\n1\t寺田　　千恵\t36.35\t7.75\t7.63\n2\t石村　日奈那\t37.64\t8.07\t7.63\n"
    o = parse.parse_oriten(t)
    assert o["items"] == ["一周", "まわり足", "直線"] and o["rows"]["1"] == [36.35, 7.75, 7.63]
    assert parse.parse_oriten("data=\n1\t2\n半周\tまわり足\n1\tA\t0.00\t0.00\n") is None
