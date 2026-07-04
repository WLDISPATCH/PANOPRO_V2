from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

_XMP_HEADER_READ_BYTES = 2 * 1024 * 1024


def _ratio_to_float(value: Any) -> float:
    if hasattr(value, "num") and hasattr(value, "den"):
        return float(value.num) / float(value.den)
    return float(value)


def _dms_to_decimal(values: Any, ref: str) -> float:
    degrees = _ratio_to_float(values[0])
    minutes = _ratio_to_float(values[1])
    seconds = _ratio_to_float(values[2])
    decimal = degrees + minutes / 60 + seconds / 3600
    if ref in {"S", "W"}:
        decimal *= -1
    return decimal


def _extract_xmp_value(raw: str, key: str) -> str | None:
    patterns = (
        rf'{re.escape(key)}="([^"]+)"',
        rf"<{re.escape(key)}>([^<]+)</{re.escape(key)}>",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return None


def _apply_xmp_metadata(
    raw: str,
    gps_lat: float | None,
    gps_lon: float | None,
    capture_ts: str | None,
) -> tuple[float | None, float | None, str | None]:
    if gps_lat is None:
        value = _extract_xmp_value(raw, "drone-dji:GpsLatitude") or _extract_xmp_value(
            raw, "exif:GPSLatitude"
        )
        if value is not None:
            gps_lat = float(value)
    if gps_lon is None:
        value = _extract_xmp_value(
            raw, "drone-dji:GpsLongtitude"
        ) or _extract_xmp_value(raw, "drone-dji:GpsLongitude")
        if value is not None:
            gps_lon = float(value)
    if capture_ts is None:
        value = _extract_xmp_value(raw, "xmp:CreateDate") or _extract_xmp_value(
            raw, "photoshop:DateCreated"
        )
        if value:
            capture_ts = value.replace("Z", "+00:00")
    return gps_lat, gps_lon, capture_ts


def read_photo_metadata(path: Path) -> dict[str, Any]:
    import exifread

    gps_lat = None
    gps_lon = None
    capture_ts = None

    with path.open("rb") as handle:
        tags = exifread.process_file(handle, details=False)

    if "GPS GPSLatitude" in tags and "GPS GPSLongitude" in tags:
        gps_lat = _dms_to_decimal(tags["GPS GPSLatitude"].values, str(tags.get("GPS GPSLatitudeRef", "N")))
        gps_lon = _dms_to_decimal(tags["GPS GPSLongitude"].values, str(tags.get("GPS GPSLongitudeRef", "E")))

    if "EXIF DateTimeOriginal" in tags:
        capture_ts = datetime.strptime(str(tags["EXIF DateTimeOriginal"]), "%Y:%m:%d %H:%M:%S").isoformat()
    elif "Image DateTime" in tags:
        capture_ts = datetime.strptime(str(tags["Image DateTime"]), "%Y:%m:%d %H:%M:%S").isoformat()

    with path.open("rb") as handle:
        raw = handle.read(_XMP_HEADER_READ_BYTES).decode("utf-8", errors="ignore")
    gps_lat, gps_lon, capture_ts = _apply_xmp_metadata(
        raw, gps_lat, gps_lon, capture_ts
    )

    if (
        gps_lat is None
        and gps_lon is None
        and capture_ts is None
        and path.stat().st_size > _XMP_HEADER_READ_BYTES
    ):
        raw = path.read_bytes().decode("utf-8", errors="ignore")
        gps_lat, gps_lon, capture_ts = _apply_xmp_metadata(
            raw, gps_lat, gps_lon, capture_ts
        )

    return {
        "gps_lat": gps_lat,
        "gps_lon": gps_lon,
        "capture_ts": capture_ts,
    }
