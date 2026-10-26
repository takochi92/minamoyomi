"""Build a self-contained local annotation desk from the existing pilot evidence.

No remote fetches. Browser capture times are preserved as such, never PTS.
"""
from __future__ import annotations

import argparse
import base64
import io
import html
import json
import hashlib
from fractions import Fraction
from datetime import date
from pathlib import Path

from PIL import Image

from scraper.turn_measurement import digest, render_panel, METHOD, BOW_METHOD

ASSETS = Path(__file__).with_name("turn_review")
NAMES = {1: "鈴木 唯央", 2: "生方 靖亜", 3: "柳瀬 幹太", 4: "杉江 浩明", 5: "花田 凱成", 6: "一瀬 明"}


def build(frames_dir, config, tracks, report):
    if (config.get("venue"), config.get("turn")) != ("heiwajima", "1-mark"):
        raise ValueError("Heiwajima first-mark only")
    if (report.get("date"), report.get("race"), report.get("venue")) != (config["date"], config["race"], config["venue"]):
        raise ValueError("Report belongs to a different race")
    method = config.get('method', METHOD)
    if method not in (METHOD, BOW_METHOD):
        raise ValueError('Unsupported measurement method')
    frames_dir = Path(frames_dir).resolve()
    raw_manifest = json.loads((frames_dir / "frames.json").read_text(encoding="utf-8"))
    source_details = None
    if isinstance(raw_manifest, list):
        manifest = raw_manifest
        source_clock = "browser_capture_clock_unverified"
    else:
        if raw_manifest.get('schema') != 2 or raw_manifest.get('source', {}).get('clock') != 'decoded_pts':
            raise ValueError('Unsupported frame clock')
        source_details = raw_manifest['source']
        base = Fraction(*source_details['time_base'])
        if base <= 0 or raw_manifest['image_size'] != config['image_size']:
            raise ValueError('Invalid source dimensions or time base')
        manifest = []
        previous = None
        for frame in raw_manifest['frames']:
            if type(frame.get('pts')) is not int or (previous is not None and frame['pts'] <= previous):
                raise ValueError('Invalid decoded frame PTS')
            previous = frame['pts']
            manifest.append({**frame, 'before': float(frame['pts']*base), 'after': float(frame['pts']*base)})
        source_clock = 'decoded_pts'
    by_boat = {row["boat"]: {p["frame"]: p for p in row["points"]} for row in tracks}
    images = {}
    def sample(boat, index):
        frame = manifest[index]
        path = (frames_dir / frame["file"]).resolve()
        if path.parent != frames_dir:
            raise ValueError("Frame outside supplied directory")
        if index not in images:
            if source_details and hashlib.sha256(path.read_bytes()).hexdigest() != frame.get('sha256'):
                raise ValueError('Decoded frame fingerprint changed')
            with Image.open(path) as image:
                if list(image.size) != config["image_size"]:
                    raise ValueError("Frame size changed")
                buf = io.BytesIO()
                image.convert("RGB").save(buf, "WEBP", quality=78)
                images[index] = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
        result = {"index": index, "time": (frame["before"] + frame["after"]) / 2,
                  "proposal": by_boat[boat].get(index, {}).get("bbox")}
        if source_details:
            result['pts'] = frame['pts']
        return result
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
                samples.append(sample(boat, index))
            events.append({"boat": boat, "gate": gate, "frames": samples})
    evidence = {"date": config["date"], "race": config["race"], "venue": config["venue"],
                "size": config["image_size"], "gates": config["gates"], "events": events,
                "frame_manifest_digest": digest(raw_manifest),
                "image_digests": {key: digest(value) for key, value in images.items()},
                "source_clock": source_clock, "source": config["source"]}
    if source_details:
        evidence['source_details'] = source_details
    if 'method' in config:
        evidence['method'] = method
    # This exact digest identifies the previous windows-only evidence. Accept
    # its drafts only when that unchanged subset is present in this new bundle.
    legacy_digest = digest(evidence)
    clips = []
    for boat in range(1, 7):
        indices = [frame["index"] for event in events if event["boat"] == boat for frame in event["frames"]]
        frames = [sample(boat, index) for index in range(min(indices), max(indices)+1)]
        if any(not 0 < b["time"]-a["time"] <= .2 for a, b in zip(frames, frames[1:])):
            raise ValueError("Continuous replay has a missing or reversed time interval")
        clips.append({"boat": boat, "frames": frames})
    evidence = {**evidence, "clips": clips,
                "image_digests": {key: digest(value) for key, value in images.items()}}
    bundle = {**evidence, "digest": digest(evidence), "images": images,
              "compatible_digests": [legacy_digest]}
    # Deduplicate the embedded images rather than repeat them in every event.
    names = {int(k): str(v) for k, v in config.get("names", {}).items()}
    if not names and (config["date"], config["race"]) == ("2026-10-26", 1):
        names = NAMES
    panel = render_panel({"method": method, "rows": [{"boat": i, "status": "remeasure"} for i in range(1, 7)]}, names, preview=True)
    template = (ASSETS / "review.html").read_text(encoding="utf-8")
    if method == BOW_METHOD:
        template = (template.replace('艇首と艇尾', '艇首の先端').replace('艇首・艇尾', '艇首')
                    .replace('水色：艇首の先端の中点', '水色：測定する艇首の先端')
                    .replace('<button data-point="stern">艇尾を指定</button>', '<button data-point="stern" hidden>艇尾を指定</button>'))
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
