from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from pano_namer.config import AppConfig
from pano_namer.main import create_app
from pano_namer.schemas import (
    ArchiveAssignRequest,
    ArchiveFolderCreate,
    CollectionCreate,
    CollectionItemsRequest,
    PhotoTagsRequest,
    PhotoImportRequest,
    ProjectCreate,
    ReviewUpdate,
    TagCreate,
    ViewerStateUpdate,
)


TEST_TMP_ROOT = Path(".test_tmp")


class V2ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.base_dir = (TEST_TMP_ROOT / f"v2_{uuid4().hex}").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.load(self.base_dir)
        self.app = create_app(config)
        self.create_project = self._route("/api/projects", "POST")
        self.import_photos = self._route("/api/projects/{project_id}/photos/import", "POST")
        self.create_archive_folder = self._route("/api/archive-folders", "POST")
        self.assign_archive = self._route("/api/archive/assign", "POST")
        self.archive_library = self._route("/api/archive/library", "GET")
        self.create_collection = self._route("/api/collections", "POST")
        self.add_collection_items = self._route("/api/collections/{collection_id}/items", "POST")
        self.collection_detail = self._route("/api/collections/{collection_id}/detail", "GET")
        self.create_tag = self._route("/api/tags", "POST")
        self.assign_tags = self._route("/api/photos/{photo_id}/tags", "POST")
        self.viewer_payload = self._route("/api/photos/{photo_id}/viewer", "GET")
        self.update_viewer_state = self._route("/api/photos/{photo_id}/viewer-state", "PUT")
        self.update_review = self._route("/api/photos/{photo_id}/review", "PUT")
        self.scan_duplicates = self._route("/api/projects/{project_id}/duplicates/scan", "POST")
        self.list_duplicates = self._route("/api/projects/{project_id}/duplicates", "GET")
        self.project = self.create_project(ProjectCreate(name="V2 Template"))

    def tearDown(self) -> None:
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def _route(self, path: str, method: str):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route.endpoint
        raise AssertionError(f"Route not found: {method} {path}")

    def create_photo(self, name: str, color: tuple[int, int, int]) -> Path:
        path = self.base_dir / name
        image = Image.new("RGB", (64, 32), color)
        image.save(path, format="JPEG")
        return path

    def import_with_metadata(self, paths: list[Path], metadata_by_path: dict[str, dict] | None = None) -> list[dict]:
        metadata_by_path = metadata_by_path or {}

        def fake_metadata(path: Path) -> dict:
            return metadata_by_path.get(
                str(path),
                {
                    "capture_ts": "2026-03-14T12:00:00",
                    "gps_lat": 57.0,
                    "gps_lon": -111.0,
                },
            )

        with patch("pano_namer.main.read_photo_metadata", side_effect=fake_metadata):
            result = self.import_photos(
                self.project["id"],
                PhotoImportRequest(paths=[str(path) for path in paths]),
            )
        return result["imported"]

    def test_import_auto_adds_photos_to_iso_week_collections(self) -> None:
        week_11_a = self.create_photo("w11_a.jpg", (10, 120, 90))
        week_11_b = self.create_photo("w11_b.jpg", (20, 140, 100))
        week_12 = self.create_photo("w12.jpg", (30, 160, 110))

        imported = self.import_with_metadata(
            [week_11_a, week_11_b, week_12],
            metadata_by_path={
                str(week_11_a): {"capture_ts": "2026-03-10T09:00:00", "gps_lat": 57.0, "gps_lon": -111.0},
                str(week_11_b): {"capture_ts": "2026-03-12T11:00:00", "gps_lat": 57.0, "gps_lon": -111.0},
                str(week_12): {"capture_ts": "2026-03-18T13:00:00", "gps_lat": 57.0, "gps_lon": -111.0},
            },
        )

        collections = self._route("/api/collections", "GET")()
        names = {item["name"]: item["item_count"] for item in collections}
        self.assertEqual(names["2026 Week 11"], 2)
        self.assertEqual(names["2026 Week 12"], 1)

        week_11_collection = next(item for item in collections if item["name"] == "2026 Week 11")
        detail = self.collection_detail(week_11_collection["id"])
        self.assertEqual({photo["id"] for photo in detail["photos"]}, {imported[0]["id"], imported[1]["id"]})

    def test_archive_collection_viewer_and_duplicate_flow(self) -> None:
        first = self.create_photo("one.jpg", (40, 120, 80))
        second = self.create_photo("two.jpg", (40, 120, 80))
        imported = self.import_with_metadata([first, second])
        self.assertEqual(len(imported), 2)

        with self.app.state.db.connect() as conn:
            conn.execute("UPDATE photos SET projected_x = ?, projected_y = ? WHERE id = ?", (500.0, 500.0, imported[0]["id"]))
            conn.execute("UPDATE photos SET projected_x = ?, projected_y = ? WHERE id = ?", (500.0, 650.0, imported[1]["id"]))
            conn.commit()

        folder = self.create_archive_folder(ArchiveFolderCreate(name="Archive A"))
        self.assign_archive(ArchiveAssignRequest(photo_ids=[imported[0]["id"]], folder_id=folder["id"]))
        archive = self.archive_library()
        self.assertEqual(len(archive["folders"]), 1)
        self.assertEqual(archive["photos"][0]["archive_folder_name"], "Archive A")
        self.assertTrue(archive["photos"][0]["thumbnail_url"])

        collection = self.create_collection(CollectionCreate(name="Collection A"))
        self.add_collection_items(collection["id"], CollectionItemsRequest(photo_ids=[photo["id"] for photo in imported]))
        detail = self.collection_detail(collection["id"])
        self.assertEqual(detail["collection"]["name"], "Collection A")
        self.assertEqual(len(detail["photos"]), 2)
        self.assertEqual(len(detail["map_photos"]), 2)

        tag = self.create_tag(TagCreate(name="Inspection"))
        self.assign_tags(imported[0]["id"], PhotoTagsRequest(tag_ids=[tag["id"]]))

        self.update_viewer_state(
            imported[0]["id"],
            ViewerStateUpdate(north_offset=15, default_yaw=30, default_pitch=0, default_fov=75),
        )
        payload = self.viewer_payload(imported[0]["id"], collection_id=collection["id"])
        self.assertEqual(payload["photo"]["viewer_state"]["north_offset"], 15)
        self.assertGreaterEqual(len(payload["hotspots"]), 1)
        self.assertTrue(any(item["name"] == "Inspection" for item in payload["photo"]["tags"]))
        auto_hotspot = next(item for item in payload["hotspots"] if item["target_photo_id"] == imported[1]["id"])
        self.assertAlmostEqual(auto_hotspot["yaw"], 15.0, delta=0.5)

        self.update_review(imported[0]["id"], ReviewUpdate(reviewed=True))
        updated_archive = self.archive_library()
        reviewed_photo = next(item for item in updated_archive["photos"] if item["id"] == imported[0]["id"])
        self.assertTrue(reviewed_photo["reviewed"])

        self.scan_duplicates(self.project["id"])
        duplicates = self.list_duplicates(self.project["id"])
        self.assertGreaterEqual(len(duplicates), 1)


if __name__ == "__main__":
    unittest.main()
