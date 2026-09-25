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
    assert sm.count("<url>") == len([p for p in files if p.endswith(".html")])
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
