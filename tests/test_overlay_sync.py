from __future__ import annotations

import json
import unittest
import urllib.parse
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from pano_namer.config import AppConfig
from pano_namer.database import Database
from pano_namer.services import overlay_sync
from pano_namer.services.common import utc_now
from pano_namer.services.shared_naming import (
    SharedNamingSettings,
    save_settings as save_naming_settings,
)
from pano_namer.services.storage import StorageService


class FakeSupabase:
    """In-memory stand-in for the shared_overlays table + overlay-files bucket."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}

    def request(self, method, url, headers, body):
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if "/rest/v1/shared_overlays" in parsed.path:
            if method == "GET":
                tn = params.get("template_name", "").removeprefix("eq.")
                rows = [r for r in self.rows.values() if r["template_name"] == tn]
                return 200, json.dumps(rows).encode("utf-8")
            if method == "POST":
                for row in json.loads(body or b"[]"):
                    self.rows[row["uid"]] = row
                return 201, b""
        if "/storage/v1/object/overlay-files/" in parsed.path:
            key = urllib.parse.unquote(
                parsed.path.split("/storage/v1/object/overlay-files/", 1)[1]
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


BOUNDS = "[500000.0, 6300000.0, 500200.0, 6300200.0]"


class OverlaySyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name)
        self.config = AppConfig.load(base)
        self.config.ensure_dirs()
        self.db = Database(self.config.db_path)
        self.db.initialize()
        self.storage = StorageService(self.config)
        with self.db.connect() as conn:
            save_naming_settings(
                conn,
                SharedNamingSettings(
                    enabled=True,
                    supabase_url="https://example.supabase.co",
                    supabase_anon_key="anon-key",
                    computer_name="MACHINE-A",
                    sync_areas=True,
                ),
            )
            conn.commit()
        self.fake = FakeSupabase()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_project(self, name: str) -> int:
        now = utc_now()
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO projects (name, storage_root, crs, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, str(self.config.data_dir), "EPSG:26912", now, now),
            )
            conn.commit()
            return cur.lastrowid

    def _make_overlay_image(self, project_id: int) -> Path:
        d = self.storage.project_dir(project_id) / "overlays"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"map_{uuid4().hex[:6]}.png"
        Image.new("RGB", (16, 16), (120, 160, 180)).save(path)
        return path

    def _insert_overlay(self, project_id: int, image: Path) -> int:
        now = utc_now()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO overlays (project_id, display_name, jpg_original_path, jpg_managed_path,
                    crs, bounds_json, width, height, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (project_id, "Site Map", str(image), str(image), "EPSG:26912", BOUNDS, 16, 16, now, now),
            )
            conn.commit()
            return cur.lastrowid

    def test_local_overlay_pushes_to_remote(self) -> None:
        pid = self._make_project("T")
        image = self._make_overlay_image(pid)
        overlay_id = self._insert_overlay(pid, image)
        with patch.object(overlay_sync, "_request", self.fake.request):
            result = overlay_sync.run_overlay_sync(self.db, self.storage, pid)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["pushed_new"], 1)
        self.assertEqual(len(self.fake.rows), 1)
        row = next(iter(self.fake.rows.values()))
        self.assertEqual(row["template_name"], "T")
        self.assertEqual(row["display_name"], "Site Map")
        self.assertEqual(len(self.fake.files), 1)  # image uploaded to the bucket
        with self.db.connect() as conn:
            sync_uid = conn.execute(
                "SELECT sync_uid FROM overlays WHERE id = ?", (overlay_id,)
            ).fetchone()["sync_uid"]
        self.assertTrue(sync_uid)

    def test_remote_overlay_pulls_and_creates_local(self) -> None:
        pid = self._make_project("T2")
        # Seed a remote overlay + its file.
        uid = uuid4().hex
        self.fake.files[f"t2/{uid}.png"] = _png_bytes()
        self.fake.rows[uid] = {
            "uid": uid,
            "template_name": "T2",
            "display_name": "Shared Map",
            "bounds_json": BOUNDS,
            "width": 16,
            "height": 16,
            "crs": "EPSG:26912",
            "file_ext": ".png",
            "file_hash": "abc",
            "file_path": f"t2/{uid}.png",
            "computer_name": "MACHINE-B",
            "updated_at": "2026-07-15T00:00:00+00:00",
            "deleted_at": None,
        }
        with patch.object(overlay_sync, "_request", self.fake.request):
            result = overlay_sync.run_overlay_sync(self.db, self.storage, pid)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["pulled_new"], 1)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT display_name, sync_uid, jpg_managed_path FROM overlays WHERE project_id = ?",
                (pid,),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["display_name"], "Shared Map")
        self.assertEqual(rows[0]["sync_uid"], uid)
        self.assertTrue(Path(rows[0]["jpg_managed_path"]).exists())

    def test_deleting_overlay_removes_file_from_bucket(self) -> None:
        pid = self._make_project("T")
        image = self._make_overlay_image(pid)
        overlay_id = self._insert_overlay(pid, image)
        with patch.object(overlay_sync, "_request", self.fake.request):
            overlay_sync.run_overlay_sync(self.db, self.storage, pid)  # push
            self.assertEqual(len(self.fake.files), 1)
            # Delete the overlay locally, then sync again.
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE overlays SET active = 0, updated_at = ? WHERE id = ?",
                    (utc_now(), overlay_id),
                )
                conn.commit()
            result = overlay_sync.run_overlay_sync(self.db, self.storage, pid)
        self.assertEqual(result["tombstoned"], 1)
        self.assertEqual(len(self.fake.files), 0)  # file removed, not orphaned
        row = self.fake.rows[next(iter(self.fake.rows))]
        self.assertIsNotNone(row["deleted_at"])  # tombstone row kept

    def test_noop_when_sync_disabled(self) -> None:
        pid = self._make_project("T3")
        with self.db.connect() as conn:
            save_naming_settings(conn, SharedNamingSettings())  # blank / disabled
            conn.commit()
        result = overlay_sync.run_overlay_sync(self.db, self.storage, pid)
        self.assertFalse(result["ok"])


def _png_bytes() -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
