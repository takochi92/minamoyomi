"""Read-only audit of already saved race labels; never rebuild predictions."""
from collections import Counter
import json
from pathlib import Path


def run(root=Path(__file__).resolve().parents[1]):
    out = {}
    for day in ("20261008", "20261009"):
        stats = Counter()
        examples = []
        for path in sorted((root / "site" / "data" / "races" / day).glob("*.json")):
            race = json.loads(path.read_text(encoding="utf-8"))
            result = race.get("result") or {}
            if not result.get("finished"):
                continue
            stats["finished"] += 1
            payout = result.get("trifecta_payout") or 0
            stats["over_10k"] += payout >= 10000
            stats["over_20k"] += payout >= 20000
            hard = bool((race.get("prediction") or {}).get("honmei_pick"))
            stats["labeled_hard"] += hard
            stats["hard_over_10k"] += hard and payout >= 10000
            if hard and payout >= 10000:
                examples.append({"jcd": race["jcd"], "rno": race["rno"],
                                 "result": result.get("trifecta"), "payout": payout})
        out[day] = {"counts": dict(stats), "hard_over_10k_examples": examples}
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
