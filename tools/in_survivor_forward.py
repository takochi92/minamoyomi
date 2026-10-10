"""Audit a separately fixed, prospective inside-win high-payout research ticket."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from scraper.in_survivor import PARAMS, PROTOCOL, select
from scraper.research_ledger import audit, summarize
from tools.exhibition_research import source_races


def review(rows):
    excluded = Counter()
    paired, shadow = [], []
    for row in rows:
        bad = audit(row)
        d = row.get("decision") or {}
        s = d.get("in_survivor_shadow") or {}
        if s.get("protocol") != PROTOCOL or s.get("params") != PARAMS or s.get("simulation") is not True:
            bad.append("missing_or_changed_protocol")
        if not d.get("model_revision") or s.get("model_revision") != d.get("model_revision") or s.get("model_version") != d.get("model_version"):
            bad.append("fingerprint_mismatch")
        evidence = s.get("evidence") or {}
        entry = d.get("entry") or []
        if len(entry) != 6 or evidence.get("in_frame") != entry[0] or evidence.get("third_frame") != entry[2]:
            bad.append("entry_mismatch")
        expected = select(evidence, d.get("p3") or [], (row.get("odds_pre") or {}).get("v") or [])
        if not s.get("tickets"):
            bad.append("no_research_tickets")
        if s.get("tickets") != expected:
            bad.append("fixed_tickets_mismatch")
        if bad:
            excluded.update(set(bad))
            continue
        paired.append(row)
        copy = deepcopy(row)
        copy["decision"]["tickets"] = deepcopy(s["tickets"])
        shadow.append(copy)
    result = summarize(shadow)
    result["strategy"] = PROTOCOL
    return {"protocol": PROTOCOL, "params": PARAMS, "simulation": True,
            "baseline_on_same_races": summarize(paired), "shadow": result,
            "excluded_reason_counts": dict(excluded),
            "limits": ["券は締切前のオッズ・予想・選手のコース成績から固定し、後から追加しない",
                       "確定配当を使う過去診断と締切前の仮想成績を混ぜない",
                       "少数件の回収率改善や利益は保証しない"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("site/data/in_survivor_forward.json"))
    args = parser.parse_args()
    result = review(source_races())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"settled": result["shadow"]["races"]}))


if __name__ == "__main__":
    main()
