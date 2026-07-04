from __future__ import annotations

import unittest

from pathlib import Path

from pano_namer.services.overlay import (
    _extract_lgi_registration,
    _extract_pdf_arrays,
    _extract_pdf_viewport_bbox,
    _pdf_bounds_from_gpts,
    parse_overlay_metadata,
)


class OverlayServiceTests(unittest.TestCase):
    def test_extracts_pdf_control_point_arrays(self) -> None:
        raw = "/LPTS [0 0 0 1 1 1 1 0]\n/GPTS [49 -113 49 -112 48 -112 48 -113]"
        lpts, gpts = _extract_pdf_arrays(raw)
        self.assertEqual(lpts, [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0])
        self.assertEqual(gpts, [49.0, -113.0, 49.0, -112.0, 48.0, -112.0, 48.0, -113.0])

    def test_extracts_iso_geopdf_viewport_bbox(self) -> None:
        raw = """
        /VP[<</Type /Viewport/BBox [71.647201538 72.000137329 4824 4824]
        /Measure<</Type /Measure/Subtype /GEO>>>>]
        """
        bbox = _extract_pdf_viewport_bbox(raw)
        self.assertEqual(bbox, [71.647201538, 72.000137329, 4824.0, 4824.0])

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

    def test_crops_iso_geopdf_preview_to_viewport_bbox(self) -> None:
        import shutil

        import fitz
        from PIL import Image

        work_dir = Path.home() / ".tmp" / "panopro-tests" / self._testMethodName
        work_dir.mkdir(parents=True, exist_ok=True)
        source = work_dir / "viewport.pdf"
        preview_dir = work_dir / "previews"
        try:
            document = fitz.open()
            page = document.new_page(width=200, height=200)
            page.draw_rect(
                fitz.Rect(0, 0, 200, 200), color=(1, 0, 0), fill=(1, 0, 0)
            )
            page.draw_rect(
                fitz.Rect(50, 40, 150, 140), color=(0, 1, 0), fill=(0, 1, 0)
            )
            document.save(source)
            document.close()
            source.write_bytes(
                source.read_bytes()
                + b"\n/VP[<</Type /Viewport/BBox [50 60 150 160]/Measure<</Type /Measure/Subtype /GEO"
                + b"/Bounds [0 0 0 1 1 1 1 0 0 0]"
                + b"/GPTS [459000 6353000 459000 6353100 459100 6353100 459100 6353000]"
                + b"/LPTS [0 0 0 1 1 1 1 0]>>>>]\n"
            )

            preview_path, _crs, bounds, width, height, error = parse_overlay_metadata(
                source, preview_dir
            )

            self.assertIsNone(error)
            self.assertEqual(bounds, [459000.0, 6353000.0, 459100.0, 6353100.0])
            self.assertIsNotNone(width)
            self.assertIsNotNone(height)
            self.assertLess(width or 0, 420)
            self.assertLess(height or 0, 420)
            with Image.open(preview_path) as image:
                self.assertEqual(image.size, (width, height))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

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
