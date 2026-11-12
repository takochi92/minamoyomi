"""Stage a separate BOATCAST capture tool that records the video pixel rectangle."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile

from tools.measure_exhibition import private


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("unsupported_boatcast_capture_version")
    return source.replace(old, new, 1)


def prepare(source, output):
    source = source.resolve()
    output = private(output)
    if output.exists() or output.is_relative_to(source):
        raise ValueError("capture_copy_requires_new_output_directory")
    player = (source / "player.mjs").read_text(encoding="utf-8")
    capture = (source / "capture.mjs").read_text(encoding="utf-8")
    args = (source / "args.mjs").read_text(encoding="utf-8")
    player = "import { readVideoLayout } from './boatcast_video_layout.mjs';\n" + player
    player = replace_once(player, "    const png = await cdp.screenshot();",
                          "    const layoutBefore = await readVideoLayout(cdp);\n"
                          "    const png = await cdp.screenshot();\n"
                          "    const layoutAfter = await readVideoLayout(cdp);")
    player = replace_once(player, "      png, requested:", "      png, layoutBefore, layoutAfter, requested:")
    needle = "import { judgeFrame, markDuplicates, sha256 } from './frames.mjs';"
    capture = replace_once(capture, needle, needle + "\nimport { stableVideoLayout } from './boatcast_video_layout.mjs';")
    capture = replace_once(capture, "bytes: shot.png.length, screenshot: size,",
                           "bytes: shot.png.length, screenshot: size,\n"
                           "        videoLayout: stableVideoLayout(shot.layoutBefore, shot.layoutAfter, size, shot.frame),")
    args = replace_once(args, "splitList(env.BOATCAST_CHROME_ARGS ?? '')",
                        "String(env.BOATCAST_CHROME_ARGS ?? '').split(/\\s+/).filter(Boolean)")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="boatcast-layout-", dir=output.parent) as directory:
        staged = Path(directory) / "capture"
        staged.mkdir()
        for name in ("cdp.mjs", "chrome.mjs", "failures.mjs", "frames.mjs", "player-url.mjs",
                     "redact.mjs", "stadium-candidates.mjs", "util.mjs"):
            shutil.copyfile(source / name, staged / name)
        stadiums = source / "stadiums.json"
        if stadiums.is_file():
            shutil.copyfile(stadiums, staged / stadiums.name)
        helper = Path(__file__).with_name("boatcast_video_layout.mjs")
        shutil.copyfile(helper, staged / helper.name)
        for name, contents in (("player.mjs", player), ("capture.mjs", capture), ("args.mjs", args)):
            (staged / name).write_text(contents, encoding="utf-8", newline="\n")
        staged.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.source, args.output)


if __name__ == "__main__":
    main()
