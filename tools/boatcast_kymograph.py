"""Space-time measurement of exhibition frames (private work area only; nothing here is published).

  # 1 frames -> space-time image (numbers only) and a PNG a person can look at
  python -m tools.boatcast_kymograph build --manifest PRIVATE/manifest.json --band 250,330 --output PRIVATE/pass.npz --png PRIVATE/pass.png
  # 2 automatic timing of every boat that passes both gates
  python -m tools.boatcast_kymograph measure --dump PRIVATE/pass.npz --gates 357,73 --direction -1 --output PRIVATE/pass.json
  # 2b speed of the streak instead of its edge (use where wake or water patterns cross the streak)
  python -m tools.boatcast_kymograph speed --dump PRIVATE/pass.npz --gates 370,270 --direction -1 --speeds 120,260 --window 267.7,270.3
  # 3 when the automatic edge fails: click the front edge on the PNG and time it from the clicks
  python -m tools.boatcast_kymograph assisted --clicks PRIVATE/clicks.json --gates 357,73 --direction -1

The manifest lists frames as {"file", "mediaTime"} or {"file", "frame": {"mediaTime"}}; rows marked
"measurable": false are skipped. All frames must have one resolution: a stream that fell back to another
quality stops the build. clicks.json is {"clicks": [[media_time, x], ...]} read off the PNG, where the
row index maps to the time listed in the dump.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from scraper import kymograph as ky

ROOT = Path(__file__).resolve().parents[1]


def private(path):
    path = Path(path).resolve()
    if path.is_relative_to(ROOT / "site"):
        raise SystemExit("keep exhibition frames and measurements outside site/")
    return path


def load_frames(manifest_path):
    manifest_path = private(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    frames, seen = [], set()
    for row in manifest.get("frames") or []:
        t = row.get("mediaTime", (row.get("frame") or {}).get("mediaTime"))
        if row.get("measurable") is False or not ky.is_finite(t) or t in seen:
            continue                                        # the same displayed frame counts once
        seen.add(t)
        with Image.open(manifest_path.parent / Path(row["file"]).name) as im:
            frames.append((float(t), np.asarray(im.convert("L"))))
    if len(frames) < 10:
        raise SystemExit("fewer than ten usable frames")
    return frames


def build(manifest, band, x_range=None):
    frames = load_frames(manifest)
    sizes = {f.shape for _, f in frames}
    if len(sizes) != 1:
        raise SystemExit(f"frame_resolution_changed: {sorted(sizes)}")
    sample = [f for _, f in frames[:: max(1, len(frames) // 60)]]
    background = np.median(np.stack(sample), axis=0).astype(np.uint8)
    out = {}
    for name, guard in (("image", False), ("image_guard", True)):
        times, image = ky.build(frames, band, background, spray_guard=guard)
        out[name] = image[:, x_range[0]:x_range[1]] if x_range else image
    out.update(times=times, band=np.array(band), x_offset=np.array(x_range[0] if x_range else 0),
               resolution=np.array(frames[0][1].shape[::-1]))
    return out


def measure(dump, gates, direction):
    offset = int(dump["x_offset"])
    shifted = tuple(g - offset for g in gates)
    result = {}
    for name in ("image", "image_guard"):
        boats = ky.measure(dump["times"], dump[name], shifted, direction)
        result[name] = boats
    return {"gates": list(gates), "direction": direction, "resolution": dump["resolution"].tolist(),
            "frames": int(len(dump["times"])), **result}


def speed(dump, gates, direction, speed_range, window=None, columns=None, accelerations=(0.0,)):
    offset = int(dump["x_offset"])
    trial = list(np.arange(speed_range[0], speed_range[1] + .01, 2.0))
    out = {"gates": list(gates), "direction": direction, "resolution": dump["resolution"].tolist()}
    for name in ("image", "image_guard"):
        out[name] = ky.measure_speed(dump["times"], dump[name], tuple(g - offset for g in gates), direction, trial,
                                     window=window, accelerations=accelerations,
                                     columns=(columns[0] - offset, columns[1] - offset) if columns else None)
        if "position" in out[name]:
            out[name]["position"] += offset
    return out


def pair(text, kind=float):
    a, b = text.split(",")
    return kind(a), kind(b)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build")
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--band", required=True, help="top,bottom rows the boats travel in")
    p.add_argument("--x-range", help="left,right columns to keep")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--png", type=Path)
    for name in ("measure", "assisted", "speed"):
        p = sub.add_parser(name)
        p.add_argument("--clicks" if name == "assisted" else "--dump", required=True, type=Path)
        if name == "speed":
            p.add_argument("--speeds", required=True, help="lowest,highest trial speed in pixels per second")
            p.add_argument("--window", help="start,end media time of one boat's pass")
            p.add_argument("--columns", help="left,right frame columns to use")
            p.add_argument("--accelerations", default="0", help="comma separated trial accelerations (px/s^2)")
        p.add_argument("--gates", required=True, help="first,second gate positions in frame pixels")
        p.add_argument("--direction", required=True, type=int, choices=(-1, 1))
        p.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        dump = build(args.manifest, pair(args.band, int), pair(args.x_range, int) if args.x_range else None)
        np.savez_compressed(private(args.output), **dump)
        if args.png:
            private(args.png).write_bytes(ky.to_png_bytes(dump["image_guard"]))
        print(json.dumps({"frames": int(len(dump["times"])), "resolution": dump["resolution"].tolist()}))
        return
    gates = pair(args.gates)
    if args.command == "measure":
        result = measure(np.load(private(args.dump)), gates, args.direction)
    elif args.command == "speed":
        result = speed(np.load(private(args.dump)), gates, args.direction, pair(args.speeds),
                       pair(args.window) if args.window else None, pair(args.columns, int) if args.columns else None,
                       tuple(float(a) for a in args.accelerations.split(",")))
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            private(args.output).write_text(text + "\n", encoding="utf-8")
        print(text)
        return
    else:
        clicks = json.loads(private(args.clicks).read_text(encoding="utf-8-sig"))["clicks"]
        result = ky.assisted(None, [tuple(c) for c in clicks], gates, args.direction)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        private(args.output).write_text(text + "\n", encoding="utf-8")
    print(text if args.command == "assisted" else json.dumps(
        {name: [(b["status"], b.get("seconds"), b["reasons"]) for b in result[name]] for name in ("image", "image_guard")},
        ensure_ascii=False))


if __name__ == "__main__":
    main()
