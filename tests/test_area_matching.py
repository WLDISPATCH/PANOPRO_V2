from __future__ import annotations

import unittest

from shapely.geometry import MultiPolygon, Point, Polygon

from pano_namer.services.matching import choose_area_match, containment_area_for_point


class AreaMatchingTests(unittest.TestCase):
    def test_prefers_smallest_containing_polygon(self) -> None:
        point = Point(5, 5)
        areas = [
            {"id": 1, "geometry": Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])},
            {"id": 2, "geometry": Polygon([(2, 2), (10, 2), (10, 10), (2, 10)])},
        ]

        match, mode = choose_area_match(point, areas)

        self.assertEqual(mode, "inside")
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 2)

    def test_prefers_smallest_containing_part_for_grouped_area(self) -> None:
        point = Point(5, 5)
        grouped = MultiPolygon(
            [
                Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                Polygon([(100, 100), (160, 100), (160, 160), (100, 160)]),
            ]
        )
        other = Polygon([(-2, -2), (20, -2), (20, 20), (-2, 20)])

        grouped_area = containment_area_for_point(grouped, point)
        other_area = containment_area_for_point(other, point)

        self.assertEqual(grouped_area, 100.0)
        self.assertEqual(other_area, 484.0)

        match, mode = choose_area_match(
            point,
            [
                {"id": 10, "geometry": other},
                {"id": 20, "geometry": grouped},
            ],
        )

        self.assertEqual(mode, "inside")
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 20)

    def test_falls_back_to_nearest_when_point_is_outside_all_areas(self) -> None:
        point = Point(50, 50)
        areas = [
            {"id": 1, "geometry": Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])},
            {"id": 2, "geometry": Polygon([(60, 60), (70, 60), (70, 70), (60, 70)])},
        ]

        match, mode = choose_area_match(point, areas)

        self.assertEqual(mode, "nearest")
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 2)


if __name__ == "__main__":
    unittest.main()
