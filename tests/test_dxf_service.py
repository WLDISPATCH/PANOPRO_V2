from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

import ezdxf
from shapely import wkt

from pano_namer.services.dxf import build_manual_polygon_wkt, extract_area_geometry_wkt, read_dxf_crs


TEST_TMP_ROOT = Path(".test_tmp")


class DxfServiceTests(unittest.TestCase):
    def test_reads_epsg_metadata_from_text(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEST_TMP_ROOT / f"dxf_{uuid4().hex}"
        temp_dir.mkdir(exist_ok=True)
        path = temp_dir / "area.dxf"
        path.write_text("0\nSECTION\n999\nEPSG:26911\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
        self.assertEqual(read_dxf_crs(path), "EPSG:26911")

    def test_raises_when_epsg_missing(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEST_TMP_ROOT / f"dxf_{uuid4().hex}"
        temp_dir.mkdir(exist_ok=True)
        path = temp_dir / "area.dxf"
        path.write_text("0\nSECTION\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_dxf_crs(path)

    def test_extracts_polygon_from_kml(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEST_TMP_ROOT / f"kml_{uuid4().hex}"
        temp_dir.mkdir(exist_ok=True)
        path = temp_dir / "area.kml"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -111.0000,57.0000,0 -110.9990,57.0000,0 -110.9990,57.0010,0 -111.0000,57.0010,0 -111.0000,57.0000,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
""",
            encoding="utf-8",
        )
        geometry_wkt, bbox = extract_area_geometry_wkt(path)
        self.assertIn("POLYGON", geometry_wkt)
        self.assertEqual(len(bbox), 4)
        self.assertLess(bbox[0], bbox[2])
        self.assertLess(bbox[1], bbox[3])

    def test_extracts_combined_geometry_from_multiple_dxf_polygons(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEST_TMP_ROOT / f"multi_dxf_{uuid4().hex}"
        temp_dir.mkdir(exist_ok=True)
        path = temp_dir / "area.dxf"

        doc = ezdxf.new("R2000")
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
        msp.add_lwpolyline([(20, 0), (30, 0), (30, 10), (20, 10)], close=True)
        doc.saveas(path)

        geometry_wkt, bbox = extract_area_geometry_wkt(path)
        geometry = wkt.loads(geometry_wkt)

        self.assertEqual(geometry.geom_type, "MultiPolygon")
        self.assertEqual(len(getattr(geometry, "geoms", [])), 2)
        self.assertEqual(bbox, [0.0, 0.0, 30.0, 10.0])

    def _temp_path(self, name: str) -> Path:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEST_TMP_ROOT / f"area_{uuid4().hex}"
        temp_dir.mkdir(exist_ok=True)
        return temp_dir / name

    def _assert_square(self, path: Path, origin: tuple[float, float] = (0.0, 0.0)) -> None:
        geometry_wkt, bbox = extract_area_geometry_wkt(path)
        geometry = wkt.loads(geometry_wkt)
        self.assertAlmostEqual(geometry.area, 100.0)
        self.assertEqual(bbox, [origin[0], origin[1], origin[0] + 10.0, origin[1] + 10.0])

    SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]

    def test_dxf_polyline_ending_at_start_counts_as_closed(self) -> None:
        path = self._temp_path("area.dxf")
        doc = ezdxf.new("R2018")
        doc.modelspace().add_lwpolyline(self.SQUARE + [self.SQUARE[0]], close=False)
        doc.saveas(path)
        self._assert_square(path)

    def test_dxf_polygon_inside_block_reference(self) -> None:
        path = self._temp_path("area.dxf")
        doc = ezdxf.new("R2018")
        block = doc.blocks.new("BOUNDARY")
        block.add_lwpolyline(self.SQUARE, close=True)
        doc.modelspace().add_blockref("BOUNDARY", (100, 200))
        doc.saveas(path)
        self._assert_square(path, origin=(100.0, 200.0))

    def test_dxf_hatch_boundary(self) -> None:
        path = self._temp_path("area.dxf")
        doc = ezdxf.new("R2018")
        hatch = doc.modelspace().add_hatch()
        hatch.paths.add_polyline_path(self.SQUARE, is_closed=True)
        doc.saveas(path)
        self._assert_square(path)

    def test_dxf_loose_line_segments_forming_a_loop(self) -> None:
        path = self._temp_path("area.dxf")
        doc = ezdxf.new("R2018")
        msp = doc.modelspace()
        for start, end in zip(self.SQUARE, self.SQUARE[1:] + self.SQUARE[:1]):
            msp.add_line(start, end)
        doc.saveas(path)
        self._assert_square(path)

    def test_dxf_without_boundary_reports_entity_types(self) -> None:
        path = self._temp_path("area.dxf")
        doc = ezdxf.new("R2018")
        doc.modelspace().add_text("no boundary here")
        doc.saveas(path)
        with self.assertRaisesRegex(ValueError, "found: TEXT"):
            extract_area_geometry_wkt(path)

    def _write_kml(self, placemark: str) -> Path:
        path = self._temp_path("area.kml")
        path.write_text(
            '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2">'
            f"<Document><Placemark>{placemark}</Placemark></Document></kml>",
            encoding="utf-8",
        )
        return path

    RING = "-111.0,57.0,0 -110.999,57.0,0 -110.999,57.001,0 -111.0,57.001,0 -111.0,57.0,0"

    def test_kml_closed_linestring_path(self) -> None:
        path = self._write_kml(f"<LineString><coordinates>{self.RING}</coordinates></LineString>")
        geometry_wkt, _bbox = extract_area_geometry_wkt(path)
        self.assertGreater(wkt.loads(geometry_wkt).area, 0)

    def test_kml_open_linestring_is_rejected(self) -> None:
        open_ring = self.RING.rsplit(" ", 1)[0]
        path = self._write_kml(f"<LineString><coordinates>{open_ring}</coordinates></LineString>")
        with self.assertRaises(ValueError):
            extract_area_geometry_wkt(path)

    def test_kml_coordinates_with_spaces_after_commas(self) -> None:
        ring = self.RING.replace(",", ", ")
        path = self._write_kml(
            "<Polygon><outerBoundaryIs><LinearRing>"
            f"<coordinates>{ring}</coordinates>"
            "</LinearRing></outerBoundaryIs></Polygon>"
        )
        geometry_wkt, _bbox = extract_area_geometry_wkt(path)
        self.assertGreater(wkt.loads(geometry_wkt).area, 0)

    def test_builds_manual_polygon_geometry(self) -> None:
        geometry_wkt, bbox = build_manual_polygon_wkt([(0, 0), (10, 0), (10, 5), (0, 5)])
        geometry = wkt.loads(geometry_wkt)

        self.assertEqual(geometry.geom_type, "Polygon")
        self.assertAlmostEqual(geometry.area, 50.0)
        self.assertEqual(bbox, [0.0, 0.0, 10.0, 5.0])


if __name__ == "__main__":
    unittest.main()
