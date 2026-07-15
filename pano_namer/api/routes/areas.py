from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from pano_namer.area_colors import next_available_area_color, normalize_area_color
from pano_namer.config import FIXED_CRS
from pano_namer.database import Database
from pano_namer.schemas import (
    AreaCreate,
    AreaGeometryUpdate,
    AreaResponse,
    AreaUpdate,
)
from pano_namer.services.common import dumps_json, ensure_path, utc_now
from pano_namer.services.dxf import (
    build_manual_multipolygon_wkt,
    build_manual_polygon_wkt,
    extract_area_geometry_wkt,
)
from pano_namer.services.matching import choose_area_match
from pano_namer.services.rename import plan_renames
from pano_namer.services.storage import StorageService

from .projects import fetch_project


def safe_upload_name(filename: str | None) -> str:
    name = Path((filename or "upload").replace("\\", "/")).name
    return name or "upload"


async def save_area_upload(storage: StorageService, project_id: int, upload: Any) -> Path:
    dest_dir = storage.project_dir(project_id) / "areas"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{uuid4().hex}_{safe_upload_name(upload.filename)}"
    with dest_path.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            output.write(chunk)
    await upload.close()
    return dest_path


def row_to_area(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "dxf_original_path": row["dxf_original_path"],
        "dxf_managed_path": row["dxf_managed_path"],
        "display_color": row["display_color"],
        "source_crs": row["source_crs"],
        "footprint_bbox": __import__("json").loads(row["footprint_bbox_json"]) if row["footprint_bbox_json"] else [],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def resolve_area_color(
    conn: sqlite3.Connection,
    project_id: int,
    requested_color: str | None,
    *,
    exclude_area_id: int | None = None,
) -> str:
    normalized = normalize_area_color(requested_color)
    if requested_color is not None and normalized is None:
        raise HTTPException(status_code=400, detail="Area color must be a 6-digit hex value.")
    if normalized is not None:
        return normalized

    query = "SELECT display_color FROM areas WHERE project_id = ? AND active = 1"
    params: list[Any] = [project_id]
    if exclude_area_id is not None:
        query += " AND id != ?"
        params.append(exclude_area_id)
    rows = conn.execute(query, params).fetchall()
    existing_colors = [row["display_color"] for row in rows if row["display_color"]]
    return next_available_area_color(existing_colors)


def refresh_pending_photo_matches(conn: sqlite3.Connection, project_id: int) -> None:
    try:
        from pyproj import Transformer
        from shapely import wkt
        from shapely.geometry import Point
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Missing dependency: {exc}") from exc

    project = fetch_project(conn, project_id)
    project_crs = project["crs"] or FIXED_CRS
    area_rows = conn.execute(
        "SELECT * FROM areas WHERE project_id = ? AND active = 1",
        (project_id,),
    ).fetchall()
    photo_rows = conn.execute(
        "SELECT * FROM photos WHERE project_id = ? AND applied = 0",
        (project_id,),
    ).fetchall()

    areas = []
    area_lookup: dict[int, Any] = {}
    for row in area_rows:
        geometry = wkt.loads(row["footprint_wkt"])
        area_lookup[row["id"]] = geometry
        if not geometry.is_empty:
            areas.append({"id": row["id"], "name": row["name"], "geometry": geometry})
    transformer = Transformer.from_crs("EPSG:4326", project_crs, always_xy=True)
    now = utc_now()

    for row in photo_rows:
        projected_x = None
        projected_y = None
        matched_area_id = None
        match_mode = None
        error = None
        original_path = Path(row["original_path"])

        if not original_path.exists():
            error = "Photo file not found at saved path."
        elif row["capture_ts"] is None:
            error = "Photo metadata did not contain a capture timestamp."
        elif row["match_mode"] == "manual":
            matched_area_id = row["matched_area_id"]
            match_mode = "manual" if matched_area_id else None
            if row["gps_lat"] is not None and row["gps_lon"] is not None:
                projected_x, projected_y = transformer.transform(row["gps_lon"], row["gps_lat"])
            if matched_area_id is None:
                error = "Manual area not selected."
            elif matched_area_id not in area_lookup:
                error = "Selected area no longer exists."
            elif area_lookup[matched_area_id].is_empty:
                error = None
        else:
            if row["gps_lat"] is None or row["gps_lon"] is None:
                error = "Photo metadata did not contain GPS coordinates."
            else:
                projected_x, projected_y = transformer.transform(row["gps_lon"], row["gps_lat"])
                point = Point(projected_x, projected_y)
                matched_area, match_mode = choose_area_match(point, areas)
                if matched_area:
                    matched_area_id = matched_area["id"]

        conn.execute(
            """
            UPDATE photos
            SET projected_x = ?, projected_y = ?, matched_area_id = ?, match_mode = ?,
                proposed_filename = NULL, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (projected_x, projected_y, matched_area_id, match_mode, error, now, row["id"]),
        )

    joined_rows = conn.execute(
        """
        SELECT photos.*, areas.name AS area_name
        FROM photos
        LEFT JOIN areas ON photos.matched_area_id = areas.id
        WHERE photos.project_id = ? AND photos.applied = 0
        """,
        (project_id,),
    ).fetchall()
    for plan in plan_renames([dict(row) for row in joined_rows]):
        conn.execute(
            "UPDATE photos SET proposed_filename = ?, updated_at = ? WHERE id = ?",
            (plan.final_name, utc_now(), plan.photo_id),
        )


def register_area_routes(app: FastAPI, db: Database, storage: StorageService) -> None:
    @app.get("/api/projects/{project_id}/areas", response_model=list[AreaResponse])
    def list_areas(project_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            rows = conn.execute(
                "SELECT * FROM areas WHERE project_id = ? AND active = 1 ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return [row_to_area(row) for row in rows]

    def create_area_record(
        project_id: int,
        *,
        name: str,
        source_path: Path | None = None,
        managed_path: Path | None = None,
        display_color: str | None = None,
        coordinates: list[list[float]] | None = None,
    ) -> dict[str, Any]:
        if source_path and source_path.suffix.lower() not in {".dxf", ".kml"}:
            raise HTTPException(status_code=400, detail="Area import requires a DXF or KML file.")
        if source_path and coordinates:
            raise HTTPException(status_code=400, detail="Choose either an area file or drawn coordinates, not both.")
        try:
            if source_path:
                footprint_wkt, bbox = extract_area_geometry_wkt(source_path)
            elif coordinates:
                footprint_wkt, bbox = build_manual_polygon_wkt(
                    [(float(point[0]), float(point[1])) for point in coordinates if len(point) >= 2]
                )
            else:
                footprint_wkt, bbox = "POLYGON EMPTY", []
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        now = utc_now()
        if source_path and managed_path is None:
            managed_path = storage.copy_into_project(project_id, "areas", source_path)
        with db.connect() as conn:
            fetch_project(conn, project_id)
            resolved_color = resolve_area_color(conn, project_id, display_color)
            conn.execute("UPDATE projects SET crs = ?, updated_at = ? WHERE id = ?", (FIXED_CRS, now, project_id))
            cursor = conn.execute(
                """
                INSERT INTO areas (
                    project_id, name, dxf_original_path, dxf_managed_path, display_color, source_crs,
                    footprint_wkt, footprint_bbox_json, active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    project_id,
                    name.strip(),
                    str(source_path) if source_path else "",
                    str(managed_path) if managed_path else "",
                    resolved_color,
                    FIXED_CRS,
                    footprint_wkt,
                    dumps_json(bbox),
                    now,
                    now,
                ),
            )
            area_id = cursor.lastrowid
            refresh_pending_photo_matches(conn, project_id)
            conn.commit()
            row = conn.execute("SELECT * FROM areas WHERE id = ?", (area_id,)).fetchone()
        return row_to_area(row)

    @app.post("/api/projects/{project_id}/areas", response_model=AreaResponse)
    def create_area(project_id: int, payload: AreaCreate) -> dict[str, Any]:
        source_path = ensure_path(payload.source_path) if payload.source_path else None
        return create_area_record(
            project_id,
            name=payload.name,
            source_path=source_path,
            display_color=payload.display_color,
            coordinates=payload.coordinates,
        )

    @app.post("/api/projects/{project_id}/areas/upload", response_model=AreaResponse)
    async def upload_area(project_id: int, request: Request) -> dict[str, Any]:
        form = await request.form()
        name = str(form.get("name") or "").strip()
        file = form.get("file")
        filename = safe_upload_name(getattr(file, "filename", None))
        if not name:
            raise HTTPException(status_code=400, detail="Area name is required.")
        if file is None or Path(filename).suffix.lower() not in {".dxf", ".kml"}:
            raise HTTPException(status_code=400, detail="Area import requires a DXF or KML file.")
        source_path = await save_area_upload(storage, project_id, file)
        return create_area_record(project_id, name=name, source_path=source_path, managed_path=source_path)

    @app.put(
        "/api/projects/{project_id}/areas/{area_id}/upload",
        response_model=AreaResponse,
    )
    async def upload_area_replacement(
        project_id: int, area_id: int, request: Request
    ) -> dict[str, Any]:
        form = await request.form()
        file = form.get("file")
        filename = safe_upload_name(getattr(file, "filename", None))
        if file is None or Path(filename).suffix.lower() not in {".dxf", ".kml"}:
            raise HTTPException(
                status_code=400, detail="Area replacement requires a DXF or KML file."
            )
        source_path = await save_area_upload(storage, project_id, file)
        try:
            footprint_wkt, bbox = extract_area_geometry_wkt(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        now = utc_now()
        with db.connect() as conn:
            fetch_project(conn, project_id)
            area = conn.execute(
                "SELECT * FROM areas WHERE id = ? AND project_id = ?",
                (area_id, project_id),
            ).fetchone()
            if area is None:
                raise HTTPException(status_code=404, detail="Area not found")
            conn.execute(
                """
                UPDATE areas
                SET dxf_original_path = ?, dxf_managed_path = ?, source_crs = ?,
                    footprint_wkt = ?, footprint_bbox_json = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (
                    str(source_path),
                    str(source_path),
                    FIXED_CRS,
                    footprint_wkt,
                    dumps_json(bbox),
                    now,
                    area_id,
                    project_id,
                ),
            )
            refresh_pending_photo_matches(conn, project_id)
            conn.commit()
            row = conn.execute(
                "SELECT * FROM areas WHERE id = ?", (area_id,)
            ).fetchone()
        return row_to_area(row)

    @app.put("/api/projects/{project_id}/areas/{area_id}", response_model=AreaResponse)
    def update_area(project_id: int, area_id: int, payload: AreaUpdate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            fetch_project(conn, project_id)
            area = conn.execute("SELECT * FROM areas WHERE id = ? AND project_id = ?", (area_id, project_id)).fetchone()
            if area is None:
                raise HTTPException(status_code=404, detail="Area not found")

            name = payload.name.strip() if payload.name else area["name"]
            dxf_original_path = area["dxf_original_path"]
            dxf_managed_path = area["dxf_managed_path"]
            display_color = area["display_color"]
            source_crs = area["source_crs"]
            footprint_wkt = area["footprint_wkt"]
            bbox_json = area["footprint_bbox_json"]
            if payload.display_color is not None:
                display_color = resolve_area_color(conn, project_id, payload.display_color, exclude_area_id=area_id)

            if payload.source_path:
                source_path = ensure_path(payload.source_path)
                try:
                    footprint_wkt, bbox = extract_area_geometry_wkt(source_path)
                except Exception as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                source_crs = FIXED_CRS
                managed_path = storage.copy_into_project(project_id, "areas", source_path)
                dxf_original_path = str(source_path)
                dxf_managed_path = str(managed_path)
                bbox_json = dumps_json(bbox)

            conn.execute(
                """
                UPDATE areas
                SET name = ?, dxf_original_path = ?, dxf_managed_path = ?, display_color = ?, source_crs = ?,
                    footprint_wkt = ?, footprint_bbox_json = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (
                    name,
                    dxf_original_path,
                    dxf_managed_path,
                    display_color,
                    source_crs,
                    footprint_wkt,
                    bbox_json,
                    now,
                    area_id,
                    project_id,
                ),
            )
            refresh_pending_photo_matches(conn, project_id)
            conn.commit()
            row = conn.execute("SELECT * FROM areas WHERE id = ?", (area_id,)).fetchone()
        return row_to_area(row)

    @app.put(
        "/api/projects/{project_id}/areas/{area_id}/geometry",
        response_model=AreaResponse,
    )
    def update_area_geometry(
        project_id: int, area_id: int, payload: AreaGeometryUpdate
    ) -> dict[str, Any]:
        """Persist edited polygon geometry from the map area editor (issue #29).

        Rebuilds the footprint from the edited exterior rings and writes a fresh
        KML so area sync detects the change (via file hash + updated_at) and
        pushes it. Pending photos are re-matched against the new geometry.
        """
        from pano_namer.services.area_sync import kml_for_polygon_wkt

        try:
            footprint_wkt, bbox = build_manual_multipolygon_wkt(payload.parts)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        now = utc_now()
        with db.connect() as conn:
            fetch_project(conn, project_id)
            area = conn.execute(
                "SELECT * FROM areas WHERE id = ? AND project_id = ?",
                (area_id, project_id),
            ).fetchone()
            if area is None:
                raise HTTPException(status_code=404, detail="Area not found")

            # Back the edited geometry with a KML so it syncs like a drawn area.
            areas_dir = storage.project_dir(project_id) / "areas"
            areas_dir.mkdir(parents=True, exist_ok=True)
            kml_path = areas_dir / f"edited_{area_id}_{uuid4().hex[:8]}.kml"
            try:
                kml_path.write_bytes(kml_for_polygon_wkt(footprint_wkt))
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail=f"Could not save edited geometry: {exc}"
                ) from exc

            conn.execute(
                """
                UPDATE areas
                SET dxf_original_path = ?, dxf_managed_path = ?, source_crs = ?,
                    footprint_wkt = ?, footprint_bbox_json = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (
                    str(kml_path),
                    str(kml_path),
                    FIXED_CRS,
                    footprint_wkt,
                    dumps_json(bbox),
                    now,
                    area_id,
                    project_id,
                ),
            )
            refresh_pending_photo_matches(conn, project_id)
            conn.commit()
            row = conn.execute("SELECT * FROM areas WHERE id = ?", (area_id,)).fetchone()
        return row_to_area(row)

    @app.delete("/api/projects/{project_id}/areas/{area_id}")
    def delete_area(project_id: int, area_id: int) -> dict[str, bool]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            conn.execute(
                "UPDATE areas SET active = 0, updated_at = ? WHERE id = ? AND project_id = ?",
                (utc_now(), area_id, project_id),
            )
            refresh_pending_photo_matches(conn, project_id)
            conn.commit()
        return {"ok": True}
