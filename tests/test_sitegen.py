import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402
from scraper import fan, parse, predict as P, sitegen, run  # noqa: E402


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


def test_seo_basics(tmp_path):
    _, files = _site(tmp_path)
    page = files["race/20260925/kiryu-12.html"]
    assert "<title>桐生12R 予想" in page and 'rel="canonical"' in page and "BreadcrumbList" in page
    assert "20歳未満" in page and "保証するものではありません" in page
    assert "山下 流心" in page
    sm = files["sitemap.xml"]
    assert sm.count("<url>") == len([p for p in files if p.endswith(".html") and p != "404.html" and not p.endswith("-st.html")])
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
    assert 'class="fav-btn"' in files["racer/4872.html"] and 'id="fav-today"' in files["index.html"]
