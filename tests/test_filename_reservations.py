from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pano_namer.database import Database
from pano_namer.services.reservations import reserve_filenames_for_photos


class FilenameReservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db = Database(self.root / "app.db")
        self.db.initialize()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (id, name, storage_root, crs, created_at, updated_at)
                VALUES (1, 'Reservation Project', ?, 'EPSG:26912', 'now', 'now')
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
            conn.execute(
                """
                INSERT INTO areas (id, project_id, name, dxf_original_path, dxf_managed_path, display_color,
                    source_crs, footprint_wkt, footprint_bbox_json, active, created_at, updated_at)
                VALUES (2, 1, 'Pond', '', '', '#dc3912', 'EPSG:26912', 'POLYGON EMPTY', '[]', 1, 'now', 'now')
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

    def pending_rows(self) -> list:
        with self.db.connect() as conn:
            return conn.execute(
                """
                SELECT photos.*, areas.name AS area_name
                FROM photos
                LEFT JOIN areas ON photos.matched_area_id = areas.id
                WHERE photos.project_id = 1 AND photos.applied = 0
                """
            ).fetchall()

    def reserve(self) -> list:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT photos.*, areas.name AS area_name
                FROM photos
                LEFT JOIN areas ON photos.matched_area_id = areas.id
                WHERE photos.project_id = 1 AND photos.applied = 0
                """
            ).fetchall()
            plans = reserve_filenames_for_photos(conn, 1, rows)
            reserved_ids = [plan.photo_id for plan in plans]
            if reserved_ids:
                placeholders = ",".join("?" for _ in reserved_ids)
                conn.execute(f"UPDATE photos SET applied = 1 WHERE id IN ({placeholders})", reserved_ids)
            conn.commit()
            return plans

    def test_reservation_sequences_by_project_date_and_area_scope(self) -> None:
        self.create_photo("a_002.jpg", "2026-03-14T12:02:00")
        self.create_photo("a_001.jpg", "2026-03-14T12:01:00")

        first_plans = self.reserve()

        self.assertEqual([plan.final_name for plan in first_plans], ["260314_DRAIN_001.jpg", "260314_DRAIN_002.jpg"])

        self.create_photo("b_001.jpg", "2026-03-14T13:01:00")
        second_plans = self.reserve()
        self.assertEqual([plan.final_name for plan in second_plans], ["260314_DRAIN_003.jpg"])

        self.create_photo("pond_001.jpg", "2026-03-14T14:01:00", area_id=2)
        area_plans = self.reserve()
        self.assertEqual([plan.final_name for plan in area_plans], ["260314_POND_001.jpg"])

        self.create_photo("next_day_001.jpg", "2026-03-15T14:01:00")
        date_plans = self.reserve()
        self.assertEqual([plan.final_name for plan in date_plans], ["260315_DRAIN_001.jpg"])

        with self.db.connect() as conn:
            reservations = conn.execute("SELECT * FROM filename_reservations ORDER BY id").fetchall()
            drain_counter = conn.execute(
                """
                SELECT next_sequence_number FROM rename_sequence_counters
                WHERE project_id = 1 AND capture_date = '2026-03-14' AND area_slug = 'DRAIN'
                """
            ).fetchone()
            pond_counter = conn.execute(
                """
                SELECT next_sequence_number FROM rename_sequence_counters
                WHERE project_id = 1 AND capture_date = '2026-03-14' AND area_slug = 'POND'
                """
            ).fetchone()

        self.assertEqual(len(reservations), 5)
        self.assertTrue(all(row["reservation_status"] == "reserved" for row in reservations))
        self.assertEqual(drain_counter["next_sequence_number"], 4)
        self.assertEqual(pond_counter["next_sequence_number"], 2)


if __name__ == "__main__":
    unittest.main()
