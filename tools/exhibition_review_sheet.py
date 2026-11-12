"""Build private, timestamped contact sheets for reviewing the displayed bow."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

from scraper.exhibition_segments import frame_loader, usable_frames
from tools.measure_exhibition import manifest_at, private


def build_sheets(manifest_path, output, start, end, crop, stride, scale):
    if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end:
        raise ValueError("invalid_time_window")
    if not math.isfinite(scale) or not 0 < scale <= 5 or not 1 <= stride <= 60:
        raise ValueError("invalid_sheet_scale_or_stride")
    output = private(output)
    path, manifest, _ = manifest_at(manifest_path)
    frames = usable_frames(manifest)
    names = [name for name, row in sorted(frames.items(), key=lambda item: item[1]["time"])
             if start <= row["time"] <= end][::stride]
    if not names:
        raise ValueError("no_usable_frames_in_window")
    size = next(row["screenshot"] for row in manifest["frames"] if row["file"] == names[0])
    width, height = size["width"], size["height"]
    x1, y1, x2, y2 = crop or (0, 0, width, height)
    if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
        raise ValueError("crop_outside_frame")
    tile_width = round((x2 - x1) * scale)
    tile_height = round((y2 - y1) * scale)
    if not 150 <= tile_width <= 1280 or not 50 <= tile_height <= 850:
        raise ValueError("use_crop_or_scale_to_fit_sheet")
    columns = min(4, 1600 // tile_width)
    load = frame_loader(path.parent, (width, height), frames, image_mode="RGB")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.glob("sheet-*.jpg")):
        raise ValueError("sheet_output_not_empty")      # 途中まで作ってから落ちないよう、先に確かめる
    page_size = columns * 4
    for offset in range(0, len(names), page_size):
        group = names[offset:offset + page_size]
        page = offset // page_size + 1
        row_height = tile_height + 25
        sheet = Image.new("RGB", (tile_width * columns, row_height * math.ceil(len(group) / columns)))
        labels = ImageDraw.Draw(sheet)
        for i, name in enumerate(group):
            x, y = (i % columns) * tile_width, (i // columns) * row_height
            tile = load(name).crop((x1, y1, x2, y2)).resize((tile_width, tile_height))
            sheet.paste(tile, (x, y))
            labels.text((x + 3, y + tile_height + 3), f"{frames[name]['time']:.3f}s  ({x1},{y1})")
        with (output / f"sheet-{page:03}.jpg").open("xb") as f:
            sheet.save(f, format="JPEG", quality=90)
    return len(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--crop", type=int, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--stride", type=int, default=1, choices=range(1, 61))
    parser.add_argument("--scale", type=float, default=.3)
    args = parser.parse_args()
    print(f"{build_sheets(args.manifest, args.output, args.start, args.end, args.crop, args.stride, args.scale)} frames")


if __name__ == "__main__":
    main()
