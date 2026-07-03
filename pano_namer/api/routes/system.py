from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from pano_namer import __version__
from pano_namer.config import AppConfig, FIXED_CRS
from pano_namer.database import Database
from pano_namer.schemas import AppInfoResponse, CacheCleanupResponse
from pano_namer.services.overlay import cleanup_unused_overlay_previews, overlay_preview_dir


def thumbnail_dir(cfg: AppConfig) -> Path:
    path = cfg.data_dir / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path


def register_system_routes(app: FastAPI, cfg: AppConfig, db: Database, static_dir: Path) -> None:
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(
            static_dir / "index.html",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/api/app-info", response_model=AppInfoResponse)
    def app_info() -> dict[str, str]:
        return {
            "app_name": "PANO PRO",
            "version": __version__,
            "crs": FIXED_CRS,
            "data_dir": str(cfg.data_dir),
            "db_path": str(cfg.db_path),
            "storage_dir": str(cfg.storage_dir),
            "overlay_preview_dir": str(overlay_preview_dir(cfg.data_dir)),
            "thumbnail_dir": str(thumbnail_dir(cfg)),
        }

    @app.post("/api/cache/cleanup-unused", response_model=CacheCleanupResponse)
    def cleanup_unused_cache() -> dict[str, int]:
        preview_dir = overlay_preview_dir(cfg.data_dir)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT jpg_managed_path FROM overlays WHERE active = 1 AND jpg_managed_path IS NOT NULL"
            ).fetchall()
        active_paths = [Path(row["jpg_managed_path"]) for row in rows]
        return cleanup_unused_overlay_previews(preview_dir, active_paths)
