from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pano_namer.config import AppConfig
from pano_namer.database import Database
from pano_namer.main import create_app
from pano_namer.services import pano_registry
from pano_namer.services.shared_naming import (
    SharedNamingSettings,
    SharedNamingUnavailableError,
    save_settings,
)


def _route(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FetchExportedPanosTests(unittest.TestCase):
    def test_builds_query_and_parses_rows(self) -> None:
        captured = {}

        def fake_request(method, url, headers, body):
            captured["method"] = method
            captured["url"] = url
            page = [
                {"final_name": "260702_OPTA_001", "computer_name": "PC-A",
                 "gps_lat": 57.0, "gps_lon": -111.0, "capture_ts": "2026-07-02T10:00:00"},
            ]
            return 200, json.dumps(page).encode("utf-8")

        settings = SharedNamingSettings(
            enabled=True, supabase_url="https://x.supabase.co", supabase_anon_key="k"
        )
        with patch.object(pano_registry, "_request", side_effect=fake_request):
            rows = pano_registry.fetch_exported_panos(settings)
        self.assertEqual(captured["method"], "GET")
        self.assertIn("pano_registry", captured["url"])
        self.assertIn("final_name=not.is.null", captured["url"])
        self.assertIn("is_panorama=eq.true", captured["url"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["final_name"], "260702_OPTA_001")

    def test_non_200_raises_unavailable(self) -> None:
        settings = SharedNamingSettings(
            enabled=True, supabase_url="https://x.supabase.co", supabase_anon_key="k"
        )
        with patch.object(pano_registry, "_request", return_value=(401, b"nope")):
            with self.assertRaises(SharedNamingUnavailableError):
                pano_registry.fetch_exported_panos(settings)


class CloudPanosRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.app = create_app(AppConfig.load(base))
        self.endpoint = _route(self.app, "/api/cloud-panos", "GET")
        with self.app.state.db.connect() as conn:
            save_settings(
                conn,
                SharedNamingSettings(
                    enabled=True,
                    supabase_url="https://x.supabase.co",
                    supabase_anon_key="k",
                    computer_name="THIS-PC",
                ),
            )
            conn.commit()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_excludes_own_and_projects_others(self) -> None:
        rows = [
            {"final_name": "260702_OPTA_001", "computer_name": "THIS-PC",
             "gps_lat": 57.0, "gps_lon": -111.0, "capture_ts": "2026-07-02T10:00:00"},
            {"final_name": "260702_OPTA_002", "computer_name": "OTHER-PC",
             "gps_lat": 57.01, "gps_lon": -111.01, "capture_ts": "2026-07-02T10:05:00"},
            {"final_name": "260702_OPTA_003", "computer_name": "OTHER-PC",
             "gps_lat": None, "gps_lon": None, "capture_ts": None},
        ]
        with patch.object(pano_registry, "fetch_exported_panos", return_value=rows):
            result = self.endpoint()
        self.assertTrue(result["ok"])
        self.assertTrue(result["connected"])
        # THIS-PC's own export is dropped; only the two OTHER-PC rows remain.
        self.assertEqual(len(result["panos"]), 2)
        self.assertTrue(all(p["computer_name"] == "OTHER-PC" for p in result["panos"]))
        self.assertTrue(all(not p["is_own"] for p in result["panos"]))
        first = result["panos"][0]
        # EPSG:26912 easting/northing for ~57N,-111W is ~500k / ~6.3M metres.
        self.assertAlmostEqual(first["projected_x"], 500000, delta=5000)
        self.assertGreater(first["projected_y"], 6_000_000)
        # Row with no GPS still listed, but with null projected coords.
        self.assertIsNone(result["panos"][1]["projected_x"])

    def test_offline_returns_not_ok_without_raising(self) -> None:
        with patch.object(
            pano_registry,
            "fetch_exported_panos",
            side_effect=SharedNamingUnavailableError("offline"),
        ):
            result = self.endpoint()
        self.assertFalse(result["ok"])
        self.assertFalse(result["connected"])
        self.assertIn("offline", result["error"])

    def test_unconfigured_returns_not_ok(self) -> None:
        with self.app.state.db.connect() as conn:
            save_settings(conn, SharedNamingSettings(enabled=False))
            conn.commit()
        result = self.endpoint()
        self.assertFalse(result["ok"])
        self.assertEqual(result["panos"], [])


if __name__ == "__main__":
    unittest.main()
