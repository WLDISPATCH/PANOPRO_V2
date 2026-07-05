"""SD card detection and stitched-pano discovery for Smart Import.

Classification is metadata-driven: a stitched 360 pano carries
GPano:ProjectionType="equirectangular" in its XMP (verified on DJI M4E
output). A 2:1 aspect ratio at pano resolution is accepted as a fallback
for files whose XMP is missing. Raw stitch tiles and normal photos are
counted but never returned as panos.
"""

from __future__ import annotations

import ctypes
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pano_namer.services.photos import read_photo_metadata

PANO_EXTENSIONS = {".jpg", ".jpeg"}

# Bytes of the file head scanned for JPEG dimensions and XMP. DJI writes
# XMP in the first APP1 segments, well inside this window.
_HEADER_READ_BYTES = 2 * 1024 * 1024

_EQUIRECTANGULAR_RE = re.compile(
    rb'GPano:ProjectionType\s*(?:=\s*"equirectangular"|>\s*equirectangular\s*<)'
)

_MIN_FALLBACK_PANO_WIDTH = 4096

_DRIVE_REMOVABLE = 2


@dataclass(slots=True)
class ScannedPano:
    path: Path
    original_name: str
    gps_lat: float | None
    gps_lon: float | None
    capture_ts: str | None


@dataclass(slots=True)
class ScanResult:
    source_root: Path
    panos: list[ScannedPano] = field(default_factory=list)
    skipped_normal: int = 0
    skipped_unreadable: int = 0


def removable_drives_with_dcim() -> list[Path]:
    """Return removable drive roots that contain a DCIM folder."""
    if sys.platform != "win32":
        return []
    drives: list[Path] = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for index in range(26):
        if not bitmask & (1 << index):
            continue
        root = Path(f"{chr(ord('A') + index)}:\\")
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(str(root)))
        if drive_type != _DRIVE_REMOVABLE:
            continue
        if (root / "DCIM").is_dir():
            drives.append(root)
    return drives


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return (width, height)
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > len(data):
            return None
        segment_length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if segment_length < 2:
            return None
        i += 2 + segment_length
    return None


def is_stitched_pano(path: Path) -> bool:
    """True when the file is a stitched equirectangular 360 pano."""
    try:
        with path.open("rb") as handle:
            head = handle.read(_HEADER_READ_BYTES)
    except OSError:
        return False
    if _EQUIRECTANGULAR_RE.search(head):
        return True
    dimensions = _jpeg_dimensions(head)
    if dimensions is None:
        return False
    width, height = dimensions
    return height > 0 and width == height * 2 and width >= _MIN_FALLBACK_PANO_WIDTH


def scan_events(source_root: Path):
    """Walk a DCIM tree yielding progress dicts, then a final result dict.

    Non-pano JPGs are only counted so the summary can show the card was
    fully read; nothing besides stitched panos is ever imported. Progress
    events ({"type": "progress", scanned, total, panos}) are throttled to
    every few files; the last event is {"type": "result", "result": ScanResult}.
    """
    result = ScanResult(source_root=source_root)
    scan_root = source_root / "DCIM" if (source_root / "DCIM").is_dir() else source_root
    candidates = [
        path
        for path in sorted(scan_root.rglob("*"))
        if path.is_file() and path.suffix.lower() in PANO_EXTENSIONS
    ]
    total = len(candidates)
    for index, path in enumerate(candidates, start=1):
        if not is_stitched_pano(path):
            result.skipped_normal += 1
        else:
            try:
                meta = read_photo_metadata(path)
                result.panos.append(
                    ScannedPano(
                        path=path,
                        original_name=path.name,
                        gps_lat=meta["gps_lat"],
                        gps_lon=meta["gps_lon"],
                        capture_ts=meta["capture_ts"],
                    )
                )
            except Exception:
                result.skipped_unreadable += 1
        if index % 5 == 0 or index == total:
            yield {
                "type": "progress",
                "scanned": index,
                "total": total,
                "panos": len(result.panos),
            }
    yield {"type": "result", "result": result}


def scan_for_panos(source_root: Path) -> ScanResult:
    """Non-streaming wrapper over scan_events."""
    result = ScanResult(source_root=source_root)
    for event in scan_events(source_root):
        if event["type"] == "result":
            result = event["result"]
    return result
