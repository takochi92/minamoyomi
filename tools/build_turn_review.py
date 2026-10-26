"""Build a self-contained local annotation desk from the existing pilot evidence.

No remote fetches. Browser capture times are preserved as such, never PTS.
"""
from __future__ import annotations

import argparse
import base64
import io
import html
import json
from datetime import date
from pathlib import Path

from PIL import Image

from scraper.turn_measurement import digest, render_panel

ASSETS = Path(__file__).with_name("turn_review")
NAMES = {1: "鈴木 唯央", 2: "生方 靖亜", 3: "柳瀬 幹太", 4: "杉江 浩明", 5: "花田 凱成", 6: "一瀬 明"}


def build(frames_dir, config, tracks, report):
    if (config.get("venue"), config.get("turn")) != ("heiwajima", "1-mark"):
        raise ValueError("Heiwajima first-mark only")
    if (report.get("date"), report.get("race"), report.get("venue")) != (config["date"], config["race"], config["venue"]):
        raise ValueError("Report belongs to a different race")
    frames_dir = Path(frames_dir).resolve()
    manifest = json.loads((frames_dir / "frames.json").read_text(encoding="utf-8"))
    by_boat = {row["boat"]: {p["frame"]: p for p in row["points"]} for row in tracks}
    images = {}
    events = []
    for row in report["results"]:
        boat = row["boat"]
        for gate in "ABC":
            time = row["events"].get(gate)
            if time is None:
                raise ValueError("Pilot gate candidate missing")
            middle = min(range(len(manifest)), key=lambda i: abs((manifest[i]["before"] + manifest[i]["after"]) / 2 - time))
            samples = []
            for index in range(max(0, middle-12), min(len(manifest), middle+13)):
                frame = manifest[index]
                path = (frames_dir / frame["file"]).resolve()
                if path.parent != frames_dir:
                    raise ValueError("Frame outside supplied directory")
                if index not in images:
                    with Image.open(path) as image:
                        if list(image.size) != config["image_size"]:
                            raise ValueError("Frame size changed")
                        buf = io.BytesIO()
                        image.convert("RGB").save(buf, "WEBP", quality=78)
                        images[index] = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
                samples.append({"index": index, "time": (frame["before"] + frame["after"]) / 2,
                                "proposal": by_boat[boat].get(index, {}).get("bbox")})
            events.append({"boat": boat, "gate": gate, "frames": samples})
    evidence = {"date": config["date"], "race": config["race"], "venue": config["venue"],
                "size": config["image_size"], "gates": config["gates"], "events": events,
                "frame_manifest_digest": digest(manifest),
                "image_digests": {key: digest(value) for key, value in images.items()},
                "source_clock": "browser_capture_clock_unverified", "source": config["source"]}
    bundle = {**evidence, "digest": digest(evidence), "images": images}
    # Deduplicate the embedded images rather than repeat them in every event.
    names = {int(k): str(v) for k, v in config.get("names", {}).items()}
    if not names and (config["date"], config["race"]) == ("2026-10-26", 1):
        names = NAMES
    panel = render_panel({"rows": [{"boat": i, "status": "remeasure"} for i in range(1, 7)]}, names, preview=True)
    template = (ASSETS / "review.html").read_text(encoding="utf-8")
    payload = json.dumps(bundle, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    race_label = date.fromisoformat(config["date"]).strftime("%Y/%m/%d") + "・" + str(config["race"]) + "R"
    return (template.replace("__RACE_LABEL__", html.escape(race_label))
            .replace("__CSS__", (ASSETS / "review.css").read_text(encoding="utf-8"))
            .replace("__PANEL__", panel).replace("__BUNDLE__", payload)
            .replace("__JS__", (ASSETS / "review.js").read_text(encoding="utf-8"))), bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("frames", "config", "tracks", "report", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    page, bundle = build(args.frames, load(args.config), load(args.tracks), load(args.report))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(json.dumps({"events": len(bundle["events"]), "frames": len(bundle["images"]),
                      "bundle_digest": bundle["digest"], "publication_ready": False}))


if __name__ == "__main__":
    main()
