from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pano_namer import __version__
from pano_namer.config import AppConfig
from pano_namer.main import create_app
from pano_namer.schemas import (
    AreaCreate,
    PhotoImportRequest,
    PhotoUpdateRequest,
    ProjectCreate,
    RenameReservationReportRequest,
    RenameReservationResult,
    RenameReservationsCommitRequest,
    RenameRunCreate,
)

TEST_TMP_ROOT = Path(".test_tmp")


class SafetyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.base_dir = (TEST_TMP_ROOT / f"safety_{uuid4().hex}").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.load(self.base_dir)
        self.app = create_app(config)
        self.app_info = self._route("/api/app-info", "GET")
        self.cleanup_unused_cache = self._route("/api/cache/cleanup-unused", "POST")
        self.create_project = self._route("/api/projects", "POST")
        self.create_area = self._route("/api/projects/{project_id}/areas", "POST")
        self.import_photos = self._route(
            "/api/projects/{project_id}/photos/import", "POST"
        )
        self.list_photo_batches = self._route(
            "/api/projects/{project_id}/photo-batches", "GET"
        )
        self.list_photos = self._route("/api/projects/{project_id}/photos", "GET")
        self.update_photo = self._route(
            "/api/projects/{project_id}/photos/{photo_id}", "PUT"
        )
        self.preview_rename = self._route(
            "/api/projects/{project_id}/rename-preview", "POST"
        )
        self.commit_rename_reservations = self._route(
            "/api/projects/{project_id}/rename-reservations/commit", "POST"
        )
        self.report_rename_reservation_results = self._route(
            "/api/projects/{project_id}/rename-reservations/report-results", "POST"
        )
        self.run_rename = self._route("/api/projects/{project_id}/rename-runs", "POST")
        self.rollback_rename = self._route(
            "/api/projects/{project_id}/rename-runs/{run_id}/rollback", "POST"
        )
        self.project = self.create_project(ProjectCreate(name="Template A"))

    def tearDown(self) -> None:
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def _route(self, path: str, method: str):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(
                route, "methods", set()
            ):
                return route.endpoint
        raise AssertionError(f"Route not found: {method} {path}")

    def create_photo(self, name: str, payload: bytes = b"photo") -> Path:
        path = self.base_dir / name
        path.write_bytes(payload)
        return path

    def import_with_metadata(
        self,
        paths: list[Path],
        metadata_by_path: dict[str, dict] | None = None,
        error_paths: set[str] | None = None,
    ) -> dict:
        metadata_by_path = metadata_by_path or {}
        error_paths = error_paths or set()

        def fake_metadata(path: Path) -> dict:
            path_value = str(path)
            if path_value in error_paths:
                raise ValueError("Broken metadata")
            return metadata_by_path.get(
                path_value,
                {
                    "capture_ts": "2026-03-14T12:00:00",
                    "gps_lat": 57.0,
                    "gps_lon": -111.0,
                },
            )

        with patch("pano_namer.main.read_photo_metadata", side_effect=fake_metadata):
            return self.import_photos(
                self.project["id"],
                PhotoImportRequest(paths=[str(path) for path in paths]),
            )

    def test_import_skips_duplicates_and_reports_summary(self) -> None:
        first = self.create_photo("first.jpg")
        bad = self.create_photo("bad.jpg")
        self.import_with_metadata([first])

        payload = self.import_with_metadata([first, bad], error_paths={str(bad)})

        self.assertEqual(
            payload["summary"], {"imported": 0, "duplicates": 1, "errors": 1}
        )
        statuses = {item["path"]: item["status"] for item in payload["results"]}
        self.assertEqual(statuses[str(first)], "duplicate")
        self.assertEqual(statuses[str(bad)], "error")
        self.assertEqual(len(self.list_photos(self.project["id"])), 1)

    def test_import_creates_photo_batch_and_links_photos(self) -> None:
        first = self.create_photo("batch_first.jpg")
        second = self.create_photo("batch_second.jpg")

        payload = self.import_with_metadata([first, second])

        self.assertEqual(
            payload["summary"], {"imported": 2, "duplicates": 0, "errors": 0}
        )
        imported = payload["imported"]
        self.assertEqual(len(imported), 2)
        batch_ids = {photo["batch_id"] for photo in imported}
        photo_batch_ids = {photo["photo_batch_id"] for photo in imported}
        self.assertEqual(len(batch_ids), 1)
        self.assertEqual(len(photo_batch_ids), 1)
        self.assertNotIn(None, photo_batch_ids)

        batches = self.list_photo_batches(self.project["id"])
        self.assertEqual(len(batches), 1)
        batch = batches[0]
        self.assertEqual(batch["batch_uid"], next(iter(batch_ids)))
        self.assertEqual(batch["id"], next(iter(photo_batch_ids)))
        self.assertEqual(batch["source_kind"], "import")
        self.assertEqual(batch["status"], "imported")
        self.assertEqual(batch["photo_count"], 2)
        self.assertIsNotNone(batch["completed_at"])

    def test_app_info_reports_version_and_paths(self) -> None:
        info = self.app_info()
        self.assertEqual(info["app_name"], "PANO PRO")
        self.assertEqual(info["version"], __version__)
        self.assertEqual(info["crs"], "EPSG:26912")
        self.assertTrue(info["data_dir"].endswith(self.base_dir.name))
        self.assertTrue(info["db_path"].endswith("pano_namer.db"))
        self.assertTrue(info["overlay_preview_dir"].endswith("overlay_previews"))

    def test_cleanup_unused_cache_removes_orphaned_preview_pngs(self) -> None:
        info = self.app_info()
        preview_dir = Path(info["overlay_preview_dir"])
        preview_dir.mkdir(parents=True, exist_ok=True)
        active_preview = preview_dir / "active.png"
        orphan_preview = preview_dir / "orphan.png"
        active_preview.write_bytes(b"active")
        orphan_preview.write_bytes(b"orphan")

        with self.app.state.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO overlays (
                    project_id, jpg_original_path, jpg_managed_path, crs, bounds_json,
                    width, height, active, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.project["id"],
                    str(self.base_dir / "source.pdf"),
                    str(active_preview),
                    "EPSG:26912",
                    None,
                    100,
                    100,
                    1,
                    None,
                    "2026-03-15T00:00:00",
                    "2026-03-15T00:00:00",
                ),
            )
            conn.commit()

        result = self.cleanup_unused_cache()

        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["kept_count"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertTrue(active_preview.exists())
        self.assertFalse(orphan_preview.exists())

    def test_preview_matches_plan_and_includes_skipped(self) -> None:
        area = self.create_area(self.project["id"], AreaCreate(name="Drain"))
        good = self.create_photo("good.jpg")
        missing_date = self.create_photo("missing_date.jpg")

        import_payload = self.import_with_metadata(
            [good, missing_date],
            metadata_by_path={
                str(good): {
                    "capture_ts": "2026-03-14T12:00:00",
                    "gps_lat": 57.0,
                    "gps_lon": -111.0,
                },
                str(missing_date): {
                    "capture_ts": None,
                    "gps_lat": 57.0,
                    "gps_lon": -111.0,
                },
            },
        )

        good_photo = next(
            photo
            for photo in import_payload["imported"]
            if photo["original_path"] == str(good)
        )
        self.update_photo(
            self.project["id"],
            good_photo["id"],
            PhotoUpdateRequest(matched_area_id=area["id"]),
        )

        preview = self.preview_rename(self.project["id"], RenameRunCreate())

        self.assertEqual(preview["summary"], {"planned": 1, "skipped": 1})
        planned = [row for row in preview["results"] if row["status"] == "planned"]
        skipped = [row for row in preview["results"] if row["status"] == "skipped"]
        self.assertEqual(planned[0]["final_name"], "260314_DRAIN_001.jpg")
        self.assertIn("capture timestamp", skipped[0]["detail"].lower())

    def test_desktop_reservation_commit_does_not_rename_or_mark_applied(self) -> None:
        area = self.create_area(self.project["id"], AreaCreate(name="Drain"))
        source = self.create_photo("desktop_commit.jpg")
        photo = self.import_with_metadata([source])["imported"][0]
        self.update_photo(
            self.project["id"],
            photo["id"],
            PhotoUpdateRequest(matched_area_id=area["id"]),
        )

        commit = self.commit_rename_reservations(
            self.project["id"],
            RenameReservationsCommitRequest(
                photo_ids=[photo["id"]], actor_label="William", client_device="Laptop A"
            ),
        )

        self.assertEqual(commit["summary"], {"reserved": 1})
        reservation = commit["reservations"][0]
        self.assertEqual(reservation["final_name"], "260314_DRAIN_001.jpg")
        self.assertTrue(source.exists())
        self.assertFalse(Path(reservation["target_path"]).exists())

        stored_photo = self.list_photos(self.project["id"])[0]
        self.assertFalse(stored_photo["applied"])
        self.assertEqual(stored_photo["original_path"], str(source))

        with self.app.state.db.connect() as conn:
            row = conn.execute(
                "SELECT reservation_status, applied_at, reported_at FROM filename_reservations WHERE id = ?",
                (reservation["reservation_id"],),
            ).fetchone()
        self.assertEqual(row["reservation_status"], "reserved")
        self.assertIsNone(row["applied_at"])
        self.assertIsNone(row["reported_at"])

    def test_desktop_reports_applied_and_failed_reservation_results(self) -> None:
        area = self.create_area(self.project["id"], AreaCreate(name="Drain"))
        applied_source = self.create_photo("desktop_applied.jpg", payload=b"applied")
        failed_source = self.create_photo("desktop_failed.jpg", payload=b"failed")
        payload = self.import_with_metadata([applied_source, failed_source])
        for photo in payload["imported"]:
            self.update_photo(
                self.project["id"],
                photo["id"],
                PhotoUpdateRequest(matched_area_id=area["id"]),
            )

        commit = self.commit_rename_reservations(
            self.project["id"], RenameReservationsCommitRequest()
        )
        reservations = sorted(
            commit["reservations"], key=lambda item: item["final_name"]
        )
        applied_reservation = reservations[0]
        failed_reservation = reservations[1]
        applied_target = Path(applied_reservation["target_path"])
        applied_source.rename(applied_target)

        report = self.report_rename_reservation_results(
            self.project["id"],
            RenameReservationReportRequest(
                results=[
                    RenameReservationResult(
                        photo_id=applied_reservation["photo_id"],
                        reservation_id=applied_reservation["reservation_id"],
                        status="applied",
                        final_path=str(applied_target),
                    ),
                    RenameReservationResult(
                        photo_id=failed_reservation["photo_id"],
                        reservation_id=failed_reservation["reservation_id"],
                        status="failed",
                        error="Local file was locked.",
                    ),
                ],
                actor_label="William",
                client_device="Laptop A",
            ),
        )

        self.assertEqual(report["summary"], {"applied": 1, "failed": 1, "errors": 0})
        photos = {photo["id"]: photo for photo in self.list_photos(self.project["id"])}
        self.assertTrue(photos[applied_reservation["photo_id"]]["applied"])
        self.assertEqual(
            photos[applied_reservation["photo_id"]]["original_path"],
            str(applied_target),
        )
        self.assertFalse(photos[failed_reservation["photo_id"]]["applied"])
        self.assertIn("locked", photos[failed_reservation["photo_id"]]["error"])

        with self.app.state.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, reservation_status, applied_at, error, reported_at
                FROM filename_reservations
                WHERE project_id = ?
                ORDER BY sequence_number
                """,
                (self.project["id"],),
            ).fetchall()
        self.assertEqual(rows[0]["reservation_status"], "applied")
        self.assertIsNotNone(rows[0]["applied_at"])
        self.assertIsNone(rows[0]["error"])
        self.assertIsNotNone(rows[0]["reported_at"])
        self.assertEqual(rows[1]["reservation_status"], "failed")
        self.assertIsNone(rows[1]["applied_at"])
        self.assertEqual(rows[1]["error"], "Local file was locked.")
        self.assertIsNotNone(rows[1]["reported_at"])

    def test_rollback_last_run_restores_file_and_pending_state(self) -> None:
        area = self.create_area(self.project["id"], AreaCreate(name="Drain"))
        source = self.create_photo("capture.jpg")
        import_payload = self.import_with_metadata([source])
        photo = import_payload["imported"][0]

        self.update_photo(
            self.project["id"],
            photo["id"],
            PhotoUpdateRequest(matched_area_id=area["id"]),
        )

        run = self.run_rename(self.project["id"], RenameRunCreate())
        renamed_path = Path(run["results"][0]["target_path"])
        self.assertTrue(renamed_path.exists())
        self.assertFalse(source.exists())

        rolled_back_run = self.rollback_rename(self.project["id"], run["id"])
        self.assertTrue(rolled_back_run["rollback_completed_at"])
        self.assertTrue(source.exists())
        self.assertFalse(renamed_path.exists())

        restored_photo = self.list_photos(self.project["id"])[0]
        self.assertFalse(restored_photo["applied"])
        self.assertEqual(restored_photo["original_path"], str(source))

    def test_rollback_marks_filename_reservations_rolled_back(self) -> None:
        area = self.create_area(self.project["id"], AreaCreate(name="Drain"))
        source = self.create_photo("reservation_rollback.jpg")
        import_payload = self.import_with_metadata([source])
        photo = import_payload["imported"][0]
        self.update_photo(
            self.project["id"],
            photo["id"],
            PhotoUpdateRequest(matched_area_id=area["id"]),
        )

        run = self.run_rename(self.project["id"], RenameRunCreate())
        self.rollback_rename(self.project["id"], run["id"])

        with self.app.state.db.connect() as conn:
            statuses = [
                row["reservation_status"]
                for row in conn.execute(
                    """
                    SELECT reservation_status
                    FROM filename_reservations
                    WHERE project_id = ? AND rename_run_id = ?
                    """,
                    (self.project["id"], run["id"]),
                ).fetchall()
            ]
            counter = conn.execute(
                """
                SELECT next_sequence_number
                FROM rename_sequence_counters
                WHERE project_id = ? AND capture_date = '2026-03-14' AND area_slug = 'DRAIN'
                """,
                (self.project["id"],),
            ).fetchone()

        self.assertEqual(statuses, ["rolled_back"])
        self.assertEqual(counter["next_sequence_number"], 2)

    def test_desktop_reservation_commit_william_jeff_sequences_do_not_overlap(
        self,
    ) -> None:
        area = self.create_area(self.project["id"], AreaCreate(name="Drain"))

        william_paths = [
            self.create_photo(
                f"desktop_william_{index:02d}.jpg", payload=f"w{index}".encode()
            )
            for index in range(1, 4)
        ]
        william_payload = self.import_with_metadata(william_paths)
        for photo in william_payload["imported"]:
            self.update_photo(
                self.project["id"],
                photo["id"],
                PhotoUpdateRequest(matched_area_id=area["id"]),
            )
        william_commit = self.commit_rename_reservations(
            self.project["id"],
            RenameReservationsCommitRequest(
                photo_ids=[photo["id"] for photo in william_payload["imported"]],
                actor_label="William",
            ),
        )

        jeff_paths = [
            self.create_photo(
                f"desktop_jeff_{index:02d}.jpg", payload=f"j{index}".encode()
            )
            for index in range(1, 4)
        ]
        jeff_payload = self.import_with_metadata(jeff_paths)
        for photo in jeff_payload["imported"]:
            self.update_photo(
                self.project["id"],
                photo["id"],
                PhotoUpdateRequest(matched_area_id=area["id"]),
            )
        jeff_commit = self.commit_rename_reservations(
            self.project["id"],
            RenameReservationsCommitRequest(
                photo_ids=[photo["id"] for photo in jeff_payload["imported"]],
                actor_label="Jeff",
            ),
        )

        william_names = [
            reservation["final_name"] for reservation in william_commit["reservations"]
        ]
        jeff_names = [
            reservation["final_name"] for reservation in jeff_commit["reservations"]
        ]
        self.assertEqual(
            william_names, [f"260314_DRAIN_{index:03d}.jpg" for index in range(1, 4)]
        )
        self.assertEqual(
            jeff_names, [f"260314_DRAIN_{index:03d}.jpg" for index in range(4, 7)]
        )

        with self.app.state.db.connect() as conn:
            counter = conn.execute(
                """
                SELECT next_sequence_number
                FROM rename_sequence_counters
                WHERE project_id = ? AND capture_date = '2026-03-14' AND area_slug = 'DRAIN'
                """,
                (self.project["id"],),
            ).fetchone()
        self.assertEqual(counter["next_sequence_number"], 7)

    def test_william_jeff_batches_continue_shared_area_sequence(self) -> None:
        area = self.create_area(self.project["id"], AreaCreate(name="Drain"))

        william_paths = [
            self.create_photo(f"william_{index:02d}.jpg", payload=f"w{index}".encode())
            for index in range(1, 6)
        ]
        william_payload = self.import_with_metadata(william_paths)
        for photo in william_payload["imported"]:
            self.update_photo(
                self.project["id"],
                photo["id"],
                PhotoUpdateRequest(matched_area_id=area["id"]),
            )

        william_run = self.run_rename(self.project["id"], RenameRunCreate())
        william_names = [
            Path(result["target_path"]).name for result in william_run["results"]
        ]

        jeff_paths = [
            self.create_photo(f"jeff_{index:02d}.jpg", payload=f"j{index}".encode())
            for index in range(1, 6)
        ]
        jeff_payload = self.import_with_metadata(jeff_paths)
        for photo in jeff_payload["imported"]:
            self.update_photo(
                self.project["id"],
                photo["id"],
                PhotoUpdateRequest(matched_area_id=area["id"]),
            )

        jeff_run = self.run_rename(self.project["id"], RenameRunCreate())
        jeff_names = [
            Path(result["target_path"]).name for result in jeff_run["results"]
        ]

        self.assertEqual(
            william_names, [f"260314_DRAIN_{index:03d}.jpg" for index in range(1, 6)]
        )
        self.assertEqual(
            jeff_names, [f"260314_DRAIN_{index:03d}.jpg" for index in range(6, 11)]
        )

        with self.app.state.db.connect() as conn:
            counter = conn.execute(
                """
                SELECT next_sequence_number
                FROM rename_sequence_counters
                WHERE project_id = ? AND capture_date = '2026-03-14' AND area_slug = 'DRAIN'
                """,
                (self.project["id"],),
            ).fetchone()
            reservations = conn.execute(
                """
                SELECT reservation_status
                FROM filename_reservations
                WHERE project_id = ?
                ORDER BY sequence_number
                """,
                (self.project["id"],),
            ).fetchall()

        self.assertEqual(counter["next_sequence_number"], 11)
        self.assertEqual(len(reservations), 10)
        self.assertTrue(
            all(row["reservation_status"] == "applied" for row in reservations)
        )


if __name__ == "__main__":
    unittest.main()
