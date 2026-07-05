from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

import pytest

from pano_namer.database import Database
from pano_namer.services import pano_registry, sd_card, smart_mode


def _xmp_app1(xmp_body: str) -> bytes:
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp_body.encode("utf-8")
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _sof0(width: int, height: int) -> bytes:
    body = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xc0" + struct.pack(">H", len(body) + 2) + body


def make_jpeg(
    path: Path,
    width: int,
    height: int,
    xmp_body: str | None = None,
) -> Path:
    data = b"\xff\xd8"
    if xmp_body is not None:
        data += _xmp_app1(xmp_body)
    data += _sof0(width, height)
    data += b"\xff\xd9"
    path.write_bytes(data)
    return path


PANO_XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
    'GPano:ProjectionType="equirectangular" '
    'drone-dji:GpsLatitude="+57.407221220" '
    'drone-dji:GpsLongitude="-111.606763741" '
    'xmp:CreateDate="2026-03-16T12:00:04-06:00"/>'
    "</rdf:RDF></x:xmpmeta>"
)


class TestPanoClassification:
    def test_gpano_equirectangular_is_pano(self, tmp_path):
        photo = make_jpeg(tmp_path / "a.jpg", 1000, 750, PANO_XMP)
        assert sd_card.is_stitched_pano(photo) is True

    def test_two_to_one_ratio_fallback_is_pano(self, tmp_path):
        photo = make_jpeg(tmp_path / "b.jpg", 8192, 4096)
        assert sd_card.is_stitched_pano(photo) is True

    def test_normal_photo_is_not_pano(self, tmp_path):
        photo = make_jpeg(tmp_path / "c.jpg", 4000, 3000)
        assert sd_card.is_stitched_pano(photo) is False

    def test_small_two_to_one_is_not_pano(self, tmp_path):
        photo = make_jpeg(tmp_path / "d.jpg", 2000, 1000)
        assert sd_card.is_stitched_pano(photo) is False

    def test_non_jpeg_is_not_pano(self, tmp_path):
        path = tmp_path / "e.jpg"
        path.write_bytes(b"not a jpeg")
        assert sd_card.is_stitched_pano(path) is False


class TestScanForPanos:
    def test_scan_separates_panos_from_normals(self, tmp_path):
        dcim = tmp_path / "DCIM" / "DJI_001"
        dcim.mkdir(parents=True)
        make_jpeg(dcim / "DJI_0001_PANO.jpg", 14400, 7200, PANO_XMP)
        make_jpeg(dcim / "DJI_0002.jpg", 4000, 3000)
        make_jpeg(dcim / "DJI_0003.jpg", 4000, 3000)

        result = sd_card.scan_for_panos(tmp_path)

        assert len(result.panos) == 1
        assert result.skipped_normal == 2
        pano = result.panos[0]
        assert pano.original_name == "DJI_0001_PANO.jpg"
        assert pano.gps_lat == pytest.approx(57.407221220)
        assert pano.gps_lon == pytest.approx(-111.606763741)
        assert pano.capture_ts == "2026-03-16T12:00:04-06:00"

    def test_scan_without_dcim_scans_folder_directly(self, tmp_path):
        make_jpeg(tmp_path / "pano.jpg", 14400, 7200, PANO_XMP)
        result = sd_card.scan_for_panos(tmp_path)
        assert len(result.panos) == 1


class TestRegistryDuplicates:
    ROWS = [
        {
            "original_name": "DJI_0001_PANO.jpg",
            "gps_lat": 57.407221,
            "gps_lon": -111.606764,
        },
        {"original_name": "DJI_0009_PANO.jpg", "gps_lat": None, "gps_lon": None},
    ]

    def test_same_name_and_position_is_duplicate(self):
        assert pano_registry.is_registered_duplicate(
            self.ROWS, "DJI_0001_PANO.jpg", 57.407223, -111.606766
        )

    def test_same_name_far_away_is_not_duplicate(self):
        assert not pano_registry.is_registered_duplicate(
            self.ROWS, "DJI_0001_PANO.jpg", 57.5, -111.7
        )

    def test_different_name_is_not_duplicate(self):
        assert not pano_registry.is_registered_duplicate(
            self.ROWS, "DJI_0002_PANO.jpg", 57.407221, -111.606764
        )

    def test_row_without_gps_matches_on_name_alone(self):
        assert pano_registry.is_registered_duplicate(
            self.ROWS, "DJI_0009_PANO.jpg", 57.0, -111.0
        )


class TestSmartModeSettings:
    @pytest.fixture()
    def conn(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.initialize()
        connection = sqlite3.connect(db.path)
        connection.row_factory = sqlite3.Row
        yield connection
        connection.close()

    def test_defaults(self, conn):
        settings = smart_mode.load_settings(conn)
        assert settings.ui_mode == "advanced"
        assert settings.ftp_protocol == "ftp"
        assert settings.resolved_port() == 21
        assert not settings.ftp_configured()
        assert not settings.ftp_enabled

    def test_roundtrip(self, conn):
        settings = smart_mode.SmartModeSettings(
            ui_mode="smart",
            import_base_path=r"D:\Panos",
            archive_base_path=r"D:\PanoArchive",
            ftp_host="ftp.example.com",
            ftp_port=2121,
            ftp_username="user",
            ftp_password="secret",
            ftp_remote_path="/panos",
            ftp_protocol="sftp",
            ftp_enabled=True,
        )
        smart_mode.save_settings(conn, settings)
        conn.commit()
        loaded = smart_mode.load_settings(conn)
        assert loaded == settings
        assert loaded.ftp_configured()

    def test_sftp_default_port(self, conn):
        settings = smart_mode.SmartModeSettings(ftp_protocol="sftp")
        assert settings.resolved_port() == 22
        settings.ftp_port = 2222
        assert settings.resolved_port() == 2222

    def test_unknown_protocol_falls_back_to_ftp(self, conn):
        settings = smart_mode.SmartModeSettings(ftp_protocol="gopher")
        smart_mode.save_settings(conn, settings)
        conn.commit()
        assert smart_mode.load_settings(conn).ftp_protocol == "ftp"


class TestBatchImportFiltersRawPhotos:
    def test_folder_import_skips_raw_tiles(self, tmp_path):
        from fastapi.testclient import TestClient

        from pano_namer.config import AppConfig
        from pano_namer.main import create_app

        config = AppConfig.load(tmp_path / "data")
        app = create_app(config)
        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "BATCH-FILTER"}).json()

        # A card-like folder: one stitched pano plus raw tiles in PANORAMA.
        card = tmp_path / "card" / "DCIM" / "DJI_001"
        pano_dir = card / "PANORAMA"
        pano_dir.mkdir(parents=True)
        make_jpeg(card / "DJI_0001_PANO.jpg", 14400, 7200, PANO_XMP)
        make_jpeg(pano_dir / "DJI_0002.jpg", 4000, 3000)
        make_jpeg(pano_dir / "DJI_0003.jpg", 4000, 3000)

        result = client.post(
            f"/api/projects/{project['id']}/photos/import",
            json={"paths": [str(tmp_path / "card")]},
        ).json()
        assert result["summary"]["imported"] == 1
        assert result["summary"]["non_pano_skipped"] == 2

        # Explicitly selected files are still trusted as-is.
        explicit = client.post(
            f"/api/projects/{project['id']}/photos/import",
            json={"paths": [str(pano_dir / "DJI_0002.jpg")]},
        ).json()
        assert explicit["summary"]["imported"] == 1
        assert explicit["summary"]["non_pano_skipped"] == 0


class TestSmartExportArchiveLayout:
    def test_archive_moves_files_into_dated_panos_folder(self, tmp_path):
        from fastapi.testclient import TestClient

        from pano_namer.config import AppConfig
        from pano_namer.main import create_app
        from pano_namer.services.common import utc_now
        from pano_namer.services.shared_naming import (
            SharedNamingSettings,
            save_settings,
        )

        config = AppConfig.load(tmp_path / "data")
        app = create_app(config)
        client = TestClient(app)

        project = client.post("/api/projects", json={"name": "EXPORT-LAYOUT"}).json()

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        renamed = work_dir / "260316_CP_001.jpg"
        renamed.write_bytes(b"\xff\xd8\xff\xd9")
        archive_base = tmp_path / "archive"

        db = Database(config.db_path)
        with db.connect() as conn:
            now = utc_now()
            # Photo already renamed + registered; only the archive phase runs
            # (upload stays off), which is the folder layout under test.
            conn.execute(
                """
                INSERT INTO photos (
                    project_id, batch_id, original_path, capture_ts,
                    proposed_filename, applied, smart_original_name,
                    upload_status, created_at, updated_at
                )
                VALUES (?, 'b1', ?, '2026-03-16T12:00:04-06:00',
                        '260316_CP_001.jpg', 1, 'DJI_0001_PANO.jpg',
                        'registered', ?, ?)
                """,
                (project["id"], str(renamed), now, now),
            )
            save_settings(
                conn,
                SharedNamingSettings(
                    supabase_url="https://fake.supabase.co",
                    supabase_anon_key="anon",
                ),
            )
            smart_mode.save_settings(
                conn,
                smart_mode.SmartModeSettings(
                    archive_base_path=str(archive_base), ftp_enabled=False
                ),
            )
            conn.commit()

        response = client.post("/api/smart/export", json={"project_id": project["id"]})
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary["archived"] == 1, summary

        expected = archive_base / "260316" / "PANOS" / "260316_CP_001.jpg"
        assert expected.exists()
        assert not renamed.exists()


class TestSmartModeMigration:
    def test_photos_table_gains_smart_columns(self, tmp_path):
        db = Database(tmp_path / "migrated.db")
        db.initialize()
        with db.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(photos)").fetchall()
            }
        assert {
            "is_panorama",
            "smart_original_name",
            "upload_status",
            "uploaded_at",
        } <= columns
