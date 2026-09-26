"""VMAP 1.0 manifest with inline VAST 3.0 linear ads. Pure functions, no I/O."""

import math
import xml.etree.ElementTree as ET

from adlyser.errors import EmitError
from adlyser.schemas import AdBreakSpec

VMAP_NS = "http://www.iab.net/videosuite/vmap"
AD_SYSTEM = "ADlyser"
ET.register_namespace("vmap", VMAP_NS)


def format_offset(seconds: float) -> str:
    """Format seconds as ``hh:mm:ss.mmm`` (the only place time is formatted for manifests).

    :param seconds: non-negative finite time in seconds.
    :return: e.g. ``00:04:27.000``.
    :raises EmitError: if ``seconds`` is negative or not finite.
    """
    if not math.isfinite(seconds) or seconds < 0:
        raise EmitError(f"invalid time for manifest: {seconds!r}")
    total_ms = round(seconds * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def _vast(spec: AdBreakSpec) -> ET.Element:
    """Build the inline VAST 3.0 document for one break."""
    creative = spec.creative
    vast = ET.Element("VAST", version="3.0")
    inline = ET.SubElement(ET.SubElement(vast, "Ad", id=creative.ad_id), "InLine")
    ET.SubElement(inline, "AdSystem").text = AD_SYSTEM
    ET.SubElement(inline, "AdTitle").text = creative.title
    ET.SubElement(inline, "Impression").text = ""
    linear = ET.SubElement(ET.SubElement(ET.SubElement(inline, "Creatives"), "Creative"), "Linear")
    ET.SubElement(linear, "Duration").text = format_offset(creative.duration_s)
    media = ET.SubElement(
        ET.SubElement(linear, "MediaFiles"),
        "MediaFile",
        delivery="progressive",
        type=creative.mime_type,
        width=str(creative.width),
        height=str(creative.height),
    )
    media.text = creative.media_url
    return vast


def build_vmap(breaks: list[AdBreakSpec]) -> str:
    """Build a VMAP 1.0 document, breaks in ascending time order.

    :param breaks: the breaks to include, in any order.
    :return: the XML document as a string.
    :raises EmitError: on a negative time, a duplicate break id, or two breaks at the same offset.
    """
    root = ET.Element(f"{{{VMAP_NS}}}VMAP", version="1.0")
    seen_ids: set[str] = set()
    seen_offsets: set[str] = set()
    for spec in sorted(breaks, key=lambda b: b.time_s):
        offset = format_offset(spec.time_s)
        if spec.break_id in seen_ids or offset in seen_offsets:
            raise EmitError(f"duplicate break: {spec.break_id} at {offset}")
        seen_ids.add(spec.break_id)
        seen_offsets.add(offset)
        ad_break = ET.SubElement(
            root, f"{{{VMAP_NS}}}AdBreak", timeOffset=offset, breakType="linear", breakId=spec.break_id
        )
        source = ET.SubElement(
            ad_break,
            f"{{{VMAP_NS}}}AdSource",
            id=spec.creative.ad_id,
            allowMultipleAds="false",
            followRedirects="true",
        )
        ET.SubElement(source, f"{{{VMAP_NS}}}VASTAdData").append(_vast(spec))
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
