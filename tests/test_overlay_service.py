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
