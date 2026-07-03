from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pano_namer.database import MIGRATIONS, Database


EXPECTED_INDEXES = {
    "photos": {
        "idx_photos_project_applied",
        "idx_photos_project_batch_id",
        "idx_photos_project_original_path",
        "idx_photos_project_matched_area_id",
        "idx_photos_project_photo_batch_id",
    },
    "photo_batches": {
        "idx_photo_batches_project_batch_uid",
        "idx_photo_batches_project_created_at",
    },
    "areas": {"idx_areas_project_active"},
    "rename_runs": {"idx_rename_runs_project_completed_at"},
    "pano_duplicates": {
        "idx_pano_duplicates_photo_id",
        "idx_pano_duplicates_duplicate_photo_id",
    },
    "filename_reservations": {
        "idx_filename_reservations_project_photo_id",
        "idx_filename_reservations_project_photo_batch_id",
        "idx_filename_reservations_project_rename_run_id",
        "idx_filename_reservations_project_status",
        "idx_filename_reservations_project_scope",
    },
    "rename_sequence_counters": {"idx_rename_sequence_counters_project_scope"},
    "users": {"idx_users_username", "idx_users_is_active", "idx_users_is_admin"},
}


class DatabaseMigrationTests(unittest.TestCase):
    def migration_versions(self, conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        return [row["version"] for row in rows]

    def table_columns(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}

    def index_names(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA index_list({table_name})").fetchall()}

    def assert_expected_indexes_exist(self, conn: sqlite3.Connection) -> None:
        for table_name, expected_indexes in EXPECTED_INDEXES.items():
            self.assertTrue(expected_indexes.issubset(self.index_names(conn, table_name)))

    def test_empty_database_initializes_with_schema_migrations_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "app.db")

            db.initialize()

            with db.connect() as conn:
                tables = {
                    row["name"]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                }
                self.assertIn("schema_migrations", tables)
                self.assertIn("photo_batches", tables)
                self.assertIn("rename_sequence_counters", tables)
                self.assertIn("filename_reservations", tables)
                self.assertIn("users", tables)
                self.assertIn("photo_batch_id", self.table_columns(conn, "photos"))
                self.assertEqual(
                    {
                        "id",
                        "username",
                        "email",
                        "display_name",
                        "password_hash",
                        "is_active",
                        "is_admin",
                        "created_at",
                        "updated_at",
                    },
                    self.table_columns(conn, "users"),
                )
                self.assertEqual(self.migration_versions(conn), sorted(version for version, _ in MIGRATIONS))
                self.assertIn("20260511_0005_photo_batches", self.migration_versions(conn))
                self.assertIn("20260511_0006_filename_reservations", self.migration_versions(conn))
                self.assertIn("20260512_0008_users_admin", self.migration_versions(conn))
                self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM rename_sequence_counters").fetchone()["count"], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM filename_reservations").fetchone()["count"], 0)
                self.assert_expected_indexes_exist(conn)

    def test_initialize_is_safe_to_run_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "app.db")

            db.initialize()
            with db.connect() as conn:
                first_rows = [dict(row) for row in conn.execute("SELECT * FROM schema_migrations ORDER BY version")]

            db.initialize()
            with db.connect() as conn:
                second_rows = [dict(row) for row in conn.execute("SELECT * FROM schema_migrations ORDER BY version")]
                self.assert_expected_indexes_exist(conn)

            self.assertEqual(first_rows, second_rows)

    def test_legacy_database_missing_compatibility_columns_is_upgraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    storage_root TEXT NOT NULL,
                    crs TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE areas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    dxf_original_path TEXT NOT NULL,
                    dxf_managed_path TEXT NOT NULL,
                    source_crs TEXT NOT NULL,
                    footprint_wkt TEXT NOT NULL,
                    footprint_bbox_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    batch_id TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    capture_ts TEXT,
                    gps_lat REAL,
                    gps_lon REAL,
                    projected_x REAL,
                    projected_y REAL,
                    matched_area_id INTEGER,
                    match_mode TEXT,
                    proposed_filename TEXT,
                    applied INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE rename_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    batch_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    summary_json TEXT NOT NULL,
                    results_json TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT INTO projects (id, name, storage_root, crs, created_at, updated_at)
                VALUES (1, 'Legacy Project', '.', 'EPSG:26912', 'now', 'now')
                """
            )
            conn.execute(
                """
                INSERT INTO areas (
                    project_id, name, dxf_original_path, dxf_managed_path, source_crs,
                    footprint_wkt, footprint_bbox_json, active, created_at, updated_at
                )
                VALUES (1, 'Area A', '', '', 'EPSG:26912', 'POLYGON EMPTY', '[]', 1, 'now', 'now')
                """
            )
            conn.execute(
                """
                INSERT INTO photos (
                    project_id, batch_id, original_path, capture_ts, gps_lat, gps_lon,
                    projected_x, projected_y, matched_area_id, match_mode, proposed_filename,
                    applied, error, created_at, updated_at
                )
                VALUES (1, 'legacy-batch', '/tmp/one.jpg', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, NULL, '2026-01-01T00:00:00', '2026-01-01T00:01:00')
                """
            )
            conn.execute(
                """
                INSERT INTO photos (
                    project_id, batch_id, original_path, capture_ts, gps_lat, gps_lon,
                    projected_x, projected_y, matched_area_id, match_mode, proposed_filename,
                    applied, error, created_at, updated_at
                )
                VALUES (1, 'applied-batch', '/tmp/two.jpg', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, NULL, '2026-01-02T00:00:00', '2026-01-02T00:01:00')
                """
            )
            conn.execute(
                """
                INSERT INTO rename_runs (project_id, batch_id, started_at, completed_at, summary_json, results_json)
                VALUES (1, 'legacy-run', 'now', NULL, '{}', '[]')
                """
            )
            conn.commit()
            conn.close()

            db = Database(db_path)
            db.initialize()

            with db.connect() as upgraded_conn:
                self.assertIn("display_color", self.table_columns(upgraded_conn, "areas"))
                self.assertIn("content_hash", self.table_columns(upgraded_conn, "photos"))
                self.assertIn("photo_batch_id", self.table_columns(upgraded_conn, "photos"))
                self.assertIn("rollback_started_at", self.table_columns(upgraded_conn, "rename_runs"))
                self.assertIn("rollback_completed_at", self.table_columns(upgraded_conn, "rename_runs"))
                self.assertIn("rollback_results_json", self.table_columns(upgraded_conn, "rename_runs"))
                self.assertIn("next_sequence_number", self.table_columns(upgraded_conn, "rename_sequence_counters"))
                self.assertIn("reservation_status", self.table_columns(upgraded_conn, "filename_reservations"))
                self.assertIn("username", self.table_columns(upgraded_conn, "users"))
                self.assertEqual(self.migration_versions(upgraded_conn), sorted(version for version, _ in MIGRATIONS))
                self.assertIn("20260511_0006_filename_reservations", self.migration_versions(upgraded_conn))
                self.assert_expected_indexes_exist(upgraded_conn)
                reservation_count = upgraded_conn.execute("SELECT COUNT(*) AS count FROM filename_reservations").fetchone()["count"]
                counter_count = upgraded_conn.execute("SELECT COUNT(*) AS count FROM rename_sequence_counters").fetchone()["count"]

                area_row = upgraded_conn.execute("SELECT name, display_color FROM areas WHERE id = 1").fetchone()
                photo_row = upgraded_conn.execute("SELECT original_path, content_hash, photo_batch_id FROM photos WHERE id = 1").fetchone()
                batch_rows = upgraded_conn.execute(
                    "SELECT * FROM photo_batches ORDER BY batch_uid"
                ).fetchall()
                run_row = upgraded_conn.execute(
                    """
                    SELECT batch_id, rollback_started_at, rollback_completed_at, rollback_results_json
                    FROM rename_runs WHERE id = 1
                    """
                ).fetchone()

            self.assertEqual(area_row["name"], "Area A")
            self.assertTrue(area_row["display_color"].startswith("#"))
            self.assertEqual(photo_row["original_path"], "/tmp/one.jpg")
            self.assertIsNone(photo_row["content_hash"])
            self.assertIsNotNone(photo_row["photo_batch_id"])
            self.assertEqual([row["batch_uid"] for row in batch_rows], ["applied-batch", "legacy-batch"])
            batches_by_uid = {row["batch_uid"]: row for row in batch_rows}
            self.assertEqual(batches_by_uid["legacy-batch"]["source_kind"], "legacy")
            self.assertEqual(batches_by_uid["legacy-batch"]["status"], "imported")
            self.assertEqual(batches_by_uid["legacy-batch"]["photo_count"], 1)
            self.assertIsNone(batches_by_uid["legacy-batch"]["completed_at"])
            self.assertEqual(batches_by_uid["applied-batch"]["status"], "applied")
            self.assertEqual(batches_by_uid["applied-batch"]["completed_at"], "2026-01-02T00:01:00")
            self.assertEqual(run_row["batch_id"], "legacy-run")
            self.assertIsNone(run_row["rollback_started_at"])
            self.assertIsNone(run_row["rollback_completed_at"])
            self.assertIsNone(run_row["rollback_results_json"])
            self.assertEqual(reservation_count, 0)
            self.assertEqual(counter_count, 0)

    def test_photo_batch_backfill_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    storage_root TEXT NOT NULL,
                    crs TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    batch_id TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    capture_ts TEXT,
                    gps_lat REAL,
                    gps_lon REAL,
                    projected_x REAL,
                    projected_y REAL,
                    matched_area_id INTEGER,
                    match_mode TEXT,
                    proposed_filename TEXT,
                    applied INTEGER NOT NULL DEFAULT 0,
                    content_hash TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT INTO projects (id, name, storage_root, crs, created_at, updated_at)
                VALUES (1, 'Legacy Project', '.', 'EPSG:26912', 'now', 'now')
                """
            )
            conn.executemany(
                """
                INSERT INTO photos (
                    project_id, batch_id, original_path, applied, created_at, updated_at
                )
                VALUES (1, 'legacy-batch', ?, 0, '2026-01-01T00:00:00', '2026-01-01T00:01:00')
                """,
                [('/tmp/one.jpg',), ('/tmp/two.jpg',)],
            )
            conn.commit()
            conn.close()

            db = Database(db_path)
            db.initialize()
            db.initialize()

            with db.connect() as upgraded_conn:
                batches = upgraded_conn.execute("SELECT * FROM photo_batches").fetchall()
                photos = upgraded_conn.execute("SELECT photo_batch_id FROM photos ORDER BY id").fetchall()

            self.assertEqual(len(batches), 1)
            self.assertEqual(batches[0]["batch_uid"], "legacy-batch")
            self.assertEqual(batches[0]["photo_count"], 2)
            self.assertEqual({row["photo_batch_id"] for row in photos}, {batches[0]["id"]})


if __name__ == "__main__":
    unittest.main()
