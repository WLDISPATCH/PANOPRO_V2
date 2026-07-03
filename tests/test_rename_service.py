from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from pano_namer.services.rename import apply_rename_plan, build_filename, plan_renames


TEST_TMP_ROOT = Path(".test_tmp")


class RenameServiceTests(unittest.TestCase):
    def test_build_filename_uses_required_template(self) -> None:
        name = build_filename("2026-03-14T12:00:00", "Lot 4 South", 2, ".JPG")
        self.assertEqual(name, "260314_LOT_4_SOUTH_002.jpg")

    def test_plan_renames_resolves_existing_collision(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        directory = TEST_TMP_ROOT / f"rename_{uuid4().hex}"
        directory.mkdir(exist_ok=True)
        first = directory / "PANO_001.JPG"
        second = directory / "PANO_002.JPG"
        existing = directory / "260314_LOT_1_001.jpg"
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        existing.write_bytes(b"reserved")

        plans = plan_renames(
            [
                {"id": 1, "original_path": str(first), "capture_ts": "2026-03-14T12:00:00", "area_name": "Lot 1"},
                {"id": 2, "original_path": str(second), "capture_ts": "2026-03-14T12:01:00", "area_name": "Lot 1"},
            ]
        )

        self.assertEqual([plan.final_name for plan in plans], ["260314_LOT_1_002.jpg", "260314_LOT_1_003.jpg"])

    def test_plan_renames_sequences_by_day_across_areas(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        directory = TEST_TMP_ROOT / f"rename_{uuid4().hex}"
        directory.mkdir(exist_ok=True)
        first = directory / "PANO_001.JPG"
        second = directory / "PANO_002.JPG"
        third = directory / "PANO_003.JPG"
        fourth = directory / "PANO_004.JPG"
        for path, payload in ((first, b"one"), (second, b"two"), (third, b"three"), (fourth, b"four")):
            path.write_bytes(payload)

        plans = plan_renames(
            [
                {"id": 1, "original_path": str(first), "capture_ts": "2026-03-10T12:00:00", "area_name": "Area A"},
                {"id": 2, "original_path": str(second), "capture_ts": "2026-03-10T12:01:00", "area_name": "Area B"},
                {"id": 3, "original_path": str(third), "capture_ts": "2026-03-12T12:00:00", "area_name": "Area A"},
                {"id": 4, "original_path": str(fourth), "capture_ts": "2026-03-12T12:01:00", "area_name": "Area B"},
            ]
        )

        self.assertEqual(
            [plan.final_name for plan in plans],
            [
                "260310_AREA_A_001.jpg",
                "260310_AREA_B_002.jpg",
                "260312_AREA_A_001.jpg",
                "260312_AREA_B_002.jpg",
            ],
        )

    def test_apply_rename_plan_moves_files(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        directory = TEST_TMP_ROOT / f"rename_{uuid4().hex}"
        directory.mkdir(exist_ok=True)
        source = directory / "capture.JPG"
        source.write_bytes(b"payload")
        plans = plan_renames(
            [
                {"id": 7, "original_path": str(source), "capture_ts": "2026-03-14T12:00:00", "area_name": "Area A"},
            ]
        )
        results = apply_rename_plan(plans)

        self.assertEqual(results[0]["status"], "renamed")
        self.assertFalse(source.exists())
        self.assertTrue((directory / "260314_AREA_A_001.jpg").exists())

    def test_apply_rename_plan_reports_missing_source(self) -> None:
        missing = Path(TEST_TMP_ROOT / f"missing_{uuid4().hex}" / "capture.JPG")
        plans = plan_renames(
            [
                {"id": 9, "original_path": str(missing), "capture_ts": "2026-03-14T12:00:00", "area_name": "Area A"},
            ]
        )
        results = apply_rename_plan(plans)

        self.assertEqual(results[0]["photo_id"], 9)
        self.assertEqual(results[0]["status"], "missing_source")

    def test_apply_rename_plan_keeps_photo_ids_for_multiple_renames(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        directory = TEST_TMP_ROOT / f"rename_{uuid4().hex}"
        directory.mkdir(exist_ok=True)
        first = directory / "capture_1.JPG"
        second = directory / "capture_2.JPG"
        first.write_bytes(b"one")
        second.write_bytes(b"two")

        plans = plan_renames(
            [
                {"id": 11, "original_path": str(first), "capture_ts": "2026-03-14T12:00:00", "area_name": "Area A"},
                {"id": 12, "original_path": str(second), "capture_ts": "2026-03-14T12:01:00", "area_name": "Area A"},
            ]
        )
        results = apply_rename_plan(plans)

        renamed_ids = sorted(result["photo_id"] for result in results if result["status"] == "renamed")
        self.assertEqual(renamed_ids, [11, 12])


if __name__ == "__main__":
    unittest.main()
