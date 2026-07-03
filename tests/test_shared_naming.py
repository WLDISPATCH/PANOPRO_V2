from __future__ import annotations

import http.server
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi import HTTPException

from pano_namer.config import AppConfig
from pano_namer.database import Database
from pano_namer.main import create_app, reserve_plans_with_shared_naming
from pano_namer.schemas import (
    AreaCreate,
    PhotoImportRequest,
    PhotoUpdateRequest,
    ProjectCreate,
    RenameRunCreate,
    SharedNamingSettingsPayload,
)
from pano_namer.services import shared_naming
from pano_namer.services.reservations import reserve_filenames_for_photos
from pano_namer.services.shared_naming import (
    OFFLINE_MESSAGE,
    SharedNamingConflictError,
    SharedNamingSettings,
    SharedNamingUnavailableError,
    load_settings,
    registry_row_for_stem,
    registry_rows_for_plans,
    save_settings,
)

TEST_TMP_ROOT = Path(".test_tmp")


def make_stub_registry_server():
    """Local HTTP stand-in for the Supabase used_pano_names PostgREST endpoint."""
    registry: dict[str, dict] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep test output quiet
            pass

        def _send(self, status: int, body: bytes = b"") -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            date_code = query.get("date_code", ["eq."])[0].removeprefix("eq.")
            area_code = query.get("area_code", ["eq."])[0].removeprefix("eq.")
            sequences = [
                row["sequence_number"]
                for row in registry.values()
                if row["date_code"] == date_code and row["area_code"] == area_code
            ]
            rows = [{"sequence_number": max(sequences)}] if sequences else []
            self._send(200, json.dumps(rows).encode("utf-8"))

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            rows = json.loads(self.rfile.read(length) or b"[]")
            prefer = self.headers.get("Prefer", "")
            ignore_duplicates = "ignore-duplicates" in prefer
            if not ignore_duplicates and any(row["name"] in registry for row in rows):
                self._send(409)
                return
            added = []
            for row in rows:
                if row["name"] not in registry:
                    registry[row["name"]] = row
                    added.append(row)
            body = (
                json.dumps(added).encode("utf-8")
                if "return=representation" in prefer
                else b""
            )
            self._send(201, body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return server, registry


class SharedNamingDatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db = Database(self.root / "app.db")
        self.db.initialize()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (id, name, storage_root, crs, created_at, updated_at)
                VALUES (1, 'Shared Naming Project', ?, 'EPSG:26912', 'now', 'now')
                """,
                (str(self.root),),
            )
            conn.execute(
                """
                INSERT INTO areas (id, project_id, name, dxf_original_path, dxf_managed_path, display_color,
                    source_crs, footprint_wkt, footprint_bbox_json, active, created_at, updated_at)
                VALUES (1, 1, 'Drain', '', '', '#3366cc', 'EPSG:26912', 'POLYGON EMPTY', '[]', 1, 'now', 'now')
                """
            )
            conn.commit()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def create_photo(self, name: str, capture_ts: str, area_id: int = 1) -> int:
        path = self.root / name
        path.write_bytes(b"photo")
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO photos (
                    project_id, batch_id, original_path, capture_ts, matched_area_id,
                    applied, created_at, updated_at
                )
                VALUES (1, 'batch', ?, ?, ?, 0, 'now', 'now')
                """,
                (str(path), capture_ts, area_id),
            )
            conn.commit()
            return cursor.lastrowid

    def pending_rows(self, conn) -> list:
        return conn.execute(
            """
            SELECT photos.*, areas.name AS area_name
            FROM photos
            LEFT JOIN areas ON photos.matched_area_id = areas.id
            WHERE photos.project_id = 1 AND photos.applied = 0
            """
        ).fetchall()


class MinSequenceFloorTests(SharedNamingDatabaseTestCase):
    def test_shared_max_lifts_allocation_above_local_counter(self) -> None:
        self.create_photo("a.jpg", "2026-07-02T10:00:00")
        self.create_photo("b.jpg", "2026-07-02T10:05:00")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            plans = reserve_filenames_for_photos(
                conn,
                1,
                self.pending_rows(conn),
                min_sequences={("2026-07-02", "DRAIN"): 5},
            )
            conn.commit()
        self.assertEqual(
            [plan.final_name for plan in plans],
            ["260702_DRAIN_006.jpg", "260702_DRAIN_007.jpg"],
        )

    def test_lower_shared_max_does_not_reduce_local_counter(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO rename_sequence_counters (
                    project_id, capture_date, area_slug, next_sequence_number, created_at, updated_at
                )
                VALUES (1, '2026-07-02', 'DRAIN', 9, 'now', 'now')
                """
            )
            conn.commit()
        self.create_photo("a.jpg", "2026-07-02T10:00:00")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            plans = reserve_filenames_for_photos(
                conn,
                1,
                self.pending_rows(conn),
                min_sequences={("2026-07-02", "DRAIN"): 3},
            )
            conn.commit()
        self.assertEqual([plan.final_name for plan in plans], ["260702_DRAIN_009.jpg"])


class ClientTransportTests(unittest.TestCase):
    def settings(self) -> SharedNamingSettings:
        return SharedNamingSettings(
            enabled=True,
            supabase_url="https://example.supabase.co",
            supabase_anon_key="anon-key",
            computer_name="TEST-PC",
        )

    def test_conflict_status_raises_conflict_error(self) -> None:
        with patch.object(shared_naming, "_request", return_value=(409, b"")):
            with self.assertRaises(SharedNamingConflictError):
                shared_naming.register_names(self.settings(), [{"name": "x"}])

    def test_server_error_raises_unavailable(self) -> None:
        with patch.object(shared_naming, "_request", return_value=(500, b"")):
            with self.assertRaises(SharedNamingUnavailableError):
                shared_naming.register_names(self.settings(), [{"name": "x"}])

    def test_fetch_max_sequence_reads_top_row(self) -> None:
        with patch.object(
            shared_naming, "_request", return_value=(200, b'[{"sequence_number": 7}]')
        ):
            self.assertEqual(
                shared_naming.fetch_max_sequence(self.settings(), "260702", "DRAIN"), 7
            )

    def test_fetch_max_sequence_empty_registry_is_zero(self) -> None:
        with patch.object(shared_naming, "_request", return_value=(200, b"[]")):
            self.assertEqual(
                shared_naming.fetch_max_sequence(self.settings(), "260702", "DRAIN"), 0
            )


class StemParsingTests(unittest.TestCase):
    def test_recognized_stem_parses_into_registry_row(self) -> None:
        row = registry_row_for_stem("260702_OPTA_045", "FH-UAV-II")
        self.assertEqual(
            row,
            {
                "name": "260702_OPTA_045",
                "date_code": "260702",
                "area_code": "OPTA",
                "sequence_number": 45,
                "computer_name": "FH-UAV-II",
            },
        )

    def test_area_with_underscores_keeps_trailing_digits_as_sequence(self) -> None:
        row = registry_row_for_stem("260702_NORTH_POND_2_012", "PC")
        self.assertEqual(row["area_code"], "NORTH_POND_2")
        self.assertEqual(row["sequence_number"], 12)

    def test_unrecognized_stems_return_none(self) -> None:
        for stem in ("DJI_0042", "IMG_1234", "260702_OPTA", "notes"):
            self.assertIsNone(registry_row_for_stem(stem, "PC"), stem)


class SettingsRoundTripTests(SharedNamingDatabaseTestCase):
    def test_settings_round_trip(self) -> None:
        settings = SharedNamingSettings(
            enabled=True,
            supabase_url="https://example.supabase.co",
            supabase_anon_key="anon-key",
            computer_name="Survey-Laptop",
        )
        with self.db.connect() as conn:
            save_settings(conn, settings)
            conn.commit()
            loaded = load_settings(conn)
        self.assertEqual(loaded, settings)

    def test_defaults_when_unset(self) -> None:
        with self.db.connect() as conn:
            loaded = load_settings(conn)
        self.assertFalse(loaded.enabled)
        self.assertFalse(loaded.is_configured())
        self.assertTrue(loaded.resolved_computer_name())


class SharedAllocationFlowTests(SharedNamingDatabaseTestCase):
    def enabled_settings(self) -> SharedNamingSettings:
        return SharedNamingSettings(
            enabled=True,
            supabase_url="https://example.supabase.co",
            supabase_anon_key="anon-key",
            computer_name="TEST-PC",
        )

    def test_disabled_settings_keep_original_flow(self) -> None:
        self.create_photo("a.jpg", "2026-07-02T10:00:00")
        with self.db.connect() as conn:
            plans = reserve_plans_with_shared_naming(conn, 1, None)
            conn.commit()
        self.assertEqual([plan.final_name for plan in plans], ["260702_DRAIN_001.jpg"])

    def test_conflict_retries_with_refreshed_maximum(self) -> None:
        self.create_photo("a.jpg", "2026-07-02T10:00:00")
        fetch_results = iter([3, 5])
        register_calls: list[list[dict]] = []

        def fake_register(settings, rows):
            register_calls.append(rows)
            if len(register_calls) == 1:
                raise SharedNamingConflictError("taken")

        with (
            patch.object(
                shared_naming, "load_settings", return_value=self.enabled_settings()
            ),
            patch.object(
                shared_naming,
                "fetch_max_sequence",
                side_effect=lambda *args: next(fetch_results),
            ),
            patch.object(shared_naming, "register_names", side_effect=fake_register),
        ):
            with self.db.connect() as conn:
                plans = reserve_plans_with_shared_naming(conn, 1, None)
                conn.commit()

        self.assertEqual([plan.final_name for plan in plans], ["260702_DRAIN_006.jpg"])
        self.assertEqual(len(register_calls), 2)
        self.assertEqual(register_calls[1][0]["name"], "260702_DRAIN_006")
        with self.db.connect() as conn:
            reservations = conn.execute(
                "SELECT final_filename FROM filename_reservations"
            ).fetchall()
        self.assertEqual(
            [row["final_filename"] for row in reservations], ["260702_DRAIN_006.jpg"]
        )

    def test_unavailable_registry_blocks_with_offline_message(self) -> None:
        self.create_photo("a.jpg", "2026-07-02T10:00:00")
        with (
            patch.object(
                shared_naming, "load_settings", return_value=self.enabled_settings()
            ),
            patch.object(shared_naming, "fetch_max_sequence", return_value=0),
            patch.object(
                shared_naming,
                "register_names",
                side_effect=SharedNamingUnavailableError(OFFLINE_MESSAGE),
            ),
        ):
            with self.db.connect() as conn:
                with self.assertRaises(HTTPException) as raised:
                    reserve_plans_with_shared_naming(conn, 1, None)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, OFFLINE_MESSAGE)
        with self.db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM filename_reservations"
            ).fetchone()["n"]
        self.assertEqual(count, 0)

    def test_enabled_but_unconfigured_is_rejected(self) -> None:
        settings = SharedNamingSettings(enabled=True)
        with patch.object(shared_naming, "load_settings", return_value=settings):
            with self.db.connect() as conn:
                with self.assertRaises(HTTPException) as raised:
                    reserve_plans_with_shared_naming(conn, 1, None)
        self.assertEqual(raised.exception.status_code, 400)

    def test_registry_rows_built_from_plans(self) -> None:
        self.create_photo("a.jpg", "2026-07-02T10:00:00")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            plans = reserve_filenames_for_photos(conn, 1, self.pending_rows(conn))
            conn.commit()
        rows = registry_rows_for_plans(plans, "TEST-PC")
        self.assertEqual(
            rows,
            [
                {
                    "name": "260702_DRAIN_001",
                    "date_code": "260702",
                    "area_code": "DRAIN",
                    "sequence_number": 1,
                    "computer_name": "TEST-PC",
                }
            ],
        )


class SharedNamingEndToEndTests(unittest.TestCase):
    """Full route-level flow against a local stub of the Supabase registry."""

    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.base_dir = (TEST_TMP_ROOT / f"shared_{uuid4().hex}").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.app = create_app(AppConfig.load(self.base_dir))

        self.server, self.registry = make_stub_registry_server()
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self.supabase_url = f"http://127.0.0.1:{self.server.server_address[1]}"

        self.create_project = self._route("/api/projects", "POST")
        self.create_area = self._route("/api/projects/{project_id}/areas", "POST")
        self.import_photos = self._route(
            "/api/projects/{project_id}/photos/import", "POST"
        )
        self.update_photo = self._route(
            "/api/projects/{project_id}/photos/{photo_id}", "PUT"
        )
        self.run_rename = self._route("/api/projects/{project_id}/rename-runs", "POST")
        self.put_settings = self._route("/api/settings/shared-naming", "PUT")
        self.preview = self._route(
            "/api/projects/{project_id}/shared-naming/preview", "GET"
        )
        self.backfill = self._route(
            "/api/projects/{project_id}/shared-naming/backfill", "POST"
        )

        self.project = self.create_project(ProjectCreate(name="Template A"))
        self.area = self.create_area(self.project["id"], AreaCreate(name="Drain"))
        self.put_settings(
            SharedNamingSettingsPayload(
                enabled=True,
                supabase_url=self.supabase_url,
                supabase_anon_key="stub-key",
                computer_name="TEST-PC",
            )
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def _route(self, path: str, method: str):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(
                route, "methods", set()
            ):
                return route.endpoint
        raise AssertionError(f"Route not found: {method} {path}")

    def import_assigned_photos(self, names: list[str]) -> list[int]:
        paths = []
        for name in names:
            path = self.base_dir / name
            path.write_bytes(name.encode("utf-8"))
            paths.append(path)

        def fake_metadata(path: Path) -> dict:
            return {
                "capture_ts": "2026-03-14T12:00:00",
                "gps_lat": 57.0,
                "gps_lon": -111.0,
            }

        with patch("pano_namer.main.read_photo_metadata", side_effect=fake_metadata):
            payload = self.import_photos(
                self.project["id"],
                PhotoImportRequest(paths=[str(path) for path in paths]),
            )
        photo_ids = [photo["id"] for photo in payload["imported"]]
        for photo_id in photo_ids:
            self.update_photo(
                self.project["id"],
                photo_id,
                PhotoUpdateRequest(matched_area_id=self.area["id"]),
            )
        return photo_ids

    def test_export_continues_after_names_used_by_another_computer(self) -> None:
        # Another computer already exported 001-003 for this date and area.
        for sequence in range(1, 4):
            name = f"260314_DRAIN_{sequence:03d}"
            self.registry[name] = {
                "name": name,
                "date_code": "260314",
                "area_code": "DRAIN",
                "sequence_number": sequence,
                "computer_name": "OTHER-PC",
            }

        self.import_assigned_photos(["a.jpg", "b.jpg"])

        preview = self.preview(self.project["id"])
        self.assertTrue(preview["connected"])
        self.assertEqual(
            preview["groups"],
            [{"prefix": "260314_DRAIN", "photos": 2, "starts_at": 4}],
        )

        run = self.run_rename(self.project["id"], RenameRunCreate())
        renamed = [Path(result["target_path"]).name for result in run["results"]]
        self.assertEqual(renamed, ["260314_DRAIN_004.jpg", "260314_DRAIN_005.jpg"])
        self.assertTrue((self.base_dir / "260314_DRAIN_004.jpg").exists())
        self.assertIn("260314_DRAIN_004", self.registry)
        self.assertIn("260314_DRAIN_005", self.registry)
        self.assertEqual(self.registry["260314_DRAIN_004"]["computer_name"], "TEST-PC")

    def test_offline_registry_blocks_export_and_leaves_files_untouched(self) -> None:
        self.import_assigned_photos(["a.jpg"])
        self.server.shutdown()
        self.server.server_close()

        with self.assertRaises(HTTPException) as raised:
            self.run_rename(self.project["id"], RenameRunCreate())
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("offline", raised.exception.detail)
        self.assertTrue((self.base_dir / "a.jpg").exists())

    def test_backfill_registers_existing_names_once(self) -> None:
        self.import_assigned_photos(["260314_DRAIN_045.jpg", "DJI_0001.jpg"])

        first = self.backfill(self.project["id"])
        self.assertEqual(first["matched"], 1)
        self.assertEqual(first["added"], 1)
        self.assertIn("260314_DRAIN_045", self.registry)

        second = self.backfill(self.project["id"])
        self.assertEqual(second["added"], 0)


if __name__ == "__main__":
    unittest.main()
