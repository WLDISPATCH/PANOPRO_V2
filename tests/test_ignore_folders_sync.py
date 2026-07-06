from __future__ import annotations

import json
import unittest
import urllib.parse
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pano_namer.config import AppConfig
from pano_namer.database import Database
from pano_namer.services import ignore_folders_sync, smart_mode
from pano_namer.services.common import utc_now
from pano_namer.services.shared_naming import (
    SharedNamingSettings,
    save_settings as save_naming_settings,
)


class FakeSharedSmartSettings:
    """In-memory stand-in for the shared_smart_settings table."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def request(self, method: str, url: str, headers: dict, body: bytes | None):
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if "/rest/v1/shared_smart_settings" not in parsed.path:
            return 500, b""
        if method == "GET":
            key = params.get("key", "").removeprefix("eq.")
            rows = [r for r in self.rows.values() if r["key"] == key]
            return 200, json.dumps(rows).encode("utf-8")
        if method == "POST":
            for row in json.loads(body or b"[]"):
                self.rows[row["key"]] = row
            return 201, b""
        return 500, b""


class IgnoreFoldersSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name)
        self.config = AppConfig.load(base)
        self.db = Database(self.config.db_path)
        self.db.initialize()
        with self.db.connect() as conn:
            save_naming_settings(
                conn,
                SharedNamingSettings(
                    enabled=True,
                    supabase_url="https://example.supabase.co",
                    supabase_anon_key="anon-key",
                    computer_name="MACHINE-A",
                ),
            )
            conn.commit()
        self.fake = FakeSharedSmartSettings()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _set_local(self, folders: list[str], updated_at: str) -> None:
        with self.db.connect() as conn:
            settings = smart_mode.load_settings(conn)
            settings.ignore_folders = folders
            settings.ignore_folders_updated_at = updated_at
            smart_mode.save_settings(conn, settings)
            conn.commit()

    def _local(self) -> smart_mode.SmartModeSettings:
        with self.db.connect() as conn:
            return smart_mode.load_settings(conn)

    def test_local_edit_pushes_to_remote(self) -> None:
        self._set_local(["RAW", "TILES"], utc_now())
        with patch.object(ignore_folders_sync, "_request", self.fake.request):
            result = ignore_folders_sync.run_ignore_folders_sync(self.db)
        self.assertTrue(result["ok"])
        self.assertEqual(result["direction"], "pushed")
        self.assertEqual(self.fake.rows["ignore_folders"]["value"], ["RAW", "TILES"])

    def test_newer_remote_pulls_into_local(self) -> None:
        # Local set earlier; remote set later -> remote wins.
        self._set_local(["OLD"], "2026-07-01T00:00:00+00:00")
        self.fake.rows["ignore_folders"] = {
            "key": "ignore_folders",
            "value": ["RAW", "WORKING"],
            "computer_name": "MACHINE-B",
            "updated_at": "2026-07-05T00:00:00+00:00",
        }
        with patch.object(ignore_folders_sync, "_request", self.fake.request):
            result = ignore_folders_sync.run_ignore_folders_sync(self.db)
        self.assertEqual(result["direction"], "pulled")
        self.assertEqual(self._local().ignore_folders, ["RAW", "WORKING"])

    def test_never_edited_machine_pulls_and_does_not_clobber(self) -> None:
        # No local timestamp: must pull, never push an empty default over remote.
        self.fake.rows["ignore_folders"] = {
            "key": "ignore_folders",
            "value": ["RAW"],
            "computer_name": "MACHINE-B",
            "updated_at": "2026-07-05T00:00:00+00:00",
        }
        with patch.object(ignore_folders_sync, "_request", self.fake.request):
            result = ignore_folders_sync.run_ignore_folders_sync(self.db)
        self.assertEqual(result["direction"], "pulled")
        self.assertEqual(self._local().ignore_folders, ["RAW"])

    def test_unconfigured_supabase_is_noop(self) -> None:
        with self.db.connect() as conn:
            save_naming_settings(conn, SharedNamingSettings())  # blank config
            conn.commit()
        self._set_local(["RAW"], utc_now())
        result = ignore_folders_sync.run_ignore_folders_sync(self.db)
        self.assertFalse(result["ok"])
        self.assertEqual(result["direction"], "none")


if __name__ == "__main__":
    unittest.main()
