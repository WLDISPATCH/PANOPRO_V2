"""Overlay tile pyramids stored as PMTiles archives.

Instead of stretching one giant raster over the map (which exceeds GPU
texture limits on the desktop shell and corrupts the compositor), each
overlay is cut into a multi-zoom pyramid of 256px tiles stored in a single
.pmtiles file. The frontend then uses a stock Leaflet tile layer and the
GPU only ever holds the visible tiles at the current zoom.

Grid alignment: the map runs L.CRS.Simple, where the pixel position at
zoom z is (easting * 2**z, -northing * 2**z) and global tile indices are
floor(pixel / 256). Tiles are generated directly on this global grid, so
Leaflet's default tile addressing matches without any custom layer code.
PMTiles requires 0 <= x, y < 2**z, so archives store tiles relative to an
anchor: the single global tile that contains the whole overlay at the
coarsest zoom. Local coords at level k (k tiles below the anchor zoom)
are x_local = x_global - anchor_x * 2**k, which always lands in [0, 2**k).
"""

from __future__ import annotations

import io
import math
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

TILE_SIZE = 256

# Give up if no single anchor tile contains the overlay (only possible for
# rectangles straddling the coordinate origin, which EPSG:26912 data never
# does — eastings/northings are large positive numbers).
_MAX_ANCHOR_SEARCH = 48


class OverlayTileError(Exception):
    """Tile pyramid could not be generated."""


@dataclass(slots=True)
class TileGrid:
    """Pyramid addressing for one overlay."""

    anchor_zoom: int  # coarsest map zoom; whole overlay inside one tile
    anchor_x: int  # global tile index of that tile
    anchor_y: int
    max_zoom: int  # finest map zoom (~ native raster resolution)

    def to_local(self, z_map: int, x_global: int, y_global: int) -> tuple[int, int, int] | None:
        level = z_map - self.anchor_zoom
        if level < 0 or level > self.max_zoom - self.anchor_zoom:
            return None
        x_local = x_global - self.anchor_x * (1 << level)
        y_local = y_global - self.anchor_y * (1 << level)
        if not (0 <= x_local < (1 << level) and 0 <= y_local < (1 << level)):
            return None
        return level, x_local, y_local


def overlay_tiles_dir(base_dir: Path) -> Path:
    return (base_dir / "overlay_tiles").resolve()


def _tile_range(min_value: float, max_value: float, scale: float) -> tuple[int, int]:
    first = math.floor(min_value * scale / TILE_SIZE)
    last = math.floor((max_value * scale - 1e-9) / TILE_SIZE)
    return first, last


def compute_tile_grid(bounds: list[float], width_px: int, height_px: int) -> TileGrid:
    """Choose the zoom range and anchor tile for an overlay."""
    minx, miny, maxx, maxy = bounds
    if maxx <= minx or maxy <= miny or width_px <= 0 or height_px <= 0:
        raise OverlayTileError("Overlay bounds or raster size are invalid.")
    pixels_per_meter = max(width_px / (maxx - minx), height_px / (maxy - miny))
    max_zoom = round(math.log2(pixels_per_meter))

    zoom = max_zoom
    for _ in range(_MAX_ANCHOR_SEARCH):
        scale = 2.0**zoom
        x_first, x_last = _tile_range(minx, maxx, scale)
        y_first, y_last = _tile_range(-maxy, -miny, scale)
        if x_first == x_last and y_first == y_last:
            return TileGrid(
                anchor_zoom=zoom,
                anchor_x=x_first,
                anchor_y=y_first,
                max_zoom=max_zoom,
            )
        zoom -= 1
    raise OverlayTileError("Could not find an anchor tile for the overlay bounds.")


def build_overlay_pmtiles(
    raster_path: Path, bounds: list[float], out_path: Path
) -> TileGrid:
    """Cut the overlay raster into a leaflet-grid pyramid inside a PMTiles file."""
    from PIL import Image
    from pmtiles.tile import Compression, TileType, zxy_to_tileid
    from pmtiles.writer import Writer

    minx, miny, maxx, maxy = bounds
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(raster_path) as source:
        source.load()
        width_px, height_px = source.size
        grid = compute_tile_grid(bounds, width_px, height_px)
        src_ppm_x = width_px / (maxx - minx)
        src_ppm_y = height_px / (maxy - miny)

        tiles: list[tuple[int, bytes]] = []
        for z_map in range(grid.anchor_zoom, grid.max_zoom + 1):
            level = z_map - grid.anchor_zoom
            scale = 2.0**z_map  # screen px per meter at this zoom
            x_first, x_last = _tile_range(minx, maxx, scale)
            y_first, y_last = _tile_range(-maxy, -miny, scale)
            for y_global in range(y_first, y_last + 1):
                for x_global in range(x_first, x_last + 1):
                    tile_bytes = _render_tile(
                        source,
                        src_ppm_x,
                        src_ppm_y,
                        bounds,
                        scale,
                        x_global,
                        y_global,
                    )
                    if tile_bytes is None:
                        continue
                    x_local = x_global - grid.anchor_x * (1 << level)
                    y_local = y_global - grid.anchor_y * (1 << level)
                    tiles.append(
                        (zxy_to_tileid(level, x_local, y_local), tile_bytes)
                    )

    with out_path.open("wb") as handle:
        writer = Writer(handle)
        for tile_id, data in sorted(tiles, key=lambda item: item[0]):
            writer.write_tile(tile_id, data)
        writer.finalize(
            {
                "tile_type": TileType.PNG,
                "tile_compression": Compression.NONE,
                "min_lon_e7": 0,
                "min_lat_e7": 0,
                "max_lon_e7": 0,
                "max_lat_e7": 0,
                "center_zoom": 0,
                "center_lon_e7": 0,
                "center_lat_e7": 0,
            },
            {
                "anchor_zoom": grid.anchor_zoom,
                "anchor_x": grid.anchor_x,
                "anchor_y": grid.anchor_y,
                "max_zoom": grid.max_zoom,
                "bounds": bounds,
                "tile_size": TILE_SIZE,
            },
        )
    return grid


def _render_tile(
    source,
    src_ppm_x: float,
    src_ppm_y: float,
    bounds: list[float],
    scale: float,
    x_global: int,
    y_global: int,
):
    """Resample the overlay region covered by one global tile, or None if empty."""
    from PIL import Image

    minx, miny, maxx, maxy = bounds
    tile_minx = x_global * TILE_SIZE / scale
    tile_maxx = (x_global + 1) * TILE_SIZE / scale
    tile_maxy = -(y_global * TILE_SIZE) / scale
    tile_miny = -((y_global + 1) * TILE_SIZE) / scale

    clip_minx = max(tile_minx, minx)
    clip_maxx = min(tile_maxx, maxx)
    clip_miny = max(tile_miny, miny)
    clip_maxy = min(tile_maxy, maxy)
    if clip_maxx <= clip_minx or clip_maxy <= clip_miny:
        return None

    # Destination rect inside the 256px tile canvas.
    dest_x0 = int(round((clip_minx - tile_minx) * scale))
    dest_x1 = int(round((clip_maxx - tile_minx) * scale))
    dest_y0 = int(round((tile_maxy - clip_maxy) * scale))
    dest_y1 = int(round((tile_maxy - clip_miny) * scale))
    dest_w = max(1, min(TILE_SIZE, dest_x1) - dest_x0)
    dest_h = max(1, min(TILE_SIZE, dest_y1) - dest_y0)
    if dest_x0 >= TILE_SIZE or dest_y0 >= TILE_SIZE:
        return None

    # Matching source rect in raster pixels (y measured from the top = maxy).
    src_x0 = (clip_minx - minx) * src_ppm_x
    src_x1 = (clip_maxx - minx) * src_ppm_x
    src_y0 = (maxy - clip_maxy) * src_ppm_y
    src_y1 = (maxy - clip_miny) * src_ppm_y
    box = (
        max(0.0, src_x0),
        max(0.0, src_y0),
        min(float(source.width), max(src_x1, src_x0 + 1e-6)),
        min(float(source.height), max(src_y1, src_y0 + 1e-6)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return None

    region = source.resize((dest_w, dest_h), Image.BILINEAR, box=box)
    if dest_x0 == 0 and dest_y0 == 0 and dest_w == TILE_SIZE and dest_h == TILE_SIZE:
        tile_image = region.convert("RGB")
    else:
        tile_image = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
        tile_image.paste(region, (dest_x0, dest_y0))

    buffer = io.BytesIO()
    tile_image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# ---- Reading / serving ----

_reader_lock = threading.Lock()
_reader_cache: dict[str, tuple[float, object, object]] = {}


def read_tile(pmtiles_path: Path, grid: TileGrid, z_map: int, x_global: int, y_global: int) -> bytes | None:
    from pmtiles.reader import MmapSource, Reader

    local = grid.to_local(z_map, x_global, y_global)
    if local is None:
        return None
    key = str(pmtiles_path)
    try:
        mtime = pmtiles_path.stat().st_mtime_ns
    except OSError:
        return None
    with _reader_lock:
        cached = _reader_cache.get(key)
        if cached is None or cached[0] != mtime:
            handle = pmtiles_path.open("rb")
            reader = Reader(MmapSource(handle))
            _reader_cache[key] = (mtime, reader, handle)
        reader = _reader_cache[key][1]
    return reader.get(*local)


# ---- Generation for existing overlays (startup backfill) ----


def build_tiles_for_overlay_row(conn: sqlite3.Connection, data_dir: Path, row: sqlite3.Row) -> bool:
    """Generate and record a pyramid for one overlays row. True on success."""
    import json

    from pano_namer.services.common import utc_now

    bounds = json.loads(row["bounds_json"]) if row["bounds_json"] else None
    raster = Path(row["jpg_managed_path"] or "")
    if not bounds or not raster.exists() or raster.suffix.lower() == ".pdf":
        return False
    out_path = overlay_tiles_dir(data_dir) / f"overlay_{row['id']}.pmtiles"
    grid = build_overlay_pmtiles(raster, bounds, out_path)
    conn.execute(
        """
        UPDATE overlays
        SET pmtiles_path = ?, tile_anchor_zoom = ?, tile_anchor_x = ?,
            tile_anchor_y = ?, tile_max_zoom = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            str(out_path),
            grid.anchor_zoom,
            grid.anchor_x,
            grid.anchor_y,
            grid.max_zoom,
            utc_now(),
            row["id"],
        ),
    )
    return True


def backfill_overlay_tiles(db, data_dir: Path) -> None:
    """Build pyramids for overlays that predate tiling. Runs in a thread."""

    def worker() -> None:
        try:
            with db.connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM overlays WHERE active = 1 AND pmtiles_path IS NULL"
                ).fetchall()
                for row in rows:
                    try:
                        if build_tiles_for_overlay_row(conn, data_dir, row):
                            conn.commit()
                    except Exception:
                        conn.rollback()
        except Exception:
            pass

    threading.Thread(target=worker, name="overlay-tile-backfill", daemon=True).start()
