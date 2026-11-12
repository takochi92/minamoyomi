"""Use the local turn review page to record continuous bow tracks for six boats."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scraper.exhibition_segments import finite, frame_loader, point, profile_geometry, race_identity, usable_frames
from scraper.turn_measurement import digest
from tools.measure_exhibition import manifest_at, private, read, write


ASSETS = Path(__file__).with_name("turn_review")
METHOD = "heiwajima-bow-gates-v2"
BOATS = {str(i) for i in range(1, 7)}


def review_metadata(manifest, profile, setup):
    path, data, sha = manifest_at(manifest)
    config, settings = read(profile), read(setup)
    size, gates, _ = profile_geometry(config)
    day, venue, race = race_identity(data)
    if config["venue"] != venue:
        raise ValueError("profile_venue_mismatch")
    windows = settings["windows"]
    if set(windows) != BOATS:
        raise ValueError("six_boat_windows_required")
    frames = usable_frames(data)
    ordered = sorted(frames.items(), key=lambda entry: entry[1]["time"])
    clips = []
    for boat, limits in sorted(windows.items()):
        if (not isinstance(limits, list) or len(limits) != 2 or not all(finite(v) for v in limits)
                or not 0 <= limits[0] < limits[1] <= limits[0] + 25):
            raise ValueError("invalid_boat_window")
        rows = [{"index": index, "file": name, "time": frame["time"]}
                for index, (name, frame) in enumerate(ordered) if limits[0] <= frame["time"] <= limits[1]]
        if len(rows) < 5:
            raise ValueError("too_few_frames_in_boat_window")
        clips.append({"boat": int(boat), "frames": rows})
    evidence = {"method": METHOD, "segments_only": True, "size": size, "gates": gates, "clips": clips,
                "events": [], "source_clock": "browser_media_time", "manifest_sha256": sha,
                "profile_sha256": digest(config), "setup_sha256": digest(settings),
                "race": {"date": day, "venue": venue, "race": race}}
    return path, frames, config, settings, {**evidence, "digest": digest(evidence)}


def build(manifest, profile, setup, output):
    path, frames, config, _, bundle = review_metadata(manifest, profile, setup)
    output = private(output)
    if output.exists():
        raise ValueError("review_page_requires_new_directory")
    output.mkdir(parents=True)
    mode = config.get("coordinate_space", "screenshot")
    load = frame_loader(path.parent, bundle["size"], frames, image_mode="RGB", coordinate_space=mode)
    bundle["images"] = {}
    for clip in bundle["clips"]:
        for row in clip["frames"]:
            index, name = row["index"], row["file"]
            if index in bundle["images"]:
                continue
            image = load(name)
            if mode == "video":
                dst = output / f"frame-{index}.png"
                image.save(dst)
                bundle["images"][index] = dst.name
            else:
                bundle["images"][index] = (path.parent / name).as_uri()
    payload = json.dumps(bundle, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    race = bundle["race"]
    page = (ASSETS / "review.html").read_text(encoding="utf-8")
    page = page.replace("平和島 __RACE_LABEL__", f"場 {race['venue']}・{race['date']}・{race['race']}R")
    page = page.replace("艇首・艇尾を指定して、追跡点のずれを確認する画面です。", "各艇の艇首をコマごとに記録する画面です。")
    page = page.replace("水色：艇首と艇尾の中点　黄・緑・青：全艇共通の固定線", "水色は艇首の記録点。固定線は艇間で共通です。")
    page = page.replace("各線の通過前後で艇首・艇尾を指定すると参考計算します。画面記録の未校正時刻による値で、実走タイム・本番掲載値ではありません。",
                        "艇首が見えないコマは、判別できないとして記録してください。")
    page = page.replace("①艇と線を選ぶ ②線を越える前後のコマを探す ③艇首と艇尾をクリック・タップ ④通過前／後を指定。追跡点の表示は初期状態で隠し、元の枠に引きずられず確認します。コマの幅・隠れ・線の位置は後段でも検査します。",
                        "艇を選び、艇首をクリックします。次のコマに自動で進みます。見えないコマは専用ボタンで飛ばせます。")
    page = page.replace('<h2>スマホでの掲載枠</h2><p class="legend">現在の状態を反映した見本。計測値は捏造せず空欄にしています。</p><div class="mobile">__PANEL__</div>', "")
    page = page.replace("__CSS__", (ASSETS / "review.css").read_text(encoding="utf-8"))
    page = page.replace("__BUNDLE__", payload).replace("__JS__", (ASSETS / "review.js").read_text(encoding="utf-8"))
    (output / "index.html").write_text(page.replace("__PANEL__", ""), encoding="utf-8")
    return bundle


def import_draft(manifest, profile, setup, draft):
    _, frames, _, settings, bundle = review_metadata(manifest, profile, setup)
    value = read(draft)
    if (value.get("kind") != "turn-review-draft-v1" or value.get("method") != METHOD
            or value.get("bundle_digest") != bundle["digest"] or value.get("trajectory_checked") is not True
            or not isinstance(value.get("reviewer"), str) or not value["reviewer"].strip()):
        raise ValueError("unbound_or_unreviewed_bow_draft")
    labels = value["labels"]
    keys = {f"{clip['boat']}:{row['index']}" for clip in bundle["clips"] for row in clip["frames"]}
    if (not isinstance(labels, dict) or not set(labels) <= keys
            or any(not isinstance(v, dict) or set(v) != {"bow"}
                   or (v["bow"] is not None and not point(v["bow"], bundle["size"])) for v in labels.values())):
        raise ValueError("invalid_bow_draft_labels")
    boats = {str(clip["boat"]): [{"file": row["file"],
              "bow": labels.get(f"{clip['boat']}:{row['index']}", {}).get("bow")}
             for row in clip["frames"]] for clip in bundle["clips"]}
    evidence_frames = (settings["camera_reference"], settings["lap_evidence"]["file"])
    if any(name not in frames for name in evidence_frames):
        raise ValueError("camera_or_lap_frame_not_available")
    times = [frames[name]["time"] for name in evidence_frames]
    times.extend(t for window in settings["windows"].values() for t in window)
    return {"schema": 1, "manifest_sha256": bundle["manifest_sha256"], "profile_sha256": bundle["profile_sha256"],
            "window": [min(times), max(times)],
            "boats": boats, "reviewer": value["reviewer"].strip(), "camera_reference": settings["camera_reference"],
            "camera_layout_reviewed": settings["camera_layout_reviewed"], "lap_evidence": settings["lap_evidence"],
            "identity": settings["identity"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "import"))
    for name in ("manifest", "profile", "setup", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--draft", type=Path)
    args = parser.parse_args()
    if args.mode == "build":
        build(args.manifest, args.profile, args.setup, args.output)
    else:
        if args.draft is None or args.output.exists():
            parser.error("import requires a draft and a new output file")
        write(args.output, import_draft(args.manifest, args.profile, args.setup, args.draft))


if __name__ == "__main__":
    main()
