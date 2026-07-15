from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


EPSG_PATTERNS = (
    re.compile(r"EPSG[:=]\s*(\d+)", re.IGNORECASE),
    re.compile(r'AUTHORITY\["EPSG","(\d+)"\]', re.IGNORECASE),
    re.compile(r"urn:ogc:def:crs:EPSG::(\d+)", re.IGNORECASE),
)


def read_dxf_crs(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    for pattern in EPSG_PATTERNS:
        match = pattern.search(raw)
        if match:
            return f"EPSG:{match.group(1)}"
    raise ValueError("Could not determine CRS from DXF metadata. Add EPSG metadata to the file.")


def _combined_valid_geometry(polygons: list) -> tuple[str, list[float]]:
    from shapely.ops import unary_union

    valid_polygons = [polygon for polygon in polygons if polygon.is_valid and polygon.area > 0]
    if not valid_polygons:
        raise ValueError("Area file did not contain a valid closed polygon footprint.")

    geometry = unary_union(valid_polygons)
    minx, miny, maxx, maxy = geometry.bounds
    return geometry.wkt, [minx, miny, maxx, maxy]


def _extract_dxf_polygon_wkt(path: Path) -> tuple[str, list[float]]:
    import ezdxf
    from shapely.geometry import Polygon

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    polygons: list[Polygon] = []

    for entity in msp:
        entity_type = entity.dxftype()
        if entity_type == "LWPOLYLINE" and entity.closed:
            points = [(point[0], point[1]) for point in entity.get_points("xy")]
            if len(points) >= 3:
                polygon = Polygon(points).buffer(0)
                if not polygon.is_empty:
                    polygons.append(polygon)
        elif entity_type == "POLYLINE" and entity.is_closed:
            points = [(vertex.dxf.location.x, vertex.dxf.location.y) for vertex in entity.vertices]
            if len(points) >= 3:
                polygon = Polygon(points).buffer(0)
                if not polygon.is_empty:
                    polygons.append(polygon)

    return _combined_valid_geometry(polygons)


def _parse_kml_coordinate_string(raw: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for token in raw.replace("\n", " ").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        lon = float(parts[0])
        lat = float(parts[1])
        points.append((lon, lat))
    return points


def build_manual_polygon_wkt(coordinates: list[tuple[float, float]]) -> tuple[str, list[float]]:
    from shapely.geometry import Polygon

    if len(coordinates) < 3:
        raise ValueError("Drawn area requires at least 3 points.")

    polygon = Polygon(coordinates).buffer(0)
    return _combined_valid_geometry([polygon])


def build_manual_multipolygon_wkt(
    rings: list[list[tuple[float, float]]],
) -> tuple[str, list[float]]:
    """Build combined footprint geometry from one or more edited exterior rings.

    Each ring is an exterior boundary (holes are not modeled, matching how areas
    are drawn and rendered). Used by the map area editor to persist edited
    multi-polygon geometry; overlapping rings are merged by the union.
    """
    from shapely.geometry import Polygon

    polygons: list[Polygon] = []
    for ring in rings:
        points = [(float(point[0]), float(point[1])) for point in ring if len(point) >= 2]
        if len(points) < 3:
            continue
        polygon = Polygon(points).buffer(0)
        if not polygon.is_empty:
            polygons.append(polygon)
    if not polygons:
        raise ValueError("Edited area needs at least one ring with 3 or more points.")
    return _combined_valid_geometry(polygons)


def _extract_kml_polygon_wkt(path: Path) -> tuple[str, list[float]]:
    from pyproj import Transformer
    from shapely.geometry import Polygon

    tree = ET.parse(path)
    root = tree.getroot()
    polygons: list[Polygon] = []
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:26912", always_xy=True)

    for coordinates in root.findall(".//{*}Polygon//{*}outerBoundaryIs//{*}LinearRing//{*}coordinates"):
        if not coordinates.text:
            continue
        lon_lat_points = _parse_kml_coordinate_string(coordinates.text)
        if len(lon_lat_points) < 3:
            continue
        projected_points = [transformer.transform(lon, lat) for lon, lat in lon_lat_points]
        polygon = Polygon(projected_points).buffer(0)
        if not polygon.is_empty:
            polygons.append(polygon)

    return _combined_valid_geometry(polygons)


def extract_area_geometry_wkt(path: Path) -> tuple[str, list[float]]:
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        return _extract_dxf_polygon_wkt(path)
    if suffix == ".kml":
        return _extract_kml_polygon_wkt(path)
    raise ValueError("Area import requires a DXF or KML file.")
