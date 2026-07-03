from __future__ import annotations

from typing import Any


def _iter_polygon_parts(geometry: Any) -> list[Any]:
    geom_type = getattr(geometry, "geom_type", "")
    if geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        parts: list[Any] = []
        for part in geometry.geoms:
            parts.extend(_iter_polygon_parts(part))
        return parts
    return []


def containment_area_for_point(geometry: Any, point: Any) -> float | None:
    if getattr(geometry, "is_empty", True):
        return None
    containing_areas = [
        polygon.area
        for polygon in _iter_polygon_parts(geometry)
        if not polygon.is_empty and polygon.area > 0 and polygon.covers(point)
    ]
    if not containing_areas:
        return None
    return min(containing_areas)


def choose_area_match(point: Any, areas: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    containing: list[tuple[float, dict[str, Any]]] = []
    for area in areas:
        containment_area = containment_area_for_point(area["geometry"], point)
        if containment_area is not None:
            containing.append((containment_area, area))

    if containing:
        containing.sort(key=lambda item: (item[0], item[1]["id"]))
        return containing[0][1], "inside"

    if not areas:
        return None, None

    nearest = min(areas, key=lambda area: area["geometry"].distance(point))
    return nearest, "nearest"
