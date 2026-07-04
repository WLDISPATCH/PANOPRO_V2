from __future__ import annotations

import io

import pytest
from PIL import Image

from pano_namer.services import overlay_tiles
from pano_namer.services.overlay_tiles import (
    TILE_SIZE,
    TileGrid,
    build_overlay_pmtiles,
    compute_tile_grid,
    read_tile,
)

# Fort Hills-ish bounds in EPSG:26912 meters: 2000m x 1200m.
BOUNDS = [500000.0, 6317000.0, 502000.0, 6318200.0]


def make_raster(path, width=2000, height=1200):
    image = Image.new("RGB", (width, height), (40, 90, 140))
    # A recognizable corner block so tile content can be sanity-checked.
    for x in range(200):
        for y in range(200):
            image.putpixel((x, y), (250, 40, 40))
    image.save(path, "PNG")
    return path


class TestTileGrid:
    def test_anchor_contains_whole_overlay(self):
        grid = compute_tile_grid(BOUNDS, 2000, 1200)
        scale = 2.0**grid.anchor_zoom
        assert int(BOUNDS[0] * scale // TILE_SIZE) == grid.anchor_x
        assert int((BOUNDS[2] * scale - 1e-9) // TILE_SIZE) == grid.anchor_x
        assert int(-BOUNDS[3] * scale // TILE_SIZE) == grid.anchor_y
        assert grid.max_zoom >= grid.anchor_zoom

    def test_local_coords_stay_in_range(self):
        grid = compute_tile_grid(BOUNDS, 2000, 1200)
        for z_map in range(grid.anchor_zoom, grid.max_zoom + 1):
            scale = 2.0**z_map
            x_first = int(BOUNDS[0] * scale // TILE_SIZE)
            x_last = int((BOUNDS[2] * scale - 1e-9) // TILE_SIZE)
            y_first = int(-BOUNDS[3] * scale // TILE_SIZE)
            y_last = int((-BOUNDS[1] * scale - 1e-9) // TILE_SIZE)
            for x in (x_first, x_last):
                for y in (y_first, y_last):
                    local = grid.to_local(z_map, x, y)
                    assert local is not None, (z_map, x, y)
                    level, lx, ly = local
                    assert 0 <= lx < (1 << level)
                    assert 0 <= ly < (1 << level)

    def test_out_of_range_is_none(self):
        grid = TileGrid(anchor_zoom=-3, anchor_x=244, anchor_y=-3086, max_zoom=0)
        assert grid.to_local(-4, 0, 0) is None
        assert grid.to_local(1, 0, 0) is None
        assert grid.to_local(-3, 245, -3086) is None

    def test_invalid_bounds_raise(self):
        with pytest.raises(overlay_tiles.OverlayTileError):
            compute_tile_grid([10, 10, 10, 20], 100, 100)


class TestBuildAndRead:
    def test_round_trip(self, tmp_path):
        raster = make_raster(tmp_path / "overlay.png")
        archive = tmp_path / "overlay.pmtiles"
        grid = build_overlay_pmtiles(raster, BOUNDS, archive)
        assert archive.exists()

        # Anchor-zoom tile exists and decodes to a 256px PNG.
        data = read_tile(archive, grid, grid.anchor_zoom, grid.anchor_x, grid.anchor_y)
        assert data is not None
        with Image.open(io.BytesIO(data)) as tile:
            assert tile.size == (TILE_SIZE, TILE_SIZE)

        # A max-zoom tile at the overlay's top-left corner (red block).
        scale = 2.0**grid.max_zoom
        x = int(BOUNDS[0] * scale // TILE_SIZE)
        y = int(-BOUNDS[3] * scale // TILE_SIZE)
        data = read_tile(archive, grid, grid.max_zoom, x, y)
        assert data is not None
        with Image.open(io.BytesIO(data)) as tile:
            rgba = tile.convert("RGBA")
            # Sample a pixel inside the overlay's red corner region.
            probe = rgba.getpixel((TILE_SIZE - 1, TILE_SIZE - 1))
            assert probe[3] == 255  # opaque: inside the overlay
        # Outside the pyramid range -> None
        assert read_tile(archive, grid, grid.max_zoom + 1, 0, 0) is None


class TestOverlayTileEndpoint:
    def test_import_builds_tiles_and_serves_them(self, tmp_path):
        from fastapi.testclient import TestClient

        from pano_namer.config import AppConfig
        from pano_namer.main import create_app

        config = AppConfig.load(tmp_path / "data")
        app = create_app(config)
        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "TILES"}).json()

        # Georeference via embedded EPSG/BOUNDS markers (a world file would
        # be left behind when the import copies the raster into storage).
        raster = make_raster(tmp_path / "site.png")
        with raster.open("ab") as handle:
            handle.write(b"\nEPSG:26912\nBOUNDS:500000,6317000,502000,6318200\n")

        overlay = client.post(
            f"/api/projects/{project['id']}/overlay",
            json={"source_path": str(raster)},
        ).json()
        assert overlay["tile_url"], overlay
        assert overlay["tile_min_zoom"] is not None
        assert overlay["tile_max_zoom"] is not None

        # Fetch the anchor tile through the URL template.
        url = (
            overlay["tile_url"]
            .replace("{z}", str(overlay["tile_min_zoom"]))
            .replace("{x}", "")
            .replace("{y}", "")
        )
        # Compute anchor indices like the service does.
        grid = compute_tile_grid(overlay["bounds"], overlay["width"], overlay["height"])
        url = overlay["tile_url"]
        url = url.replace("{z}", str(grid.anchor_zoom))
        url = url.replace("{x}", str(grid.anchor_x))
        url = url.replace("{y}", str(grid.anchor_y))
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["content-type"] == "image/png"

        # Out-of-range tiles 404 rather than error.
        missing = overlay["tile_url"].replace("{z}", "10").replace("{x}", "0").replace("{y}", "0")
        assert client.get(missing).status_code == 404

        # map-data carries the tile fields for the frontend.
        map_data = client.get(f"/api/projects/{project['id']}/map-data").json()
        assert map_data["overlay"]["tile_url"] == overlay["tile_url"]
