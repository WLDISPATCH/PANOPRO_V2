from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pyproj import Transformer

from pano_namer.config import AppConfig, FIXED_CRS
from pano_namer.main import create_app
from pano_namer.schemas import (
    AreaCreate,
    AreaGeometryUpdate,
    PhotoImportRequest,
    ProjectCreate,
)
from pano_namer.services.dxf import build_manual_multipolygon_wkt

TEST_TMP_ROOT = Path(".test_tmp")


def _ring(cx: float, cy: float, r: float = 200.0) -> list[list[float]]:
    return [[cx - r, cy - r], [cx + r, cy - r], [cx + r, cy + r], [cx - r, cy + r]]


class AreaGeometryEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.base_dir = (TEST_TMP_ROOT / f"geom_{uuid4().hex}").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config = AppConfig.load(self.base_dir)
        self.app = create_app(self.config)
        self.create_project = self._route("/api/projects", "POST")
        self.create_area = self._route("/api/projects/{project_id}/areas", "POST")
        self.update_geometry = self._route(
            "/api/projects/{project_id}/areas/{area_id}/geometry", "PUT"
        )
        self.import_photos = self._route(
            "/api/projects/{project_id}/photos/import", "POST"
        )
        self.list_photos = self._route("/api/projects/{project_id}/photos", "GET")
        self.map_data = self._route("/api/projects/{project_id}/map-data", "GET")
        self.project = self.create_project(ProjectCreate(name="Geom"))
        self._inv = Transformer.from_crs(FIXED_CRS, "EPSG:4326", always_xy=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def _route(self, path: str, method: str):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(
                route, "methods", set()
            ):
                return route.endpoint
        raise AssertionError(f"Route not found: {method} {path}")

    def _import_photo_at(self, cx: float, cy: float):
        lon, lat = self._inv.transform(cx, cy)
        meta = {"capture_ts": "2026-03-14T12:00:00", "gps_lat": lat, "gps_lon": lon}
        source = self.base_dir / f"{uuid4().hex}.jpg"
        source.write_bytes(b"x")
        with patch("pano_namer.main.read_photo_metadata", side_effect=lambda p: meta):
            payload = self.import_photos(
                self.project["id"], PhotoImportRequest(paths=[str(source)])
            )
        return payload["imported"][0]

    def test_multipolygon_builder_combines_rings(self) -> None:
        wkt, bbox = build_manual_multipolygon_wkt(
            [_ring(0, 0), _ring(1000, 1000)]
        )
        self.assertTrue(wkt.startswith("MULTIPOLYGON"))
        self.assertEqual(bbox[0], -200.0)

    def test_edit_geometry_rematches_photos_and_writes_kml(self) -> None:
        center = (500000.0, 6300000.0)
        area = self.create_area(
            self.project["id"],
            AreaCreate(name="Drain", coordinates=_ring(*center)),
        )
        # A photo inside the original footprint matches the area.
        photo = self._import_photo_at(*center)
        matched = self.list_photos(self.project["id"])[0]
        self.assertEqual(matched["area_name"], "Drain")

        # Move the footprint far away; the photo should no longer be inside it.
        moved = self.update_geometry(
            self.project["id"], area["id"],
            AreaGeometryUpdate(parts=[_ring(600000.0, 6400000.0)]),
        )
        self.assertNotEqual(moved["footprint_bbox"], area["footprint_bbox"])
        # The edited geometry is backed by a freshly written KML (for sync).
        self.assertTrue(moved["dxf_managed_path"].endswith(".kml"))
        self.assertTrue(Path(moved["dxf_managed_path"]).exists())

        after = self.list_photos(self.project["id"])[0]
        self.assertNotEqual(after["match_mode"], "inside")

    def test_edit_to_multipolygon_shows_two_parts_on_map(self) -> None:
        area = self.create_area(
            self.project["id"],
            AreaCreate(name="Split", coordinates=_ring(500000.0, 6300000.0)),
        )
        self.update_geometry(
            self.project["id"], area["id"],
            AreaGeometryUpdate(
                parts=[_ring(500000.0, 6300000.0), _ring(501000.0, 6300000.0)]
            ),
        )
        areas = self.map_data(self.project["id"])["areas"]
        edited = next(a for a in areas if a["id"] == area["id"])
        self.assertEqual(len(edited["parts"]), 2)

    def test_edit_geometry_rejects_degenerate_rings(self) -> None:
        from fastapi import HTTPException

        area = self.create_area(
            self.project["id"],
            AreaCreate(name="Drain", coordinates=_ring(500000.0, 6300000.0)),
        )
        with self.assertRaises(HTTPException) as ctx:
            self.update_geometry(
                self.project["id"], area["id"],
                AreaGeometryUpdate(parts=[[[0.0, 0.0], [1.0, 1.0]]]),
            )
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
