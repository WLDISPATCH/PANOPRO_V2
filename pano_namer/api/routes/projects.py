from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException

from pano_namer.config import AppConfig, FIXED_CRS
from pano_namer.database import Database
from pano_namer.schemas import ProjectCreate, ProjectResponse
from pano_namer.services.common import utc_now
from pano_namer.services.storage import StorageService


def row_to_project(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "storage_root": row["storage_root"],
        "crs": row["crs"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row:
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def register_project_routes(app: FastAPI, cfg: AppConfig, db: Database, storage: StorageService) -> None:
    @app.get("/api/projects", response_model=list[ProjectResponse])
    def list_projects() -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [row_to_project(row) for row in rows]

    @app.post("/api/projects", response_model=ProjectResponse)
    def create_project(payload: ProjectCreate) -> dict[str, Any]:
        now = utc_now()
        storage_root = payload.storage_root or str(cfg.storage_dir / "projects")
        with db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO projects (name, storage_root, crs, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (payload.name.strip(), storage_root, FIXED_CRS, now, now),
            )
            project_id = cursor.lastrowid
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        storage.project_dir(project_id)
        return row_to_project(row)

    @app.get("/api/projects/{project_id}", response_model=ProjectResponse)
    def get_project(project_id: int) -> dict[str, Any]:
        with db.connect() as conn:
            row = fetch_project(conn, project_id)
        return row_to_project(row)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: int) -> dict[str, bool]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        return {"ok": True}
