import pytest

from tools.compare_exhibition_straight import compare, validate_page_identity


def test_overlapping_video_bounds_do_not_count_as_verified_rank_reversals():
    official = [{"boat": n, "official_straight_seconds": t, "official_exhibition_seconds": 6.7}
                for n, t in enumerate((7.1, 7.2, 7.3), 1)]
    result = {"date": "20261112", "venue": "04", "race": 12, "lap": 1,
              "time_basis": "browser_presented_frame_media_time", "boats": [
                  {"boat": n, "segments": {"back_stretch": {"status": "reference",
                   "video_seconds": t, "bracket_range_video_seconds": bounds}}}
                  for n, t, bounds in [(1, 1.02, [.9, 1.15]), (2, 1, [.85, 1.1]), (3, .73, [.65, .8])]]}
    report = compare(result, official, ("20261112", "04", 12))
    assert report["comparison"]["official_straight_seconds"] == {
        "paired_boats": 3, "point_estimate_spearman": -1,
        "confirmed_same_direction": 0, "confirmed_opposite_direction": 2,
        "video_bounds_overlap": 1, "official_tie": 0,
    }
    assert report["comparison"]["official_exhibition_seconds"]["official_tie"] == 3
    assert not report["rating_ready"]


def test_official_source_must_identify_the_selected_race():
    page = ('<th><a href="/owpc/pc/race/beforeinfo?rno=11&amp;jcd=04&amp;hd=20261112">11R</a></th>'
            '<th class="is-thColor2"><a href="/owpc/pc/race/beforeinfo?rno=12&amp;jcd=04&amp;hd=20261112">12R</a></th>')
    validate_page_identity(page, "beforeinfo", ("20261112", "04", 11))
    with pytest.raises(ValueError, match="official_beforeinfo_race_mismatch"):
        validate_page_identity(page, "beforeinfo", ("20261112", "04", 12))
