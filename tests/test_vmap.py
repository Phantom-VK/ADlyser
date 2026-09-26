import re
import xml.etree.ElementTree as ET

import pytest

from adlyser.emit.vmap import build_vmap, format_offset
from adlyser.errors import EmitError
from adlyser.schemas import AdBreakSpec, Creative

NS = {"vmap": "http://www.iab.net/videosuite/vmap"}
OFFSET = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}$")


def creative(n=1, url="https://cdn.example/ad.mp4", title="Promo", duration=10.0):
    return Creative(ad_id=f"ad-{n}", title=title, duration_s=duration, media_url=url)


def brk(n, t, **kw):
    return AdBreakSpec(break_id=f"break-{n}", time_s=t, creative=creative(n, **kw))


def parse(xml):
    return ET.fromstring(xml)


# ---- format_offset ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00.000"),
        (5.5, "00:00:05.500"),
        (267.0, "00:04:27.000"),
        (3725.25, "01:02:05.250"),
        (59.9996, "00:01:00.000"),  # rounds up across a minute boundary
        (86399.999, "23:59:59.999"),
    ],
)
def test_format_offset(seconds, expected):
    assert format_offset(seconds) == expected


@pytest.mark.parametrize("bad", [-0.001, float("nan"), float("inf")])
def test_format_offset_rejects_bad_times(bad):
    with pytest.raises(EmitError):
        format_offset(bad)


# ---- build_vmap ---------------------------------------------------------------------


def test_output_parses_and_is_a_vmap_1_0_document():
    root = parse(build_vmap([brk(1, 100)]))
    assert root.tag == "{http://www.iab.net/videosuite/vmap}VMAP"
    assert root.get("version") == "1.0"


def test_no_breaks_is_a_valid_empty_vmap():
    root = parse(build_vmap([]))
    assert root.findall("vmap:AdBreak", NS) == []


def test_time_offsets_are_hh_mm_ss_mmm_and_ascending_even_for_unsorted_input():
    root = parse(build_vmap([brk(2, 900.5), brk(1, 267), brk(3, 4000)]))
    offsets = [b.get("timeOffset") for b in root.findall("vmap:AdBreak", NS)]
    assert offsets == ["00:04:27.000", "00:15:00.500", "01:06:40.000"]
    assert all(OFFSET.match(o) for o in offsets)


def test_each_break_is_linear_with_a_unique_id():
    root = parse(build_vmap([brk(1, 100), brk(2, 200)]))
    breaks = root.findall("vmap:AdBreak", NS)
    assert {b.get("breakType") for b in breaks} == {"linear"}
    ids = [b.get("breakId") for b in breaks]
    assert ids == ["break-1", "break-2"] and len(set(ids)) == 2


def test_each_break_has_inline_vast_3_with_a_media_file():
    root = parse(build_vmap([brk(1, 100, url="https://cdn.example/a.mp4", duration=10.0)]))
    (b,) = root.findall("vmap:AdBreak", NS)
    vast = b.find("vmap:AdSource/vmap:VASTAdData/VAST", NS)
    assert vast is not None and vast.get("version") == "3.0"
    inline = vast.find("Ad/InLine")
    assert inline is not None
    assert inline.find("AdSystem").text
    assert inline.find("AdTitle").text == "Promo"
    assert inline.find("Impression") is not None
    linear = inline.find("Creatives/Creative/Linear")
    assert linear.find("Duration").text == "00:00:10.000"
    media = linear.find("MediaFiles/MediaFile")
    assert media.text.strip() == "https://cdn.example/a.mp4"
    assert media.get("type") == "video/mp4" and media.get("delivery") == "progressive"
    assert media.get("width") == "960" and media.get("height") == "540"


def test_special_characters_are_escaped_and_survive_a_round_trip():
    root = parse(build_vmap([brk(1, 100, url="https://cdn.example/a.mp4?x=1&y=2", title="Tea <& Co>")]))
    vast = root.find("vmap:AdBreak/vmap:AdSource/vmap:VASTAdData/VAST", NS)
    assert vast.find("Ad/InLine/AdTitle").text == "Tea <& Co>"
    assert (
        vast.find("Ad/InLine/Creatives/Creative/Linear/MediaFiles/MediaFile")
        .text.strip()
        .endswith("?x=1&y=2")
    )


def test_duplicate_break_ids_are_rejected():
    with pytest.raises(EmitError):
        build_vmap([brk(1, 100), AdBreakSpec(break_id="break-1", time_s=200, creative=creative(2))])


def test_two_breaks_at_the_same_offset_are_rejected():
    with pytest.raises(EmitError):
        build_vmap([brk(1, 100), brk(2, 100.0004)])


def test_negative_break_time_is_rejected():
    with pytest.raises(EmitError):
        build_vmap([brk(1, -1)])
