from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from uuid import uuid4

from pano_namer.database import Database
from pano_namer.main import resolve_area_color


TEST_TMP_ROOT = Path(".test_tmp")


class AreaColorSupportTests(unittest.TestCase):
    def test_database_migration_backfills_missing_area_colors(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEST_TMP_ROOT / f"area_color_{uuid4().hex}"
        temp_dir.mkdir(exist_ok=True)
        db_path = temp_dir / "legacy.db"

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
            """
        )
        conn.execute(
            "INSERT INTO projects (id, name, storage_root, crs, created_at, updated_at) VALUES (1, 'Legacy', '.', 'EPSG:26912', 'now', 'now')"
        )
        conn.execute(
            """
            INSERT INTO areas (
                project_id, name, dxf_original_path, dxf_managed_path, source_crs,
                footprint_wkt, footprint_bbox_json, active, created_at, updated_at
            )
            VALUES
                (1, 'Area A', '', '', 'EPSG:26912', 'POLYGON EMPTY', '[]', 1, 'now', 'now'),
                (1, 'Area B', '', '', 'EPSG:26912', 'POLYGON EMPTY', '[]', 1, 'now', 'now')
            """
        )
        conn.commit()
        conn.close()

        Database(db_path).initialize()

        with Database(db_path).connect() as conn2:
            rows = conn2.execute("SELECT display_color FROM areas ORDER BY id ASC").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["display_color"].startswith("#"))
        self.assertTrue(rows[1]["display_color"].startswith("#"))
        self.assertNotEqual(rows[0]["display_color"], rows[1]["display_color"])

    def test_resolve_area_color_honors_manual_color_and_generates_next_default(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEST_TMP_ROOT / f"area_color_{uuid4().hex}"
        temp_dir.mkdir(exist_ok=True)
        db = Database(temp_dir / "app.db")
        db.initialize()

        with db.connect() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, storage_root, crs, created_at, updated_at) VALUES (1, 'Project', '.', 'EPSG:26912', 'now', 'now')"
            )
            conn.execute(
                """
                INSERT INTO areas (
                    project_id, name, dxf_original_path, dxf_managed_path, display_color, source_crs,
                    footprint_wkt, footprint_bbox_json, active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (1, "Area A", "", "", "#175c4c", "EPSG:26912", "POLYGON EMPTY", "[]", "now", "now"),
            )

            generated = resolve_area_color(conn, 1, None)
            manual = resolve_area_color(conn, 1, "#FF6600")

        self.assertNotEqual(generated, "#175c4c")
        self.assertEqual(manual, "#ff6600")


if __name__ == "__main__":
    unittest.main()
