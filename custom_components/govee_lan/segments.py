"""Model-scoped static RGBIC commands carried by the LAN ptReal envelope."""

from __future__ import annotations

import base64

from .govee_scene import GoveeLanError, _finish

# govee-local-api's H60A1 profile reports 13 rear RGB segments. Do not
# include bit 13: BLE reports associate it with the front panel on some revisions.
BACKLIGHT_SEGMENT_COUNTS = {"H60A1": 13}


def backlight_scene_groups(colors: list) -> list[dict]:
    """Validate a complete 13-color scene, grouping equal colors into one mask."""
    if not isinstance(colors, list) or len(colors) != 13:
        raise GoveeLanError("A backlight scene requires exactly 13 RGB colors")
    groups = [{"segments": [i + 1], "color": color} for i, color in enumerate(colors)]
    segment_color_packets("H60A1", groups)
    by_color: dict[tuple, dict] = {}
    for group in groups:
        key = tuple(group["color"])
        if key not in by_color:
            by_color[key] = {"segments": [], "color": list(key)}
        by_color[key]["segments"].extend(group["segments"])
    return list(by_color.values())


def segment_color_packets(sku: str, groups: list[dict]) -> list[str]:
    """Encode non-overlapping groups using user-facing segment numbers 1–13.

    Layout follows Galorhallen/govee-local-api SegmentColorMessages:
    33 05 15 01 R G B 00 00 00 00 00 <mask little-endian, 2 bytes>,
    padded to 19 bytes, followed by an XOR checksum. No global power,
    brightness, temperature, or colour commands are generated.
    """
    count = BACKLIGHT_SEGMENT_COUNTS.get(sku.upper())
    if count is None:
        raise GoveeLanError(f"Segment control is not supported for SKU {sku.upper()}")
    if not isinstance(groups, list) or not 1 <= len(groups) <= count:
        raise GoveeLanError(f"Supply between 1 and {count} segment groups")

    used: set[int] = set()
    packets = []
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"segments", "color"}:
            raise GoveeLanError("Each group requires only 'segments' and 'color'")
        color = group["color"]
        if (
            not isinstance(color, (list, tuple))
            or len(color) != 3
            or any(type(c) is not int or not 0 <= c <= 255 for c in color)
        ):
            raise GoveeLanError("Colors must contain three integers from 0 to 255")
        segments = group["segments"]
        if not isinstance(segments, (list, tuple)) or not 1 <= len(segments) <= count:
            raise GoveeLanError(f"Supply between 1 and {count} segment numbers")
        mask = 0
        for segment in segments:
            if type(segment) is not int or not 1 <= segment <= count:
                raise GoveeLanError(
                    f"Segment numbers must be integers from 1 to {count}"
                )
            if segment in used:
                raise GoveeLanError("A segment may appear only once per action")
            used.add(segment)
            mask |= 1 << (segment - 1)
        packet = _finish(
            [
                0x33,
                0x05,
                0x15,
                0x01,
                *color,
                0,
                0,
                0,
                0,
                0,
                mask & 0xFF,
                mask >> 8,
            ]
        )
        packets.append(base64.b64encode(bytes(packet)).decode())
    return packets
