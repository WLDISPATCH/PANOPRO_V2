from __future__ import annotations

import unittest

from pathlib import Path

from pano_namer.services.overlay import _extract_lgi_registration, _extract_pdf_arrays, _pdf_bounds_from_gpts, parse_overlay_metadata


class OverlayServiceTests(unittest.TestCase):
    def test_extracts_pdf_control_point_arrays(self) -> None:
        raw = "/LPTS [0 0 0 1 1 1 1 0]\n/GPTS [49 -113 49 -112 48 -112 48 -113]"
        lpts, gpts = _extract_pdf_arrays(raw)
        self.assertEqual(lpts, [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0])
        self.assertEqual(gpts, [49.0, -113.0, 49.0, -112.0, 48.0, -112.0, 48.0, -113.0])

    def test_projects_lat_lon_gpts_into_epsg_26912_bounds(self) -> None:
        bounds = _pdf_bounds_from_gpts([49.0, -113.0, 49.0, -112.0, 48.0, -112.0, 48.0, -113.0])
        self.assertEqual(len(bounds), 4)
        self.assertLess(bounds[0], bounds[2])
        self.assertLess(bounds[1], bounds[3])

    def test_extracts_global_mapper_registration_bounds(self) -> None:
        raw = """
        /Registration [ [ (0.000000000000) (0.000000000000) (458935.938941347704) (6352796.606671723537) ]
        [ (612.000000000000) (792.000000000000) (476355.061058652296) (6375339.000000000000) ] ]
        /Type /LGIDict
        """
        bounds = _extract_lgi_registration(raw)
        self.assertIsNotNone(bounds)
        self.assertAlmostEqual(bounds[0], 458935.9389413477)
        self.assertAlmostEqual(bounds[1], 6352796.606671723)
        self.assertAlmostEqual(bounds[2], 476355.0610586523)
        self.assertAlmostEqual(bounds[3], 6375339.0)

    def test_parses_real_global_mapper_pdf_metadata(self) -> None:
        path = Path(r"d:\Inline Group Inc. Dropbox\PROJECTS\19001_SUNCOR_FORT HILLS\UAV\MISC - Documents & MISC Files\TEMP FLIGHTS\MAPS\Sat imagery\260124_SAT_260215_DRONE_2M.pdf")
        if not path.exists():
            self.skipTest("Real overlay PDF not available on this machine.")
        preview_path, crs, bounds, width, height, error = parse_overlay_metadata(path)
        self.assertIsNone(error)
        self.assertEqual(crs, "EPSG:26912")
        self.assertTrue(preview_path.exists())
        self.assertEqual(preview_path.suffix.lower(), ".png")
        self.assertIsNotNone(bounds)
        self.assertGreater(width or 0, 0)
        self.assertGreater(height or 0, 0)


if __name__ == "__main__":
    unittest.main()


class OverlayRasterSizeCapTests(unittest.TestCase):
    def test_pdf_preview_capped_to_gpu_safe_size(self) -> None:
        import tempfile

        import fitz

        from pano_namer.services.overlay import (
            MAX_OVERLAY_PIXEL_DIMENSION,
            _render_pdf_preview,
        )

        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            # 100x60 inch sheet: at 150 dpi this would be 15000px wide.
            document = fitz.open()
            document.new_page(width=100 * 72, height=60 * 72)
            pdf_path = temp_dir / "huge_plan.pdf"
            document.save(pdf_path)
            document.close()

            _, width, height = _render_pdf_preview(pdf_path, temp_dir / "previews")
            self.assertLessEqual(max(width, height), MAX_OVERLAY_PIXEL_DIMENSION)
            self.assertGreater(width, height)

    def test_startup_downscales_existing_oversized_overlay(self) -> None:
        import tempfile

        from PIL import Image

        from pano_namer.database import Database
        from pano_namer.services.common import utc_now
        from pano_namer.services.overlay import (
            MAX_OVERLAY_PIXEL_DIMENSION,
            normalize_oversized_overlay_rasters,
        )

        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            big_png = temp_dir / "overlay.png"
            Image.new("RGB", (6000, 3000), color=(200, 210, 220)).save(big_png)

            db = Database(temp_dir / "test.db")
            db.initialize()
            with db.connect() as conn:
                now = utc_now()
                conn.execute(
                    "INSERT INTO projects (id, name, storage_root, crs, created_at, updated_at) VALUES (1, 'T', ?, 'EPSG:26912', ?, ?)",
                    (str(temp_dir), now, now),
                )
                conn.execute(
                    """
                    INSERT INTO overlays (
                        project_id, jpg_original_path, jpg_managed_path,
                        width, height, active, created_at, updated_at
                    ) VALUES (1, ?, ?, 6000, 3000, 1, ?, ?)
                    """,
                    (str(big_png), str(big_png), now, now),
                )
                conn.commit()

            fixed = normalize_oversized_overlay_rasters(db)
            self.assertEqual(fixed, 1)
            with Image.open(big_png) as image:
                self.assertLessEqual(max(image.size), MAX_OVERLAY_PIXEL_DIMENSION)
            with db.connect() as conn:
                row = conn.execute("SELECT width, height FROM overlays").fetchone()
            self.assertEqual(row["width"], MAX_OVERLAY_PIXEL_DIMENSION)
            self.assertEqual(row["height"], MAX_OVERLAY_PIXEL_DIMENSION // 2)

            # Second run is a no-op.
            self.assertEqual(normalize_oversized_overlay_rasters(db), 0)
