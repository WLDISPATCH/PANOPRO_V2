from __future__ import annotations

import re
from hashlib import sha1
from pathlib import Path
from uuid import uuid4

from pano_namer.config import FIXED_CRS


def overlay_preview_dir(base_dir: Path) -> Path:
    return (base_dir / "overlay_previews").resolve()


def _number_list(raw: str) -> list[float]:
    return [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", raw)]


def _extract_pdf_arrays(raw: str) -> tuple[list[float] | None, list[float] | None]:
    lpts_match = re.search(r"/LPTS\s*\[([^\]]+)\]", raw, re.IGNORECASE | re.DOTALL)
    gpts_match = re.search(r"/GPTS\s*\[([^\]]+)\]", raw, re.IGNORECASE | re.DOTALL)
    lpts = _number_list(lpts_match.group(1)) if lpts_match else None
    gpts = _number_list(gpts_match.group(1)) if gpts_match else None
    return lpts, gpts


def _extract_pdf_viewport_bbox(raw: str) -> list[float] | None:
    match = re.search(
        r"/VP\s*\[\s*<<.*?/BBox\s*\[([^\]]+)\]",
        raw,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        match = re.search(
            r"/Type\s*/Viewport.*?/BBox\s*\[([^\]]+)\]",
            raw,
            re.IGNORECASE | re.DOTALL,
        )
    if not match:
        return None

    bbox = _number_list(match.group(1))
    if len(bbox) < 4:
        return None
    x1, y1, x2, y2 = bbox[:4]
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _extract_lgi_registration(raw: str) -> list[float] | None:
    match = re.search(r"/Registration\s*\[\s*\[(.*?)\]\s*\[(.*?)\]\s*\]", raw, re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    first = _number_list(match.group(1))
    second = _number_list(match.group(2))
    if len(first) < 4 or len(second) < 4:
        return None

    xs = [first[2], second[2]]
    ys = [first[3], second[3]]
    return [min(xs), min(ys), max(xs), max(ys)]


def _pdf_bounds_from_gpts(gpts: list[float]) -> list[float]:
    if len(gpts) < 8 or len(gpts) % 2 != 0:
        raise ValueError("Geospatial PDF did not contain enough GPTS coordinates.")

    pairs = list(zip(gpts[0::2], gpts[1::2]))
    if all(abs(value) <= 180 for value in gpts):
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:4326", FIXED_CRS, always_xy=True)
        projected = [transformer.transform(lon, lat) for lat, lon in pairs]
    else:
        projected = pairs

    xs = [pair[0] for pair in projected]
    ys = [pair[1] for pair in projected]
    return [min(xs), min(ys), max(xs), max(ys)]


def _render_pdf_preview(
    path: Path,
    preview_dir: Path | None = None,
    viewport_bbox: list[float] | None = None,
) -> tuple[Path, int, int]:
    import fitz

    preview_dir = (preview_dir or overlay_preview_dir(Path.cwd() / ".pano_namer_data")).resolve()
    preview_dir.mkdir(parents=True, exist_ok=True)
    stat = path.stat()
    token = sha1(f"{path.resolve()}::{stat.st_mtime_ns}::{stat.st_size}".encode("utf-8")).hexdigest()[:12]
    preview_path = preview_dir / f"{path.stem}_{token}_{uuid4().hex[:8]}.png"

    document = fitz.open(path)
    try:
        page = document.load_page(0)
        clip = None
        if viewport_bbox:
            x1, y1, x2, y2 = viewport_bbox
            page_height = page.rect.height
            clip = fitz.Rect(x1, page_height - y2, x2, page_height - y1)
            clip = clip & page.rect
            if clip.is_empty:
                clip = None
        pixmap = page.get_pixmap(dpi=150, alpha=False, clip=clip)
        pixmap.save(preview_path)
        return preview_path, pixmap.width, pixmap.height
    finally:
        document.close()


def parse_overlay_metadata(
    path: Path,
    preview_dir: Path | None = None,
) -> tuple[Path, str | None, list[float] | None, int | None, int | None, str | None]:
    if path.suffix.lower() == ".pdf":
        raw = path.read_bytes().decode("latin-1", errors="ignore")
        registration_bounds = _extract_lgi_registration(raw)
        viewport_bbox = None if registration_bounds else _extract_pdf_viewport_bbox(raw)
        _lpts, gpts = _extract_pdf_arrays(raw)
        if not gpts and not registration_bounds:
            return path, FIXED_CRS, None, None, None, "Could not read geospatial PDF bounds metadata from the overlay PDF."
        try:
            bounds = registration_bounds or _pdf_bounds_from_gpts(gpts or [])
            preview_path, width, height = _render_pdf_preview(
                path, preview_dir, viewport_bbox=viewport_bbox
            )
        except Exception as exc:  # pragma: no cover
            return path, FIXED_CRS, None, None, None, f"Unable to read the geospatial PDF overlay: {exc}"
        return preview_path, FIXED_CRS, bounds, width, height, None

    from PIL import Image

    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:  # pragma: no cover
        return path, FIXED_CRS, None, None, None, f"Unable to read image dimensions: {exc}"

    raw = path.read_bytes().decode("utf-8", errors="ignore")
    epsg_match = re.search(r"EPSG[:=]\s*(\d+)", raw, re.IGNORECASE)
    bounds_match = re.search(
        r"BOUNDS[:=]\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)",
        raw,
        re.IGNORECASE,
    )
    if epsg_match and bounds_match:
        bounds = [float(bounds_match.group(index)) for index in range(1, 5)]
        return path, f"EPSG:{epsg_match.group(1)}", bounds, width, height, None

    world_file = path.with_suffix(".jgw")
    prj_file = path.with_suffix(".prj")
    if world_file.exists():
        lines = [float(line.strip()) for line in world_file.read_text().splitlines()[:6]]
        if len(lines) == 6:
            pixel_width, _, _, pixel_height, top_left_x, top_left_y = lines
            minx = top_left_x
            maxy = top_left_y
            maxx = minx + (pixel_width * width)
            miny = maxy + (pixel_height * height)
            crs = prj_file.read_text().strip() if prj_file.exists() else None
            return path, crs or FIXED_CRS, [minx, miny, maxx, maxy], width, height, None

    return path, FIXED_CRS, None, width, height, "Could not read overlay georeference metadata."


def cleanup_unused_overlay_previews(preview_dir: Path, active_preview_paths: list[Path]) -> dict[str, int]:
    preview_dir = preview_dir.resolve()
    preview_dir.mkdir(parents=True, exist_ok=True)
    keep = {
        path.resolve()
        for path in active_preview_paths
        if path.suffix.lower() == ".png" and preview_dir in path.resolve().parents
    }
    deleted_count = 0
    deleted_bytes = 0
    kept_count = 0
    error_count = 0
    for candidate in preview_dir.glob("*.png"):
        resolved = candidate.resolve()
        if resolved in keep:
            kept_count += 1
            continue
        try:
            deleted_bytes += candidate.stat().st_size
            candidate.unlink()
            deleted_count += 1
        except OSError:
            error_count += 1
    return {
        "deleted_count": deleted_count,
        "deleted_bytes": deleted_bytes,
        "kept_count": kept_count,
        "error_count": error_count,
    }
