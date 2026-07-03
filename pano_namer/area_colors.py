from __future__ import annotations

import re


AREA_COLOR_PALETTE = (
    "#175c4c",
    "#b45a2a",
    "#225f99",
    "#8a4f9e",
    "#6e7f1e",
    "#9b3d3d",
    "#1f6d7a",
    "#8f6a1f",
    "#5b4ba6",
    "#a24c2c",
)
DEFAULT_AREA_COLOR = AREA_COLOR_PALETTE[0]
HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def normalize_area_color(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if not HEX_COLOR_RE.fullmatch(candidate):
        return None
    return f"#{candidate.lstrip('#').lower()}"


def next_available_area_color(existing_colors: list[str]) -> str:
    normalized = {color.lower() for color in existing_colors}
    for color in AREA_COLOR_PALETTE:
        if color.lower() not in normalized:
            return color
    return AREA_COLOR_PALETTE[len(existing_colors) % len(AREA_COLOR_PALETTE)]
