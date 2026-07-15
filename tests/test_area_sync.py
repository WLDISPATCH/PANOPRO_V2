from __future__ import annotations

import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from pano_namer.config import AppConfig
from pano_namer.database import Database
from pano_namer.services import area_sync
from pano_namer.services.common import utc_now
from pano_namer.services.dxf import extract_area_geometry_wkt
from pano_namer.services.shared_naming import (
    SharedNamingSettings,
    SharedNamingUnavailableError,
    save_settings,
)
from pano_namer.services.storage import StorageService


class FakeSupabase:
    """In-memory stand-in for the shared_areas table + area-files bucket."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}

    def request(self, method: str, url: str, headers: dict, body: bytes | None):
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if "/rest/v1/shared_areas" in parsed.path:
            if method == "GET":
                if "template_name" in params:
                    template = params["template_name"].removeprefix("eq.")
                    rows = [r for r in self.rows.values() if r["template_name"] == template]
                else:
                    rows = list(self.rows.values())
                return 200, json.dumps(rows).encode("utf-8")
            if method == "POST":
                for row in json.loads(body or b"[]"):
                    existing = self.rows.get(row["uid"], {})
                    existing.update(row)
                    self.rows[row["uid"]] = existing
                return 201, b""
        if "/storage/v1/object/area-files/" in parsed.path:
            key = urllib.parse.unquote(
                parsed.path.split("/storage/v1/object/area-files/", 1)[1]
            )
            if method == "POST":
                self.files[key] = body or b""
                return 200, b""
            if method == "GET":
                if key not in self.files:
                    return 404, b""
                return 200, self.files[key]
            if method == "DELETE":
                existed = self.files.pop(key, None)
                return (200, b"") if existed is not None else (404, b"")
        return 500, b""


PROJECTED_SQUARE_WKT = (
    "POLYGON ((500000 6317300, 500120 6317300, 500120 6317420, "
    "500000 6317420, 500000 6317300))"
)


class Machine:
    """One simulated PanoPro install: its own DB, storage dir, and project."""

    def __init__(self, root: Path, name: str, template: str | None) -> None:
        self.base_dir = root / name
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config = AppConfig.load(self.base_dir)
        self.config.ensure_dirs()
        self.db = Database(self.config.db_path)
        self.db.initialize()
        self.storage = StorageService(self.config)
        with self.db.connect() as conn:
            if template is not None:
                conn.execute(
                    """
                    INSERT INTO projects (id, name, storage_root, crs, created_at, updated_at)
                    VALUES (1, ?, ?, 'EPSG:26912', ?, ?)
                    """,
                    (template, str(self.base_dir), utc_now(), utc_now()),
                )
            save_settings(
                conn,
                SharedNamingSettings(
                    enabled=False,
                    supabase_url="https://fake.supabase.co",
                    supabase_anon_key="anon",
                    computer_name=name,
                    sync_areas=True,
                ),
            )
            conn.commit()

    def add_drawn_area(self, name: str, color: str = "#175c4c") -> int:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO areas (
                    project_id, name, dxf_original_path, dxf_managed_path, display_color,
                    source_crs, footprint_wkt, footprint_bbox_json, active, created_at, updated_at
                )
                VALUES (1, ?, '', '', ?, 'EPSG:26912', ?, '[]', 1, ?, ?)
                """,
                (name, color, PROJECTED_SQUARE_WKT, utc_now(), utc_now()),
            )
            conn.commit()
            return cursor.lastrowid

    def area(self, name: str):
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM areas WHERE project_id = 1 AND name = ?", (name,)
            ).fetchone()

    def areas(self):
        with self.db.connect() as conn:
            return conn.execute("SELECT * FROM areas WHERE project_id = 1").fetchall()

    def sync(self):
        return area_sync.run_area_sync(self.db, self.storage, 1)


class AreaSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.fake = FakeSupabase()
        self.machine_a = Machine(root, "A", "SiteX")
        self.machine_b = Machine(root, "B", "SiteX")
        patcher = patch.object(area_sync, "_request", side_effect=self.fake.request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_drawn_area_pushes_from_a_and_pulls_on_b(self) -> None:
        self.machine_a.add_drawn_area("OPTA", "#3366cc")
        summary_a = self.machine_a.sync()
        self.assertTrue(summary_a["ok"], summary_a)
        self.assertEqual(summary_a["pushed_new"], 1)
        self.assertEqual(len(self.fake.rows), 1)
        self.assertEqual(len(self.fake.files), 1)

        summary_b = self.machine_b.sync()
        self.assertTrue(summary_b["ok"], summary_b)
        self.assertEqual(summary_b["pulled_new"], 1)
        pulled = self.machine_b.area("OPTA")
        self.assertIsNotNone(pulled)
        self.assertTrue(pulled["active"])
        self.assertEqual(pulled["sync_uid"], self.machine_a.area("OPTA")["sync_uid"])
        # geometry round-trips through the KML export/import within tolerance
        _, bbox = extract_area_geometry_wkt(Path(pulled["dxf_managed_path"]))
        self.assertAlmostEqual(bbox[0], 500000, delta=1.5)
        self.assertAlmostEqual(bbox[3], 6317420, delta=1.5)

    def test_rename_syncs_without_duplicating(self) -> None:
        self.machine_a.add_drawn_area("OPTA")
        self.machine_a.sync()
        self.machine_b.sync()

        area_a = self.machine_a.area("OPTA")
        with self.machine_a.db.connect() as conn:
            conn.execute(
                "UPDATE areas SET name = 'OPTA-RENAMED', updated_at = ? WHERE id = ?",
                (utc_now(), area_a["id"]),
            )
            conn.commit()
        summary_a = self.machine_a.sync()
        self.assertEqual(summary_a["pushed_updated"], 1)

        summary_b = self.machine_b.sync()
        self.assertEqual(summary_b["pulled_updated"], 1)
        names = [row["name"] for row in self.machine_b.areas()]
        self.assertIn("OPTA-RENAMED", names)
        self.assertNotIn("OPTA", names)
        self.assertEqual(len(names), 1)

    def test_file_change_pulls_new_geometry(self) -> None:
        self.machine_a.add_drawn_area("OPTA")
        self.machine_a.sync()
        self.machine_b.sync()

        area_a = self.machine_a.area("OPTA")
        shifted = PROJECTED_SQUARE_WKT.replace("500000", "500500").replace("500120", "500620")
        new_kml = area_sync.kml_for_polygon_wkt(shifted)
        new_path = Path(area_a["dxf_managed_path"]).with_name("shifted.kml")
        new_path.write_bytes(new_kml)
        with self.machine_a.db.connect() as conn:
            conn.execute(
                "UPDATE areas SET dxf_managed_path = ?, footprint_wkt = ?, updated_at = ? WHERE id = ?",
                (str(new_path), shifted, utc_now(), area_a["id"]),
            )
            conn.commit()
        self.machine_a.sync()

        summary_b = self.machine_b.sync()
        self.assertEqual(summary_b["pulled_updated"], 1)
        pulled = self.machine_b.area("OPTA")
        _, bbox = extract_area_geometry_wkt(Path(pulled["dxf_managed_path"]))
        self.assertAlmostEqual(bbox[0], 500500, delta=1.5)

    def test_deletion_tombstone_propagates(self) -> None:
        self.machine_a.add_drawn_area("OPTA")
        self.machine_a.sync()
        self.machine_b.sync()

        area_b = self.machine_b.area("OPTA")
        with self.machine_b.db.connect() as conn:
            conn.execute(
                "UPDATE areas SET active = 0, updated_at = ? WHERE id = ?",
                (utc_now(), area_b["id"]),
            )
            conn.commit()
        summary_b = self.machine_b.sync()
        self.assertEqual(summary_b["tombstoned"], 1)
        # Housekeeping: the deletion removes the file from the bucket too.
        self.assertEqual(len(self.fake.files), 0)

        summary_a = self.machine_a.sync()
        self.assertEqual(summary_a["deactivated"], 1)
        self.assertFalse(self.machine_a.area("OPTA")["active"])

    def test_blank_area_is_skipped(self) -> None:
        with self.machine_a.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO areas (
                    project_id, name, dxf_original_path, dxf_managed_path, display_color,
                    source_crs, footprint_wkt, footprint_bbox_json, active, created_at, updated_at
                )
                VALUES (1, 'BLANK', '', '', '#175c4c', 'EPSG:26912', 'POLYGON EMPTY', '[]', 1, ?, ?)
                """,
                (utc_now(), utc_now()),
            )
            conn.commit()
        summary = self.machine_a.sync()
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["pushed_new"], 0)
        self.assertEqual(len(self.fake.rows), 0)

    def test_disabled_sync_reports_not_enabled(self) -> None:
        with self.machine_a.db.connect() as conn:
            save_settings(
                conn,
                SharedNamingSettings(
                    supabase_url="https://fake.supabase.co",
                    supabase_anon_key="anon",
                    sync_areas=False,
                ),
            )
            conn.commit()
        summary = self.machine_a.sync()
        self.assertFalse(summary["ok"])
        self.assertIn("not enabled", summary["error"])

    def test_offline_returns_error_without_raising(self) -> None:
        self.machine_a.add_drawn_area("OPTA")

        def offline(*args, **kwargs):
            raise SharedNamingUnavailableError("offline")

        with patch.object(area_sync, "_request", side_effect=offline):
            summary = self.machine_a.sync()
        self.assertFalse(summary["ok"])
        self.assertIn("offline", summary["error"])


class GlobalAreaSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.fake = FakeSupabase()
        self.machine_a = Machine(self.root, "A", "SiteX")
        self.fresh = Machine(self.root, "FRESH", None)
        patcher = patch.object(area_sync, "_request", side_effect=self.fake.request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _settings(self, machine: Machine) -> SharedNamingSettings:
        with machine.db.connect() as conn:
            from pano_namer.services.shared_naming import load_settings

            return load_settings(conn)

    def test_fetch_remote_template_names_dedupes_and_skips_tombstones(self) -> None:
        self.fake.rows = {
            "u1": {"uid": "u1", "template_name": "SiteX", "deleted_at": None},
            "u2": {"uid": "u2", "template_name": "sitex", "deleted_at": None},
            "u3": {"uid": "u3", "template_name": "Gone", "deleted_at": utc_now()},
            "u4": {"uid": "u4", "template_name": "SiteY", "deleted_at": None},
        }
        names = area_sync.fetch_remote_template_names(self._settings(self.fresh))
        self.assertEqual(names, ["SiteX", "SiteY"])

    def test_ensure_project_reuses_case_insensitive_match(self) -> None:
        with self.machine_a.db.connect() as conn:
            project_id, created = area_sync._ensure_project(
                conn, self.machine_a.storage, "SITEX"
            )
        self.assertEqual(project_id, 1)
        self.assertFalse(created)

    def test_ensure_project_creates_missing_project(self) -> None:
        with self.fresh.db.connect() as conn:
            project_id, created = area_sync._ensure_project(
                conn, self.fresh.storage, "SiteZ"
            )
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        self.assertTrue(created)
        self.assertEqual(row["name"], "SiteZ")
        self.assertEqual(row["crs"], "EPSG:26912")

    def test_fresh_machine_bootstraps_templates_and_areas(self) -> None:
        self.machine_a.add_drawn_area("OPTA")
        self.machine_a.sync()

        summary = area_sync.run_global_area_sync(self.fresh.db, self.fresh.storage, None)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["templates_created"], 1)
        self.assertEqual(summary["created_names"], ["SiteX"])
        self.assertEqual(summary["templates_synced"], 1)
        self.assertEqual(summary["pulled_new"], 1)

        with self.fresh.db.connect() as conn:
            project = conn.execute(
                "SELECT * FROM projects WHERE name = 'SiteX'"
            ).fetchone()
            self.assertIsNotNone(project)
            areas = conn.execute(
                "SELECT * FROM areas WHERE project_id = ?", (project["id"],)
            ).fetchall()
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0]["name"], "OPTA")
        self.assertTrue(areas[0]["active"])

    def test_selected_local_only_project_gets_pushed(self) -> None:
        self.machine_a.add_drawn_area("OPTA")
        summary = area_sync.run_global_area_sync(
            self.machine_a.db, self.machine_a.storage, 1
        )
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["templates_created"], 0)
        self.assertEqual(summary["pushed_new"], 1)
        self.assertEqual(len(self.fake.rows), 1)

    def test_unselected_local_only_project_is_not_pushed(self) -> None:
        self.machine_a.add_drawn_area("OPTA")
        summary = area_sync.run_global_area_sync(
            self.machine_a.db, self.machine_a.storage, None
        )
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["templates_synced"], 0)
        self.assertEqual(len(self.fake.rows), 0)

    def test_disabled_sync_reports_not_enabled(self) -> None:
        with self.fresh.db.connect() as conn:
            save_settings(
                conn,
                SharedNamingSettings(
                    supabase_url="https://fake.supabase.co",
                    supabase_anon_key="anon",
                    sync_areas=False,
                ),
            )
            conn.commit()
        summary = area_sync.run_global_area_sync(self.fresh.db, self.fresh.storage, None)
        self.assertFalse(summary["ok"])
        self.assertIn("not enabled", summary["error"])


if __name__ == "__main__":
    unittest.main()
