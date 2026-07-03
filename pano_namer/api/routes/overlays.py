from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from pano_namer.config import AppConfig, FIXED_CRS
from pano_namer.database import Database
from pano_namer.schemas import OverlayCreate, OverlayResponse
from pano_namer.services.common import dumps_json, ensure_path, loads_json, utc_now
from pano_namer.services.overlay import overlay_preview_dir, parse_overlay_metadata
from pano_namer.services.storage import StorageService

from .projects import fetch_project


def safe_upload_name(filename: str | None) -> str:
    name = Path((filename or "upload").replace("\\", "/")).name
    return name or "upload"


async def save_overlay_upload(storage: StorageService, project_id: int, upload: Any) -> Path:
    dest_dir = storage.project_dir(project_id) / "overlays"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{uuid4().hex}_{safe_upload_name(upload.filename)}"
    with dest_path.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            output.write(chunk)
    await upload.close()
    return dest_path


def row_to_overlay(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "jpg_original_path": row["jpg_original_path"],
        "jpg_managed_path": row["jpg_managed_path"],
        "image_url": f"/api/overlays/{row['id']}/image",
        "crs": row["crs"],
        "bounds": loads_json(row["bounds_json"], None),
        "width": row["width"],
        "height": row["height"],
        "active": bool(row["active"]),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def register_overlay_routes(app: FastAPI, cfg: AppConfig, db: Database, storage: StorageService) -> None:
    @app.get("/api/projects/{project_id}/overlay", response_model=OverlayResponse | None)
    def get_overlay(project_id: int) -> dict[str, Any] | None:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            row = conn.execute(
                "SELECT * FROM overlays WHERE project_id = ? AND active = 1 ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        return row_to_overlay(row)

    def create_overlay_from_path(project_id: int, source_path: Path, original_path: Path | None = None) -> dict[str, Any]:
        display_path, crs, bounds, width, height, error = parse_overlay_metadata(
            source_path,
            overlay_preview_dir(cfg.data_dir),
        )
        now = utc_now()
        with db.connect() as conn:
            fetch_project(conn, project_id)
            conn.execute("UPDATE projects SET crs = ?, updated_at = ? WHERE id = ?", (FIXED_CRS, now, project_id))
            conn.execute("UPDATE overlays SET active = 0 WHERE project_id = ?", (project_id,))
            cursor = conn.execute(
                """
                INSERT INTO overlays (
                    project_id, jpg_original_path, jpg_managed_path, crs, bounds_json,
                    width, height, active, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    project_id,
                    str(original_path or source_path),
                    str(display_path),
                    crs or FIXED_CRS,
                    dumps_json(bounds) if bounds else None,
                    width,
                    height,
                    error,
                    now,
                    now,
                ),
            )
            overlay_id = cursor.lastrowid
            conn.commit()
            row = conn.execute("SELECT * FROM overlays WHERE id = ?", (overlay_id,)).fetchone()
        return row_to_overlay(row)

    @app.post("/api/projects/{project_id}/overlay", response_model=OverlayResponse)
    def import_overlay(project_id: int, payload: OverlayCreate) -> dict[str, Any]:
        source_path = ensure_path(payload.source_path)
        managed_path = storage.copy_into_project(project_id, "overlays", source_path)
        return create_overlay_from_path(project_id, managed_path, original_path=source_path)

    @app.post("/api/projects/{project_id}/overlay/upload", response_model=OverlayResponse)
    async def upload_overlay(project_id: int, request: Request) -> dict[str, Any]:
        form = await request.form()
        file = form.get("file")
        filename = safe_upload_name(getattr(file, "filename", None))
        if file is None or Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Overlay import requires a PDF file.")
        source_path = await save_overlay_upload(storage, project_id, file)
        return create_overlay_from_path(project_id, source_path)

    @app.get("/api/overlays/{overlay_id}/image")
    def overlay_image(overlay_id: int) -> FileResponse:
        with db.connect() as conn:
            row = conn.execute("SELECT jpg_managed_path FROM overlays WHERE id = ?", (overlay_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Overlay not found")
        return FileResponse(Path(row["jpg_managed_path"]))
