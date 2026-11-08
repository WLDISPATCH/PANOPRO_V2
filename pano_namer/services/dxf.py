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


# Endpoints closer than this (in drawing units) count as the same point, so a
# polyline drawn back to its start is treated as closed even without the flag.
DXF_CLOSE_TOLERANCE = 1e-3
# Blocks nested deeper than this are ignored to avoid runaway recursion.
MAX_BLOCK_DEPTH = 8


def _points_close(a: tuple[float, float], b: tuple[float, float], tolerance: float) -> bool:
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


def _read_dxf_document(path: Path):
    import ezdxf
    from ezdxf import recover

    try:
        return ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        # Files from some CAD exporters have minor structural errors that the
        # recover loader can repair.
        doc, _auditor = recover.readfile(path)
        return doc


def _iter_dxf_entities(entities, depth: int = 0):
    """Yield drawable entities, expanding block references (INSERT) in place."""
    for entity in entities:
        if entity.dxftype() == "INSERT":
            if depth >= MAX_BLOCK_DEPTH:
                continue
            try:
                yield from _iter_dxf_entities(entity.virtual_entities(), depth + 1)
            except Exception:
                continue
        else:
            yield entity


def _polyline_points(entity) -> list[tuple[float, float]]:
    if entity.dxftype() == "LWPOLYLINE":
        # LWPOLYLINE points are in OCS; convert so blocks/extrusions land in WCS.
        ocs = entity.ocs()
        elevation = entity.dxf.elevation
        return [
            (vec.x, vec.y)
            for vec in ocs.points_to_wcs((x, y, elevation) for x, y in entity.get_points("xy"))
        ]
    return [(vec.x, vec.y) for vec in entity.points_in_wcs()]


def _extract_dxf_polygon_wkt(path: Path) -> tuple[str, list[float]]:
    from ezdxf import path as dxf_path
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize

    doc = _read_dxf_document(path)
    msp = doc.modelspace()
    polygons: list[Polygon] = []
    open_lines: list[LineString] = []
    seen_types: set[str] = set()

    def add_polygon(points: list[tuple[float, float]]) -> None:
        if len(points) >= 3:
            polygon = Polygon(points).buffer(0)
            if not polygon.is_empty:
                polygons.append(polygon)

    for entity in _iter_dxf_entities(msp):
        entity_type = entity.dxftype()
        seen_types.add(entity_type)
        try:
            if entity_type in {"LWPOLYLINE", "POLYLINE"}:
                if entity_type == "POLYLINE" and (entity.is_polygon_mesh or entity.is_poly_face_mesh):
                    continue
                points = _polyline_points(entity)
                closed = entity.closed if entity_type == "LWPOLYLINE" else entity.is_closed
                if not closed and len(points) >= 4 and _points_close(points[0], points[-1], DXF_CLOSE_TOLERANCE):
                    closed = True
                if closed:
                    add_polygon(points)
                elif len(points) >= 2:
                    open_lines.append(LineString(points))
            elif entity_type == "HATCH":
                for boundary in dxf_path.from_hatch(entity):
                    add_polygon([(vec.x, vec.y) for vec in boundary.flattening(0.01)])
            elif entity_type == "LINE":
                start, end = entity.dxf.start, entity.dxf.end
                open_lines.append(LineString([(start.x, start.y), (end.x, end.y)]))
            elif entity_type == "ARC":
                points = [(vec.x, vec.y) for vec in entity.flattening(0.01)]
                if len(points) >= 2:
                    open_lines.append(LineString(points))
            elif entity_type == "CIRCLE":
                add_polygon([(vec.x, vec.y) for vec in entity.flattening(0.01)])
        except Exception:
            # One malformed entity should not block the rest of the file.
            continue

    # Only fall back to stitching loose linework when the file has no explicit
    # closed shapes, so extra lines in a drawing don't distort a real boundary.
    if not polygons and open_lines:
        polygons.extend(polygon.buffer(0) for polygon in polygonize(open_lines))

    if not any(polygon.is_valid and polygon.area > 0 for polygon in polygons):
        found = ", ".join(sorted(seen_types)) or "no drawable entities"
        raise ValueError(
            "Area file did not contain a valid closed polygon footprint "
            f"(found: {found}). Draw the boundary as a closed polyline or hatch."
        )
    return _combined_valid_geometry(polygons)


def _parse_kml_coordinate_string(raw: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    # Some exporters write "lon, lat, alt" with spaces after the commas.
    normalized = re.sub(r"\s*,\s*", ",", raw.strip())
    for token in normalized.split():
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


# About 1 cm; KML coordinates are lon/lat degrees.
KML_CLOSE_TOLERANCE_DEG = 1e-7


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

    if not polygons:
        # Google Earth "paths" drawn back to their start point are closed
        # LineStrings rather than Polygons; accept those as boundaries too.
        for coordinates in root.findall(".//{*}LineString/{*}coordinates"):
            if not coordinates.text:
                continue
            lon_lat_points = _parse_kml_coordinate_string(coordinates.text)
            if len(lon_lat_points) < 4 or not _points_close(
                lon_lat_points[0], lon_lat_points[-1], KML_CLOSE_TOLERANCE_DEG
            ):
                continue
            projected_points = [transformer.transform(lon, lat) for lon, lat in lon_lat_points]
            polygon = Polygon(projected_points).buffer(0)
            if not polygon.is_empty:
                polygons.append(polygon)

    if not polygons:
        raise ValueError(
            "Area file did not contain a valid closed polygon footprint. "
            "Draw the boundary in Google Earth as a polygon (or a path that ends at its start point)."
        )
    return _combined_valid_geometry(polygons)


def extract_area_geometry_wkt(path: Path) -> tuple[str, list[float]]:
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        return _extract_dxf_polygon_wkt(path)
    if suffix == ".kml":
        return _extract_kml_polygon_wkt(path)
    raise ValueError("Area import requires a DXF or KML file.")
