from __future__ import annotations

import json
import math
import os
import queue
import sqlite3
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles


class NoCacheStaticFiles(StaticFiles):
    """Serve app.js/styles.css with revalidation so they can never go stale.

    index.html is served no-store, but without cache headers here browsers
    could pair a fresh index.html with a cached old app.js after a reload,
    crashing the whole frontend (missing element ids, "V-" badge, dead UI).
    no-cache still allows fast 304 responses via ETag/Last-Modified.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response

from pano_namer.api.routes.areas import register_area_routes
from pano_namer.api.routes.overlays import register_overlay_routes, row_to_overlay
from pano_namer.api.routes.projects import register_project_routes
from pano_namer.api.routes.settings import register_settings_routes
from pano_namer.api.routes.smart import register_smart_routes
from pano_namer.api.routes.system import register_system_routes
from pano_namer.api.routes.site_insight import register_site_insight_routes
from pano_namer import __version__
from pano_namer.area_colors import (
    DEFAULT_AREA_COLOR,
    next_available_area_color,
    normalize_area_color,
)
from pano_namer.admin import install_admin
from pano_namer.auth_gate import install_auth_gate
from pano_namer.config import AppConfig, FIXED_CRS
from pano_namer.database import Database
from pano_namer.schemas import (
    AppInfoResponse,
    ArchiveAssignRequest,
    ArchiveFolderCreate,
    AreaCreate,
    AreaResponse,
    CacheCleanupResponse,
    CollectionCreate,
    CollectionItemsRequest,
    CollectionUpdate,
    AreaUpdate,
    AnnotationCreate,
    HotspotCreate,
    IssueCreate,
    MapDataResponse,
    NoteCreate,
    PhotoDeleteRequest,
    PhotoImportRequest,
    PhotoImportResponse,
    PhotoBatchResponse,
    PhotoTagsRequest,
    PhotoUpdateRequest,
    PhotoResponse,
    ProjectCreate,
    ProjectResponse,
    RenameRunCreate,
    RenamePreviewResponse,
    RenameReservationReportRequest,
    RenameReservationReportResponse,
    RenameReservationsCommitRequest,
    RenameReservationsCommitResponse,
    RenameRunResponse,
    ReviewUpdate,
    SavedFilterCreate,
    TagCreate,
    ViewerStateUpdate,
)
from pano_namer.services.common import dumps_json, ensure_path, loads_json, utc_now
from pano_namer.services.dxf import build_manual_polygon_wkt, extract_area_geometry_wkt
from pano_namer.services.media import content_hash, ensure_thumbnail, prepare_thumbnail
from pano_namer.services.matching import choose_area_match
from pano_namer.services.photos import read_photo_metadata
from pano_namer.services import overlay_tiles, shared_naming
from pano_namer.services.rename import (
    RenamePlanItem,
    apply_rename_plan,
    plan_renames,
    preview_renames,
    rollback_rename_results,
)
from pano_namer.services.reservations import (
    report_filename_reservation_results,
    reserve_filenames_for_photos,
)
from pano_namer.services.storage import StorageService
from pano_namer.services.site_insight_uploads import SiteInsightSettings

STATIC_DIR = Path(__file__).resolve().parent / "static"
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
THUMBNAIL_DIR_NAME = "thumbnails"


def safe_upload_name(filename: str | None) -> str:
    name = Path((filename or "upload").replace("\\", "/")).name
    return name or "upload"


async def save_upload_to_project(
    storage: StorageService, project_id: int, category: str, upload: Any
) -> Path:
    dest_dir = storage.project_dir(project_id) / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{uuid4().hex}_{safe_upload_name(upload.filename)}"
    with dest_path.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            output.write(chunk)
    await upload.close()
    return dest_path


def row_to_project(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "storage_root": row["storage_root"],
        "crs": row["crs"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_area(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "dxf_original_path": row["dxf_original_path"],
        "dxf_managed_path": row["dxf_managed_path"],
        "display_color": row["display_color"] or DEFAULT_AREA_COLOR,
        "source_crs": row["source_crs"],
        "footprint_bbox": loads_json(row["footprint_bbox_json"], []),
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_photo(row: sqlite3.Row) -> dict[str, Any]:
    area_name = row["area_name"] if "area_name" in row.keys() else None
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "batch_id": row["batch_id"],
        "photo_batch_id": (
            row["photo_batch_id"] if "photo_batch_id" in row.keys() else None
        ),
        "original_path": row["original_path"],
        "capture_ts": row["capture_ts"],
        "gps_lat": row["gps_lat"],
        "gps_lon": row["gps_lon"],
        "projected_x": row["projected_x"],
        "projected_y": row["projected_y"],
        "matched_area_id": row["matched_area_id"],
        "area_name": area_name,
        "match_mode": row["match_mode"],
        "proposed_filename": row["proposed_filename"],
        "applied": bool(row["applied"]),
        "content_hash": row["content_hash"] if "content_hash" in row.keys() else None,
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_photo_batch(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "batch_uid": row["batch_uid"],
        "source_kind": row["source_kind"],
        "actor_label": row["actor_label"],
        "client_device": row["client_device"],
        "status": row["status"],
        "photo_count": row["photo_count"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }


def row_to_rename_run(row: sqlite3.Row) -> dict[str, Any]:
    rollback_results = loads_json(row["rollback_results_json"], [])
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "batch_id": row["batch_id"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "summary": loads_json(row["summary_json"], {}),
        "results": loads_json(row["results_json"], []),
        "rollback_started_at": row["rollback_started_at"],
        "rollback_completed_at": row["rollback_completed_at"],
        "rollback_results": rollback_results,
    }


def fetch_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row:
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def fetch_pending_photo_rows(
    conn: sqlite3.Connection, project_id: int, photo_ids: list[int] | None = None
) -> list[sqlite3.Row]:
    if photo_ids:
        placeholders = ",".join("?" for _ in photo_ids)
        return conn.execute(
            f"""
            SELECT photos.*, areas.name AS area_name
            FROM photos
            LEFT JOIN areas ON photos.matched_area_id = areas.id
            WHERE photos.project_id = ? AND photos.applied = 0 AND photos.id IN ({placeholders})
            """,
            [project_id, *photo_ids],
        ).fetchall()
    return conn.execute(
        """
        SELECT photos.*, areas.name AS area_name
        FROM photos
        LEFT JOIN areas ON photos.matched_area_id = areas.id
        WHERE photos.project_id = ? AND photos.applied = 0
        """,
        (project_id,),
    ).fetchall()


SHARED_NAMING_MAX_ATTEMPTS = 3


def reserve_plans_with_shared_naming(
    conn: sqlite3.Connection, project_id: int, photo_ids: list[int] | None
) -> list[RenamePlanItem]:
    """Start the reservation transaction and allocate filename plans.

    When Shared Pano Naming is disabled this matches the original flow exactly.
    When enabled, the shared Supabase registry is consulted for each group's
    highest used sequence, the reserved names are inserted into the registry
    before any local rename happens, and a unique-name conflict (another
    computer claimed the range first) triggers a refresh-and-retry.

    On return the write transaction is open and reservations are committed to
    it but not yet to disk; callers keep full control of commit/rollback. The
    registry insert intentionally happens while the SQLite write lock is held:
    this database is local to one machine with a single writer, and inserting
    into Supabase before renaming files matters more than lock hold time.
    """
    settings = shared_naming.load_settings(conn)
    if not settings.enabled:
        conn.execute("BEGIN IMMEDIATE")
        rows = fetch_pending_photo_rows(conn, project_id, photo_ids)
        return reserve_filenames_for_photos(conn, project_id, rows)

    if not settings.is_configured():
        raise HTTPException(
            status_code=400,
            detail=(
                "Shared Pano Naming is enabled but the Supabase URL or anon key "
                "is missing. Update Settings or disable Shared Pano Naming."
            ),
        )

    for _attempt in range(SHARED_NAMING_MAX_ATTEMPTS):
        rows = fetch_pending_photo_rows(conn, project_id, photo_ids)
        groups = shared_naming.group_keys_for_rows(rows)
        try:
            min_sequences = {
                key: shared_naming.fetch_max_sequence(
                    settings, shared_naming.date_code_from_canonical(key[0]), key[1]
                )
                for key in groups
            }
        except shared_naming.SharedNamingUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        conn.execute("BEGIN IMMEDIATE")
        plans = reserve_filenames_for_photos(
            conn, project_id, rows, min_sequences=min_sequences
        )
        if not plans:
            return plans
        registry_rows = shared_naming.registry_rows_for_plans(
            plans, settings.resolved_computer_name()
        )
        try:
            shared_naming.register_names(settings, registry_rows)
        except shared_naming.SharedNamingConflictError:
            conn.rollback()
            continue
        except shared_naming.SharedNamingUnavailableError as exc:
            conn.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return plans

    raise HTTPException(
        status_code=409,
        detail=(
            "Could not reserve shared pano names after "
            f"{SHARED_NAMING_MAX_ATTEMPTS} attempts. Try again."
        ),
    )


def build_rename_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    renamed_count = 0
    unchanged_count = 0
    error_count = 0
    for result in results:
        if result["status"] in {"renamed", "unchanged"}:
            if result["status"] == "renamed":
                renamed_count += 1
            else:
                unchanged_count += 1
        else:
            error_count += 1
    return {
        "renamed": renamed_count,
        "unchanged": unchanged_count,
        "errors": error_count,
    }


def thumbnail_dir(cfg: AppConfig) -> Path:
    path = cfg.data_dir / THUMBNAIL_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_audit(
    conn: sqlite3.Connection,
    action_type: str,
    entity_type: str,
    entity_id: int | None,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_events (action_type, entity_type, entity_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (action_type, entity_type, entity_id, dumps_json(payload or {}), utc_now()),
    )


def ensure_photo_thumbnail(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    photo_id: int,
    photo_path: Path,
    precomputed: tuple[bytes, int, int] | None = None,
) -> dict[str, Any] | None:
    if not photo_path.exists():
        return None
    row = conn.execute(
        "SELECT * FROM pano_thumbnails WHERE photo_id = ?", (photo_id,)
    ).fetchone()
    if row is not None and Path(row["thumb_path"]).exists():
        return {
            "path": row["thumb_path"],
            "width": row["width"],
            "height": row["height"],
            "url": f"/api/photos/{photo_id}/thumbnail",
        }
    try:
        if precomputed is None:
            thumb_path, width, height = ensure_thumbnail(
                photo_path, thumbnail_dir(cfg), photo_id
            )
        else:
            data, width, height = precomputed
            thumb_path = thumbnail_dir(cfg) / f"photo_{photo_id}.jpg"
            thumb_path.write_bytes(data)
    except Exception:
        return None
    conn.execute(
        """
        INSERT INTO pano_thumbnails (photo_id, thumb_path, width, height, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(photo_id) DO UPDATE SET
            thumb_path = excluded.thumb_path,
            width = excluded.width,
            height = excluded.height,
            updated_at = excluded.updated_at
        """,
        (photo_id, str(thumb_path), width, height, utc_now()),
    )
    return {
        "path": str(thumb_path),
        "width": width,
        "height": height,
        "url": f"/api/photos/{photo_id}/thumbnail",
    }


def prepare_photo_import(source_path: Path) -> dict[str, Any]:
    try:
        meta = read_photo_metadata(source_path)
        hash_value = content_hash(source_path)
    except Exception as exc:
        return {
            "meta": None,
            "hash_value": None,
            "thumb": None,
            "error": str(exc),
        }

    try:
        thumb = prepare_thumbnail(source_path)
    except Exception:
        thumb = None

    return {
        "meta": meta,
        "hash_value": hash_value,
        "thumb": thumb,
        "error": None,
    }


def ensure_photo_view_state(conn: sqlite3.Connection, photo_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM pano_view_state WHERE photo_id = ?", (photo_id,)
    ).fetchone()
    if row is not None:
        return row
    conn.execute(
        """
        INSERT INTO pano_view_state (photo_id, north_offset, default_yaw, default_pitch, default_fov, updated_at)
        VALUES (?, 0, 0, 0, 75, ?)
        """,
        (photo_id, utc_now()),
    )
    return conn.execute(
        "SELECT * FROM pano_view_state WHERE photo_id = ?", (photo_id,)
    ).fetchone()


def parse_capture_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def weekly_collection_name(capture_ts: str | None) -> str | None:
    capture_dt = parse_capture_datetime(capture_ts)
    if capture_dt is None:
        return None
    iso_year, iso_week, _ = capture_dt.isocalendar()
    return f"{iso_year} Week {iso_week:02d}"


def ensure_collection_row(
    conn: sqlite3.Connection, name: str, description: str | None = None
) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM collections WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return row
    now = utc_now()
    cursor = conn.execute(
        "INSERT INTO collections (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, description, now, now),
    )
    collection_id = cursor.lastrowid
    log_audit(
        conn,
        "collection.create",
        "collection",
        collection_id,
        {"name": name, "system_generated": True},
    )
    return conn.execute(
        "SELECT * FROM collections WHERE id = ?", (collection_id,)
    ).fetchone()


def add_photo_to_collection(
    conn: sqlite3.Connection,
    collection_id: int,
    photo_id: int,
    audit_action: str = "collection.add_photo",
) -> None:
    last_order_row = conn.execute(
        "SELECT COALESCE(MAX(item_order), 0) AS max_order FROM collection_items WHERE collection_id = ?",
        (collection_id,),
    ).fetchone()
    next_order = int(last_order_row["max_order"]) + 1
    conn.execute(
        """
        INSERT OR IGNORE INTO collection_items (collection_id, photo_id, item_order, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (collection_id, photo_id, next_order, utc_now()),
    )
    refresh_system_tags(conn, photo_id)
    log_audit(conn, audit_action, "collection", collection_id, {"photo_id": photo_id})


def normalize_degrees(value: float) -> float:
    while value <= -180:
        value += 360
    while value > 180:
        value -= 360
    return value


def bearing_from_projected(
    source_x: float, source_y: float, target_x: float, target_y: float
) -> float:
    dx = target_x - source_x
    dy = target_y - source_y
    if dx == 0 and dy == 0:
        return 0.0
    return normalize_degrees(float(math.degrees(math.atan2(dx, dy))))


def system_tag_names(conn: sqlite3.Connection, photo_id: int) -> list[str]:
    row = conn.execute(
        """
        SELECT photos.id, projects.name AS project_name, areas.name AS area_name, archive_folders.name AS archive_name
        FROM photos
        LEFT JOIN projects ON photos.project_id = projects.id
        LEFT JOIN areas ON photos.matched_area_id = areas.id
        LEFT JOIN archived_panos ON archived_panos.photo_id = photos.id
        LEFT JOIN archive_folders ON archived_panos.folder_id = archive_folders.id
        WHERE photos.id = ?
        """,
        (photo_id,),
    ).fetchone()
    if row is None:
        return []
    names: list[str] = []
    if row["project_name"]:
        names.append(f"template:{row['project_name']}")
    if row["area_name"]:
        names.append(f"area:{row['area_name']}")
    if row["archive_name"]:
        names.append(f"archive:{row['archive_name']}")
    collection_rows = conn.execute(
        """
        SELECT collections.name
        FROM collection_items
        JOIN collections ON collections.id = collection_items.collection_id
        WHERE collection_items.photo_id = ?
        ORDER BY collections.name
        """,
        (photo_id,),
    ).fetchall()
    names.extend([f"collection:{row['name']}" for row in collection_rows])
    return names


def refresh_system_tags(conn: sqlite3.Connection, photo_id: int) -> None:
    names = system_tag_names(conn, photo_id)
    conn.execute(
        """
        DELETE FROM pano_tags
        WHERE photo_id = ? AND tag_id IN (SELECT id FROM tags WHERE tag_type = 'system')
        """,
        (photo_id,),
    )
    now = utc_now()
    for name in names:
        conn.execute(
            """
            INSERT INTO tags (name, tag_type, created_at, updated_at)
            VALUES (?, 'system', ?, ?)
            ON CONFLICT(name) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (name, now, now),
        )
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[
            "id"
        ]
        conn.execute(
            """
            INSERT OR IGNORE INTO pano_tags (photo_id, tag_id, created_at)
            VALUES (?, ?, ?)
            """,
            (photo_id, tag_id, now),
        )


def refresh_all_system_tags(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id FROM photos").fetchall()
    for row in rows:
        refresh_system_tags(conn, row["id"])


def update_duplicate_pairs(
    conn: sqlite3.Connection, photo_id: int, hash_value: str | None
) -> None:
    if not hash_value:
        return
    row_ids = conn.execute(
        "SELECT id FROM photos WHERE content_hash = ? AND id != ? ORDER BY id",
        (hash_value, photo_id),
    ).fetchall()
    now = utc_now()
    for row in row_ids:
        left = min(photo_id, row["id"])
        right = max(photo_id, row["id"])
        conn.execute(
            """
            INSERT OR IGNORE INTO pano_duplicates (photo_id, duplicate_photo_id, content_hash, status, created_at)
            VALUES (?, ?, ?, 'detected', ?)
            """,
            (left, right, hash_value, now),
        )


def photo_detail_payload(
    conn: sqlite3.Connection, cfg: AppConfig, photo_id: int
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT photos.*, areas.name AS area_name
        FROM photos
        LEFT JOIN areas ON photos.matched_area_id = areas.id
        WHERE photos.id = ?
        """,
        (photo_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    photo = row_to_photo(row)
    photo_path = Path(row["original_path"])
    thumb = (
        ensure_photo_thumbnail(conn, cfg, photo_id, photo_path)
        if photo_path.exists()
        else None
    )
    archive_row = conn.execute(
        """
        SELECT archived_panos.folder_id, archived_panos.reviewed, archive_folders.name AS folder_name
        FROM archived_panos
        LEFT JOIN archive_folders ON archive_folders.id = archived_panos.folder_id
        WHERE archived_panos.photo_id = ?
        """,
        (photo_id,),
    ).fetchone()
    tag_rows = conn.execute(
        """
        SELECT tags.id, tags.name, tags.tag_type
        FROM pano_tags
        JOIN tags ON tags.id = pano_tags.tag_id
        WHERE pano_tags.photo_id = ?
        ORDER BY tags.tag_type, tags.name
        """,
        (photo_id,),
    ).fetchall()
    collection_rows = conn.execute(
        """
        SELECT collections.id, collections.name
        FROM collection_items
        JOIN collections ON collections.id = collection_items.collection_id
        WHERE collection_items.photo_id = ?
        ORDER BY collections.name
        """,
        (photo_id,),
    ).fetchall()
    duplicate_rows = conn.execute(
        """
        SELECT *
        FROM pano_duplicates
        WHERE photo_id = ? OR duplicate_photo_id = ?
        ORDER BY id
        """,
        (photo_id, photo_id),
    ).fetchall()
    view_state = ensure_photo_view_state(conn, photo_id)
    return {
        **photo,
        "image_url": f"/api/photos/{photo_id}/image",
        "thumbnail_url": thumb["url"] if thumb else None,
        "thumbnail_width": thumb["width"] if thumb else None,
        "thumbnail_height": thumb["height"] if thumb else None,
        "archive_folder_id": archive_row["folder_id"] if archive_row else None,
        "archive_folder_name": archive_row["folder_name"] if archive_row else None,
        "reviewed": bool(archive_row["reviewed"]) if archive_row else False,
        "tags": [dict(row) for row in tag_rows],
        "collections": [dict(row) for row in collection_rows],
        "duplicates": [dict(row) for row in duplicate_rows],
        "viewer_state": dict(view_state) if view_state else None,
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
        raise HTTPException(
            status_code=400, detail="Area color must be a 6-digit hex value."
        )
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


def expand_photo_sources_events(raw_paths: list[str]):
    """Expand files/folders into importable photo paths, yielding progress.

    Folder (batch) expansion only accepts stitched 360 panos: DJI cards keep
    the raw stitch tiles in PANORAMA subfolders, and recursing a card or
    mission folder used to sweep those in alongside the stitched output.
    Explicitly selected files are trusted as-is. Yields throttled
    {"type": "scan", scanned, total, accepted} events for folder candidates,
    then {"type": "result", "paths": [...], "skipped_non_pano": n}.
    """
    from pano_namer.services.sd_card import is_stitched_pano

    # Enumerate first so scan progress has a total.
    entries: list[tuple[Path, bool]] = []  # (path, from_folder)
    for raw_path in raw_paths:
        source_path = ensure_path(raw_path)
        if source_path.is_dir():
            for child in sorted(source_path.rglob("*")):
                if child.is_file() and child.suffix.lower() in PHOTO_EXTENSIONS:
                    entries.append((child, True))
        elif source_path.suffix.lower() in PHOTO_EXTENSIONS:
            entries.append((source_path, False))

    expanded: list[Path] = []
    seen: set[Path] = set()
    skipped_non_pano = 0
    total = sum(1 for _, from_folder in entries if from_folder)
    scanned = 0
    for path, from_folder in entries:
        resolved = path.resolve() if from_folder else path
        if resolved in seen or path in seen:
            continue
        if from_folder:
            scanned += 1
            if not is_stitched_pano(path):
                skipped_non_pano += 1
            else:
                expanded.append(resolved)
                seen.add(resolved)
            if scanned % 5 == 0 or scanned == total:
                yield {
                    "type": "scan",
                    "scanned": scanned,
                    "total": total,
                    "accepted": len(expanded),
                }
        else:
            expanded.append(path)
            seen.add(path)
    yield {"type": "result", "paths": expanded, "skipped_non_pano": skipped_non_pano}


def expand_photo_sources(raw_paths: list[str]) -> tuple[list[Path], int]:
    """Non-streaming wrapper over expand_photo_sources_events."""
    for event in expand_photo_sources_events(raw_paths):
        if event["type"] == "result":
            return event["paths"], event["skipped_non_pano"]
    return [], 0


def refresh_pending_photo_matches(conn: sqlite3.Connection, project_id: int) -> None:
    try:
        from pyproj import Transformer
        from shapely import wkt
        from shapely.geometry import Point
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(
            status_code=500, detail=f"Missing dependency: {exc}"
        ) from exc

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
                projected_x, projected_y = transformer.transform(
                    row["gps_lon"], row["gps_lat"]
                )
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
                projected_x, projected_y = transformer.transform(
                    row["gps_lon"], row["gps_lat"]
                )
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
            (
                projected_x,
                projected_y,
                matched_area_id,
                match_mode,
                error,
                now,
                row["id"],
            ),
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


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or AppConfig.load()
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    db.initialize()
    storage = StorageService(cfg)
    # Overlays imported before tiling get a pyramid built in the background;
    # the map falls back to the single-image overlay until it is ready.
    overlay_tiles.backfill_overlay_tiles(db, cfg.data_dir)

    app = FastAPI(title="PANO PRO", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = cfg
    app.state.db = db
    app.state.storage = storage

    install_auth_gate(app)
    install_admin(app, cfg)

    app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")
    register_system_routes(app, cfg, db, STATIC_DIR)
    register_project_routes(app, cfg, db, storage)
    register_area_routes(app, db, storage)
    register_overlay_routes(app, cfg, db, storage)
    register_settings_routes(app, db, storage)
    site_insight_settings = SiteInsightSettings.from_env()
    register_site_insight_routes(app, site_insight_settings)

    @app.get(
        "/api/projects/{project_id}/photo-batches",
        response_model=list[PhotoBatchResponse],
    )
    def list_photo_batches(project_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            rows = conn.execute(
                """
                SELECT * FROM photo_batches
                WHERE project_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (project_id,),
            ).fetchall()
        return [row_to_photo_batch(row) for row in rows]

    @app.get("/api/projects/{project_id}/photos", response_model=list[PhotoResponse])
    def list_photos(project_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            rows = conn.execute(
                """
                SELECT photos.*, areas.name AS area_name
                FROM photos
                LEFT JOIN areas ON photos.matched_area_id = areas.id
                WHERE photos.project_id = ?
                ORDER BY photos.created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [row_to_photo(row) for row in rows]

    def import_photo_paths(
        project_id: int,
        paths: list[Path],
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        created_ids: list[int] = []
        import_results: list[dict[str, Any]] = []
        with db.connect() as conn:
            fetch_project(conn, project_id)
            existing_paths_snapshot = {
                row["original_path"]
                for row in conn.execute(
                    "SELECT original_path FROM photos WHERE project_id = ?",
                    (project_id,),
                ).fetchall()
            }

        prep_indices = [
            index
            for index, source_path in enumerate(paths)
            if str(source_path) not in existing_paths_snapshot
        ]
        prepared_by_index: dict[int, dict[str, Any]] = {}
        if prep_indices:
            max_workers = min(8, os.cpu_count() or 4)
            prep_paths = (paths[index] for index in prep_indices)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for index, prepared in zip(
                    prep_indices, executor.map(prepare_photo_import, prep_paths)
                ):
                    prepared_by_index[index] = prepared
                    if progress is not None:
                        progress(len(prepared_by_index), len(prep_indices))

        with db.connect() as conn:
            fetch_project(conn, project_id)
            batch_id = uuid4().hex
            now = utc_now()
            batch_cursor = conn.execute(
                """
                INSERT INTO photo_batches (
                    project_id, batch_uid, source_kind, status, photo_count,
                    created_at, updated_at
                )
                VALUES (?, ?, 'import', 'importing', 0, ?, ?)
                """,
                (project_id, batch_id, now, now),
            )
            photo_batch_id = batch_cursor.lastrowid
            existing_paths = {
                row["original_path"]
                for row in conn.execute(
                    "SELECT original_path FROM photos WHERE project_id = ?",
                    (project_id,),
                ).fetchall()
            }

            for index, source_path in enumerate(paths):
                source_value = str(source_path)
                if source_value in existing_paths:
                    import_results.append(
                        {
                            "path": source_value,
                            "status": "duplicate",
                            "detail": "Photo already exists in this template.",
                            "photo": None,
                        }
                    )
                    continue
                prepared = prepared_by_index.get(index)
                if prepared is None:
                    prepared = prepare_photo_import(source_path)
                if prepared["error"] is not None:
                    import_results.append(
                        {
                            "path": source_value,
                            "status": "error",
                            "detail": prepared["error"],
                            "photo": None,
                        }
                    )
                    continue
                meta = prepared["meta"]
                hash_value = prepared["hash_value"]
                cursor = conn.execute(
                    """
                    INSERT INTO photos (
                        project_id, batch_id, photo_batch_id, original_path, capture_ts, gps_lat, gps_lon,
                        projected_x, projected_y, matched_area_id, match_mode, proposed_filename,
                        applied, content_hash, error, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        batch_id,
                        photo_batch_id,
                        source_value,
                        meta["capture_ts"],
                        meta["gps_lat"],
                        meta["gps_lon"],
                        None,
                        None,
                        None,
                        None,
                        hash_value,
                        None,
                        now,
                        now,
                    ),
                )
                photo_id = cursor.lastrowid
                created_ids.append(photo_id)
                ensure_photo_thumbnail(
                    conn, cfg, photo_id, source_path, prepared["thumb"]
                )
                ensure_photo_view_state(conn, photo_id)
                weekly_name = weekly_collection_name(meta["capture_ts"])
                if weekly_name:
                    collection_row = ensure_collection_row(
                        conn,
                        weekly_name,
                        description="System-generated weekly collection based on ISO calendar week.",
                    )
                    add_photo_to_collection(
                        conn,
                        collection_row["id"],
                        photo_id,
                        audit_action="collection.auto_add_weekly",
                    )
                update_duplicate_pairs(conn, photo_id, hash_value)
                log_audit(
                    conn, "photo.import", "photo", photo_id, {"path": source_value}
                )
                existing_paths.add(source_value)
                import_results.append(
                    {
                        "path": source_value,
                        "status": "imported",
                        "detail": None,
                        "photo": None,
                    }
                )

            completed_at = utc_now()
            status = "imported" if created_ids else "empty"
            conn.execute(
                """
                UPDATE photo_batches
                SET status = ?, photo_count = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, len(created_ids), completed_at, completed_at, photo_batch_id),
            )
            if created_ids:
                refresh_pending_photo_matches(conn, project_id)
                refresh_all_system_tags(conn)
            conn.commit()

            rows = []
            if created_ids:
                rows = conn.execute(
                    f"""
                    SELECT photos.*, areas.name AS area_name
                    FROM photos
                    LEFT JOIN areas ON photos.matched_area_id = areas.id
                    WHERE photos.id IN ({','.join('?' for _ in created_ids)})
                    ORDER BY photos.id DESC
                    """,
                    created_ids,
                ).fetchall()
        photos_by_path = {row["original_path"]: row_to_photo(row) for row in rows}
        for result in import_results:
            if result["status"] == "imported":
                result["photo"] = photos_by_path.get(result["path"])
        imported = [
            result["photo"]
            for result in import_results
            if result["status"] == "imported" and result.get("photo")
        ]
        summary = {
            "imported": len(imported),
            "duplicates": sum(
                1 for result in import_results if result["status"] == "duplicate"
            ),
            "errors": sum(
                1 for result in import_results if result["status"] == "error"
            ),
        }
        return {"imported": imported, "results": import_results, "summary": summary}

    @app.post(
        "/api/projects/{project_id}/photos/import", response_model=PhotoImportResponse
    )
    def import_photos(project_id: int, payload: PhotoImportRequest) -> dict[str, Any]:
        paths, skipped_non_pano = expand_photo_sources(payload.paths)
        result = import_photo_paths(project_id, paths)
        result["summary"]["non_pano_skipped"] = skipped_non_pano
        return result

    @app.post("/api/projects/{project_id}/photos/import/stream")
    def import_photos_stream(
        project_id: int, payload: PhotoImportRequest
    ) -> StreamingResponse:
        # Validate before streaming: guards must be real HTTP errors.
        with db.connect() as conn:
            fetch_project(conn, project_id)

        def ndjson():
            try:
                paths: list[Path] = []
                skipped_non_pano = 0
                for event in expand_photo_sources_events(payload.paths):
                    if event["type"] == "result":
                        paths = event["paths"]
                        skipped_non_pano = event["skipped_non_pano"]
                    else:
                        yield json.dumps(
                            {
                                "stage": "scan",
                                "scanned": event["scanned"],
                                "total": event["total"],
                                "accepted": event["accepted"],
                            }
                        ) + "\n"

                # import_photo_paths reports prep progress via callback; a
                # queue bridges those callbacks into this generator.
                events: queue.Queue = queue.Queue()
                outcome: dict[str, Any] = {}

                def emit_progress(done: int, total: int) -> None:
                    if done % 3 == 0 or done == total:
                        events.put(
                            {"stage": "import", "processed": done, "total": total}
                        )

                def worker() -> None:
                    try:
                        outcome["result"] = import_photo_paths(
                            project_id, paths, progress=emit_progress
                        )
                    except Exception as exc:
                        outcome["error"] = str(exc)
                    finally:
                        events.put(None)

                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                while True:
                    item = events.get()
                    if item is None:
                        break
                    yield json.dumps(item) + "\n"
                thread.join()

                if "error" in outcome:
                    yield json.dumps(
                        {"stage": "error", "detail": outcome["error"]}
                    ) + "\n"
                    return
                summary = outcome["result"]["summary"]
                summary["non_pano_skipped"] = skipped_non_pano
                yield json.dumps({"stage": "done", "summary": summary}) + "\n"
            except Exception as exc:  # headers already sent; surface as event
                yield json.dumps({"stage": "error", "detail": str(exc)}) + "\n"

        return StreamingResponse(ndjson(), media_type="application/x-ndjson")

    @app.post(
        "/api/projects/{project_id}/photos/upload", response_model=PhotoImportResponse
    )
    async def upload_photos(project_id: int, request: Request) -> dict[str, Any]:
        form = await request.form()
        saved_paths: list[Path] = []
        for upload in form.getlist("files"):
            filename = safe_upload_name(getattr(upload, "filename", None))
            if Path(filename).suffix.lower() not in PHOTO_EXTENSIONS:
                continue
            saved_paths.append(
                await save_upload_to_project(storage, project_id, "photos", upload)
            )
        return import_photo_paths(project_id, saved_paths)

    @app.post("/api/projects/{project_id}/photos/remove")
    def remove_photos(project_id: int, payload: PhotoDeleteRequest) -> dict[str, int]:
        photo_ids = [
            photo_id for photo_id in payload.photo_ids if isinstance(photo_id, int)
        ]
        if not photo_ids:
            return {"removed": 0}

        placeholders = ",".join("?" for _ in photo_ids)
        with db.connect() as conn:
            fetch_project(conn, project_id)
            existing = conn.execute(
                f"SELECT id FROM photos WHERE project_id = ? AND id IN ({placeholders})",
                [project_id, *photo_ids],
            ).fetchall()
            if not existing:
                return {"removed": 0}
            existing_ids = [row["id"] for row in existing]
            conn.execute(
                f"DELETE FROM photos WHERE project_id = ? AND id IN ({','.join('?' for _ in existing_ids)})",
                [project_id, *existing_ids],
            )
            refresh_pending_photo_matches(conn, project_id)
            conn.commit()
        return {"removed": len(existing_ids)}

    @app.post(
        "/api/projects/{project_id}/rename-preview",
        response_model=RenamePreviewResponse,
    )
    def rename_preview(project_id: int, payload: RenameRunCreate) -> dict[str, Any]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            rows = fetch_pending_photo_rows(conn, project_id, payload.photo_ids)
        return preview_renames([dict(row) for row in rows])

    @app.put(
        "/api/projects/{project_id}/photos/{photo_id}", response_model=PhotoResponse
    )
    def update_photo(
        project_id: int, photo_id: int, payload: PhotoUpdateRequest
    ) -> dict[str, Any]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            photo = conn.execute(
                """
                SELECT photos.*, areas.name AS area_name
                FROM photos
                LEFT JOIN areas ON photos.matched_area_id = areas.id
                WHERE photos.project_id = ? AND photos.id = ?
                """,
                (project_id, photo_id),
            ).fetchone()
            if photo is None:
                raise HTTPException(status_code=404, detail="Photo not found")
            if photo["applied"]:
                raise HTTPException(
                    status_code=400, detail="Processed photos cannot be reassigned."
                )
            if payload.matched_area_id is not None:
                area = conn.execute(
                    "SELECT id FROM areas WHERE project_id = ? AND id = ? AND active = 1",
                    (project_id, payload.matched_area_id),
                ).fetchone()
                if area is None:
                    raise HTTPException(
                        status_code=400, detail="Selected area not found."
                    )

            conn.execute(
                """
                UPDATE photos
                SET matched_area_id = ?, match_mode = ?, error = NULL, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (
                    payload.matched_area_id,
                    "manual" if payload.matched_area_id is not None else None,
                    utc_now(),
                    photo_id,
                    project_id,
                ),
            )
            refresh_pending_photo_matches(conn, project_id)
            conn.commit()
            row = conn.execute(
                """
                SELECT photos.*, areas.name AS area_name
                FROM photos
                LEFT JOIN areas ON photos.matched_area_id = areas.id
                WHERE photos.project_id = ? AND photos.id = ?
                """,
                (project_id, photo_id),
            ).fetchone()
        return row_to_photo(row)

    @app.post(
        "/api/projects/{project_id}/rename-reservations/commit",
        response_model=RenameReservationsCommitResponse,
    )
    def commit_rename_reservations(
        project_id: int, payload: RenameReservationsCommitRequest
    ) -> dict[str, Any]:
        # Desktop-assisted rename deliberately separates central name allocation
        # from local filesystem mutation. The legacy /rename-runs endpoint below
        # still reserves and renames in one server-side transaction.
        with db.connect() as conn:
            try:
                fetch_project(conn, project_id)
                plans = reserve_plans_with_shared_naming(
                    conn, project_id, payload.photo_ids
                )
                if not plans:
                    conn.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail="No photos were eligible for filename reservation.",
                    )
                conn.commit()
            except HTTPException:
                if conn.in_transaction:
                    conn.rollback()
                raise
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

        reservations = [
            {
                "reservation_id": plan.reservation_id,
                "photo_id": plan.photo_id,
                "source_path": str(plan.source_path),
                "target_path": str(plan.target_path),
                "final_name": plan.final_name,
                "status": "reserved",
            }
            for plan in plans
            if plan.reservation_id is not None
        ]
        return {
            "summary": {"reserved": len(reservations)},
            "reservations": reservations,
        }

    @app.post(
        "/api/projects/{project_id}/rename-reservations/report-results",
        response_model=RenameReservationReportResponse,
    )
    def report_rename_reservation_results(
        project_id: int, payload: RenameReservationReportRequest
    ) -> dict[str, Any]:
        if not payload.results:
            raise HTTPException(
                status_code=400, detail="At least one rename result is required."
            )
        with db.connect() as conn:
            fetch_project(conn, project_id)
            results = report_filename_reservation_results(
                conn,
                project_id,
                [result.model_dump() for result in payload.results],
            )
            conn.commit()
        summary = {
            "applied": sum(
                1 for result in results if result.get("status") == "applied"
            ),
            "failed": sum(1 for result in results if result.get("status") == "failed"),
            "errors": sum(1 for result in results if result.get("status") == "error"),
        }
        return {"summary": summary, "results": results}

    @app.post(
        "/api/projects/{project_id}/rename-runs", response_model=RenameRunResponse
    )
    def run_rename(project_id: int, payload: RenameRunCreate) -> dict[str, Any]:
        started_at = utc_now()
        with db.connect() as conn:
            try:
                fetch_project(conn, project_id)
                plans = reserve_plans_with_shared_naming(
                    conn, project_id, payload.photo_ids
                )
                if not plans:
                    conn.rollback()
                    raise HTTPException(
                        status_code=400, detail="No photos were eligible for rename."
                    )

                try:
                    apply_results = apply_rename_plan(plans)
                except Exception as exc:
                    failed_at = utc_now()
                    reservation_ids = [
                        plan.reservation_id
                        for plan in plans
                        if plan.reservation_id is not None
                    ]
                    if reservation_ids:
                        placeholders = ",".join("?" for _ in reservation_ids)
                        conn.execute(
                            f"""
                            UPDATE filename_reservations
                            SET reservation_status = 'failed', updated_at = ?
                            WHERE project_id = ? AND id IN ({placeholders})
                            """,
                            [failed_at, project_id, *reservation_ids],
                        )
                    conn.commit()
                    raise HTTPException(
                        status_code=500, detail=f"Rename failed: {exc}"
                    ) from exc

                plan_lookup = {plan.photo_id: plan for plan in plans}
                for result in apply_results:
                    photo_id = result["photo_id"]
                    plan = plan_lookup[photo_id]
                    result_at = utc_now()
                    if result["status"] in {"renamed", "unchanged"}:
                        conn.execute(
                            "UPDATE photos SET original_path = ?, proposed_filename = ?, applied = 1, error = NULL, updated_at = ? WHERE id = ?",
                            (
                                str(plan.target_path),
                                plan.final_name,
                                result_at,
                                photo_id,
                            ),
                        )
                        conn.execute(
                            """
                            UPDATE filename_reservations
                            SET reservation_status = 'applied', applied_at = ?, updated_at = ?
                            WHERE project_id = ? AND id = ?
                            """,
                            (result_at, result_at, project_id, plan.reservation_id),
                        )
                    else:
                        conn.execute(
                            "UPDATE photos SET error = ?, updated_at = ? WHERE id = ?",
                            (
                                "Photo file not found at saved path.",
                                result_at,
                                photo_id,
                            ),
                        )
                        conn.execute(
                            """
                            UPDATE filename_reservations
                            SET reservation_status = 'failed', updated_at = ?
                            WHERE project_id = ? AND id = ?
                            """,
                            (result_at, project_id, plan.reservation_id),
                        )

                summary = build_rename_summary(apply_results)
                cursor = conn.execute(
                    """
                    INSERT INTO rename_runs (
                        project_id, batch_id, started_at, completed_at,
                        rollback_started_at, rollback_completed_at,
                        summary_json, results_json, rollback_results_json
                    )
                    VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
                    """,
                    (
                        project_id,
                        uuid4().hex,
                        started_at,
                        utc_now(),
                        dumps_json(summary),
                        dumps_json(apply_results),
                    ),
                )
                run_id = cursor.lastrowid
                reservation_ids = [
                    plan.reservation_id
                    for plan in plans
                    if plan.reservation_id is not None
                ]
                if reservation_ids:
                    placeholders = ",".join("?" for _ in reservation_ids)
                    conn.execute(
                        f"""
                        UPDATE filename_reservations
                        SET rename_run_id = ?, updated_at = ?
                        WHERE project_id = ? AND id IN ({placeholders})
                        """,
                        [run_id, utc_now(), project_id, *reservation_ids],
                    )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM rename_runs WHERE id = ?", (run_id,)
                ).fetchone()
            except HTTPException:
                if conn.in_transaction:
                    conn.rollback()
                raise
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

        return row_to_rename_run(row)

    register_smart_routes(app, db, import_photo_paths, run_rename)

    @app.post(
        "/api/projects/{project_id}/rename-runs/{run_id}/rollback",
        response_model=RenameRunResponse,
    )
    def rollback_rename_run(project_id: int, run_id: int) -> dict[str, Any]:
        rollback_started_at = utc_now()
        with db.connect() as conn:
            fetch_project(conn, project_id)
            latest_row = conn.execute(
                """
                SELECT * FROM rename_runs
                WHERE project_id = ? AND completed_at IS NOT NULL
                ORDER BY completed_at DESC, id DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            if latest_row is None or latest_row["id"] != run_id:
                raise HTTPException(
                    status_code=400,
                    detail="Only the most recent rename run can be rolled back.",
                )
            if latest_row["rollback_completed_at"] is not None:
                raise HTTPException(
                    status_code=400,
                    detail="This rename run has already been rolled back.",
                )

            run_results = loads_json(latest_row["results_json"], [])
            rollback_results = rollback_rename_results(run_results)
            rollback_lookup = {
                result["photo_id"]: result for result in rollback_results
            }
            for result in run_results:
                rollback_result = rollback_lookup.get(result["photo_id"])
                if rollback_result is None:
                    continue
                if rollback_result["status"] in {"rolled_back", "restored_pending"}:
                    conn.execute(
                        """
                        UPDATE photos
                        SET original_path = ?, applied = 0, error = NULL, updated_at = ?
                        WHERE id = ? AND project_id = ?
                        """,
                        (
                            result["source_path"],
                            utc_now(),
                            result["photo_id"],
                            project_id,
                        ),
                    )
                elif rollback_result["status"] in {
                    "missing_target",
                    "blocked_target_exists",
                    "rollback_error",
                }:
                    detail = rollback_result.get("detail")
                    message = detail or rollback_result["status"].replace("_", " ")
                    conn.execute(
                        "UPDATE photos SET error = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                        (
                            f"Rollback failed: {message}.",
                            utc_now(),
                            result["photo_id"],
                            project_id,
                        ),
                    )

            rolled_back_photo_ids = [
                result["photo_id"]
                for result in rollback_results
                if result.get("status") in {"rolled_back", "restored_pending"}
            ]
            if rolled_back_photo_ids:
                placeholders = ",".join("?" for _ in rolled_back_photo_ids)
                conn.execute(
                    f"""
                    UPDATE filename_reservations
                    SET reservation_status = 'rolled_back', updated_at = ?
                    WHERE project_id = ? AND rename_run_id = ? AND photo_id IN ({placeholders})
                    """,
                    [utc_now(), project_id, run_id, *rolled_back_photo_ids],
                )

            refresh_pending_photo_matches(conn, project_id)
            conn.execute(
                """
                UPDATE rename_runs
                SET rollback_started_at = ?, rollback_completed_at = ?, rollback_results_json = ?
                WHERE id = ? AND project_id = ?
                """,
                (
                    rollback_started_at,
                    utc_now(),
                    dumps_json(rollback_results),
                    run_id,
                    project_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM rename_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return row_to_rename_run(row)

    @app.get(
        "/api/projects/{project_id}/rename-runs", response_model=list[RenameRunResponse]
    )
    def list_rename_runs(project_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            rows = conn.execute(
                "SELECT * FROM rename_runs WHERE project_id = ? ORDER BY started_at DESC",
                (project_id,),
            ).fetchall()
        return [row_to_rename_run(row) for row in rows]

    @app.get("/api/projects/{project_id}/map-data", response_model=MapDataResponse)
    def map_data(project_id: int) -> dict[str, Any]:
        try:
            from shapely import wkt
        except ImportError as exc:  # pragma: no cover
            raise HTTPException(
                status_code=500, detail=f"Missing dependency: {exc}"
            ) from exc

        with db.connect() as conn:
            project = fetch_project(conn, project_id)
            area_rows = conn.execute(
                "SELECT * FROM areas WHERE project_id = ? AND active = 1 ORDER BY name",
                (project_id,),
            ).fetchall()
            photo_rows = conn.execute(
                """
                SELECT photos.*, areas.name AS area_name
                FROM photos
                LEFT JOIN areas ON photos.matched_area_id = areas.id
                WHERE photos.project_id = ?
                ORDER BY photos.created_at DESC
                """,
                (project_id,),
            ).fetchall()
            overlay_row = conn.execute(
                "SELECT * FROM overlays WHERE project_id = ? AND active = 1 ORDER BY created_at DESC, id DESC LIMIT 1",
                (project_id,),
            ).fetchone()

        areas_payload = []
        for row in area_rows:
            geometry = wkt.loads(row["footprint_wkt"])
            if geometry.is_empty:
                continue
            if geometry.geom_type == "Polygon":
                parts = [[[x, y] for x, y in geometry.exterior.coords]]
                label_anchor = list(geometry.representative_point().coords)[0]
            else:
                polygons = [
                    polygon
                    for polygon in getattr(geometry, "geoms", [])
                    if not polygon.is_empty
                ]
                parts = [
                    [[x, y] for x, y in polygon.exterior.coords] for polygon in polygons
                ]
                largest = (
                    max(polygons, key=lambda polygon: polygon.area)
                    if polygons
                    else geometry
                )
                label_anchor = list(largest.representative_point().coords)[0]
            areas_payload.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "display_color": row["display_color"] or DEFAULT_AREA_COLOR,
                    "bbox": loads_json(row["footprint_bbox_json"], []),
                    "parts": parts,
                    "label_anchor": [label_anchor[0], label_anchor[1]],
                }
            )

        photos_payload = [
            {
                "id": row["id"],
                "path": row["original_path"],
                "capture_ts": row["capture_ts"],
                "projected_x": row["projected_x"],
                "projected_y": row["projected_y"],
                "match_mode": row["match_mode"],
                "area_name": row["area_name"],
                "proposed_filename": row["proposed_filename"],
                "applied": bool(row["applied"]),
                "error": row["error"],
            }
            for row in photo_rows
        ]

        return {
            "project": row_to_project(project),
            "overlay": row_to_overlay(overlay_row),
            "areas": areas_payload,
            "photos": photos_payload,
        }

    @app.get("/api/photos/{photo_id}/image")
    def photo_image(photo_id: int) -> FileResponse:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT original_path FROM photos WHERE id = ?", (photo_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        path = Path(row["original_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Photo file not found")
        return FileResponse(path)

    @app.get("/api/photos/{photo_id}/thumbnail")
    def photo_thumbnail(photo_id: int) -> FileResponse:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT original_path FROM photos WHERE id = ?", (photo_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Photo not found")
            thumb = ensure_photo_thumbnail(
                conn, cfg, photo_id, Path(row["original_path"])
            )
            conn.commit()
        if thumb is None:
            raise HTTPException(status_code=404, detail="Thumbnail not available")
        return FileResponse(Path(thumb["path"]))

    @app.get("/api/archive-folders")
    def list_archive_folders() -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM archive_folders ORDER BY COALESCE(parent_id, 0), name"
            ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/archive-folders")
    def create_archive_folder(payload: ArchiveFolderCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO archive_folders (parent_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (payload.parent_id, payload.name.strip(), now, now),
            )
            folder_id = cursor.lastrowid
            conn.commit()
            row = conn.execute(
                "SELECT * FROM archive_folders WHERE id = ?", (folder_id,)
            ).fetchone()
        return dict(row)

    @app.delete("/api/archive-folders/{folder_id}")
    def delete_archive_folder(folder_id: int) -> dict[str, bool]:
        with db.connect() as conn:
            conn.execute("DELETE FROM archive_folders WHERE id = ?", (folder_id,))
            conn.commit()
        return {"ok": True}

    @app.post("/api/archive/assign")
    def assign_archive_folder(payload: ArchiveAssignRequest) -> dict[str, int]:
        now = utc_now()
        with db.connect() as conn:
            for photo_id in payload.photo_ids:
                conn.execute(
                    """
                    INSERT INTO archived_panos (photo_id, folder_id, reviewed, archived_at, updated_at)
                    VALUES (?, ?, 0, ?, ?)
                    ON CONFLICT(photo_id) DO UPDATE SET
                        folder_id = excluded.folder_id,
                        updated_at = excluded.updated_at
                    """,
                    (photo_id, payload.folder_id, now, now),
                )
                refresh_system_tags(conn, photo_id)
                log_audit(
                    conn,
                    "archive.assign",
                    "photo",
                    photo_id,
                    {"folder_id": payload.folder_id},
                )
            conn.commit()
        return {"updated": len(payload.photo_ids)}

    @app.get("/api/archive/library")
    def archive_library() -> dict[str, Any]:
        with db.connect() as conn:
            folder_rows = conn.execute(
                "SELECT * FROM archive_folders ORDER BY COALESCE(parent_id, 0), name"
            ).fetchall()
            photo_rows = conn.execute("""
                SELECT photos.id
                FROM archived_panos
                JOIN photos ON photos.id = archived_panos.photo_id
                ORDER BY photos.created_at DESC
                """).fetchall()
            photos = [photo_detail_payload(conn, cfg, row["id"]) for row in photo_rows]
            conn.commit()
        return {"folders": [dict(row) for row in folder_rows], "photos": photos}

    @app.get("/api/collections")
    def list_collections() -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT collections.*, COUNT(collection_items.id) AS item_count
                FROM collections
                LEFT JOIN collection_items ON collection_items.collection_id = collections.id
                GROUP BY collections.id
                ORDER BY collections.name
                """).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/collections")
    def create_collection(payload: CollectionCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO collections (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (payload.name.strip(), payload.description, now, now),
            )
            collection_id = cursor.lastrowid
            log_audit(
                conn,
                "collection.create",
                "collection",
                collection_id,
                {"name": payload.name},
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM collections WHERE id = ?", (collection_id,)
            ).fetchone()
        return dict(row)

    @app.put("/api/collections/{collection_id}")
    def update_collection(
        collection_id: int, payload: CollectionUpdate
    ) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM collections WHERE id = ?", (collection_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Collection not found")
            conn.execute(
                """
                UPDATE collections
                SET name = ?, description = ?, cover_photo_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.name or row["name"],
                    (
                        payload.description
                        if payload.description is not None
                        else row["description"]
                    ),
                    (
                        payload.cover_photo_id
                        if payload.cover_photo_id is not None
                        else row["cover_photo_id"]
                    ),
                    now,
                    collection_id,
                ),
            )
            log_audit(
                conn,
                "collection.update",
                "collection",
                collection_id,
                payload.model_dump(),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM collections WHERE id = ?", (collection_id,)
            ).fetchone()
        return dict(updated)

    @app.delete("/api/collections/{collection_id}")
    def delete_collection(collection_id: int) -> dict[str, bool]:
        with db.connect() as conn:
            conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
            log_audit(conn, "collection.delete", "collection", collection_id)
            conn.commit()
        return {"ok": True}

    @app.post("/api/collections/{collection_id}/items")
    def add_collection_items(
        collection_id: int, payload: CollectionItemsRequest
    ) -> dict[str, int]:
        with db.connect() as conn:
            for photo_id in payload.photo_ids:
                add_photo_to_collection(conn, collection_id, photo_id)
            conn.commit()
        return {"added": len(payload.photo_ids)}

    @app.api_route("/api/collections/{collection_id}/items", methods=["DELETE"])
    def remove_collection_items(
        collection_id: int, payload: CollectionItemsRequest
    ) -> dict[str, int]:
        with db.connect() as conn:
            for photo_id in payload.photo_ids:
                conn.execute(
                    "DELETE FROM collection_items WHERE collection_id = ? AND photo_id = ?",
                    (collection_id, photo_id),
                )
                refresh_system_tags(conn, photo_id)
                log_audit(
                    conn,
                    "collection.remove_photo",
                    "collection",
                    collection_id,
                    {"photo_id": photo_id},
                )
            conn.commit()
        return {"removed": len(payload.photo_ids)}

    @app.get("/api/collections/{collection_id}/detail")
    def collection_detail(collection_id: int) -> dict[str, Any]:
        with db.connect() as conn:
            collection = conn.execute(
                "SELECT * FROM collections WHERE id = ?", (collection_id,)
            ).fetchone()
            if collection is None:
                raise HTTPException(status_code=404, detail="Collection not found")
            item_rows = conn.execute(
                """
                SELECT collection_items.photo_id
                FROM collection_items
                JOIN photos ON photos.id = collection_items.photo_id
                WHERE collection_items.collection_id = ?
                ORDER BY collection_items.item_order, collection_items.id
                """,
                (collection_id,),
            ).fetchall()
            photos = [
                photo_detail_payload(conn, cfg, row["photo_id"]) for row in item_rows
            ]
            conn.commit()
        map_payload = [
            {
                "id": photo["id"],
                "name": (
                    base_name
                    if (base_name := Path(photo["original_path"]).name)
                    else str(photo["id"])
                ),
                "projected_x": photo["projected_x"],
                "projected_y": photo["projected_y"],
                "thumbnail_url": photo["thumbnail_url"],
            }
            for photo in photos
        ]
        return {
            "collection": dict(collection),
            "photos": photos,
            "map_photos": map_payload,
        }

    @app.get("/api/tags")
    def list_tags() -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM tags ORDER BY tag_type, name").fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/tags")
    def create_tag(payload: TagCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO tags (name, tag_type, created_at, updated_at)
                VALUES (?, 'user', ?, ?)
                ON CONFLICT(name) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (payload.name.strip(), now, now),
            )
            row = conn.execute(
                "SELECT * FROM tags WHERE name = ?", (payload.name.strip(),)
            ).fetchone()
            conn.commit()
        return dict(row)

    @app.post("/api/photos/{photo_id}/tags")
    def assign_photo_tags(photo_id: int, payload: PhotoTagsRequest) -> dict[str, int]:
        with db.connect() as conn:
            for tag_id in payload.tag_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO pano_tags (photo_id, tag_id, created_at) VALUES (?, ?, ?)",
                    (photo_id, tag_id, utc_now()),
                )
            log_audit(
                conn, "tag.assign", "photo", photo_id, {"tag_ids": payload.tag_ids}
            )
            conn.commit()
        return {"assigned": len(payload.tag_ids)}

    @app.api_route("/api/photos/{photo_id}/tags", methods=["DELETE"])
    def remove_photo_tags(photo_id: int, payload: PhotoTagsRequest) -> dict[str, int]:
        with db.connect() as conn:
            for tag_id in payload.tag_ids:
                conn.execute(
                    """
                    DELETE FROM pano_tags
                    WHERE photo_id = ? AND tag_id = ? AND tag_id IN (SELECT id FROM tags WHERE tag_type = 'user')
                    """,
                    (photo_id, tag_id),
                )
            log_audit(
                conn, "tag.remove", "photo", photo_id, {"tag_ids": payload.tag_ids}
            )
            conn.commit()
        return {"removed": len(payload.tag_ids)}

    @app.get("/api/saved-filters")
    def list_saved_filters() -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_filters ORDER BY filter_scope, name"
            ).fetchall()
        return [
            {**dict(row), "config": loads_json(row["config_json"], {})} for row in rows
        ]

    @app.post("/api/saved-filters")
    def create_saved_filter(payload: SavedFilterCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO saved_filters (name, filter_scope, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload.name.strip(),
                    payload.filter_scope,
                    dumps_json(payload.config),
                    now,
                    now,
                ),
            )
            filter_id = cursor.lastrowid
            conn.commit()
            row = conn.execute(
                "SELECT * FROM saved_filters WHERE id = ?", (filter_id,)
            ).fetchone()
        return {**dict(row), "config": loads_json(row["config_json"], {})}

    @app.get("/api/photos/{photo_id}/viewer")
    def photo_viewer_payload(
        photo_id: int, collection_id: int | None = None
    ) -> dict[str, Any]:
        with db.connect() as conn:
            photo = photo_detail_payload(conn, cfg, photo_id)
            north_offset = float(
                (photo.get("viewer_state") or {}).get("north_offset") or 0
            )
            annotations = conn.execute(
                "SELECT * FROM pano_annotations WHERE photo_id = ? ORDER BY id",
                (photo_id,),
            ).fetchall()
            notes = conn.execute(
                "SELECT * FROM pano_notes WHERE photo_id = ? ORDER BY created_at DESC",
                (photo_id,),
            ).fetchall()
            issues = conn.execute(
                "SELECT * FROM pano_issues WHERE photo_id = ? ORDER BY created_at DESC",
                (photo_id,),
            ).fetchall()
            manual_hotspots = conn.execute(
                "SELECT * FROM pano_hotspots WHERE photo_id = ? ORDER BY id",
                (photo_id,),
            ).fetchall()
            if collection_id is not None:
                neighbor_rows = conn.execute(
                    """
                    SELECT photos.id, photos.original_path, photos.projected_x, photos.projected_y
                    FROM collection_items
                    JOIN photos ON photos.id = collection_items.photo_id
                    WHERE collection_items.collection_id = ? AND photos.id != ? AND photos.projected_x IS NOT NULL AND photos.projected_y IS NOT NULL
                    ORDER BY ((photos.projected_x - ?) * (photos.projected_x - ?) + (photos.projected_y - ?) * (photos.projected_y - ?)) ASC
                    LIMIT 4
                    """,
                    (
                        collection_id,
                        photo_id,
                        photo["projected_x"] or 0,
                        photo["projected_x"] or 0,
                        photo["projected_y"] or 0,
                        photo["projected_y"] or 0,
                    ),
                ).fetchall()
            else:
                neighbor_rows = conn.execute(
                    """
                    SELECT id, original_path, projected_x, projected_y
                    FROM photos
                    WHERE id != ? AND project_id = ? AND projected_x IS NOT NULL AND projected_y IS NOT NULL
                    ORDER BY ((projected_x - ?) * (projected_x - ?) + (projected_y - ?) * (projected_y - ?)) ASC
                    LIMIT 4
                    """,
                    (
                        photo_id,
                        photo["project_id"],
                        photo["projected_x"] or 0,
                        photo["projected_x"] or 0,
                        photo["projected_y"] or 0,
                        photo["projected_y"] or 0,
                    ),
                ).fetchall()
            auto_hotspots = []
            for index, row in enumerate(neighbor_rows):
                if None not in (
                    photo["projected_x"],
                    photo["projected_y"],
                    row["projected_x"],
                    row["projected_y"],
                ):
                    bearing = bearing_from_projected(
                        float(photo["projected_x"]),
                        float(photo["projected_y"]),
                        float(row["projected_x"]),
                        float(row["projected_y"]),
                    )
                    yaw = normalize_degrees(bearing + north_offset)
                else:
                    yaw = -45 + (index * 30)
                auto_hotspots.append(
                    {
                        "id": f"auto-{row['id']}",
                        "target_photo_id": row["id"],
                        "yaw": yaw,
                        "pitch": -5,
                        "label": Path(row["original_path"]).name,
                        "hotspot_type": "auto",
                        "disabled": False,
                    }
                )
            conn.commit()
        return {
            "photo": photo,
            "annotations": [
                dict(row) | {"style": loads_json(row["style_json"], {})}
                for row in annotations
            ],
            "notes": [dict(row) for row in notes],
            "issues": [dict(row) for row in issues],
            "hotspots": [dict(row) for row in manual_hotspots] + auto_hotspots,
        }

    @app.put("/api/photos/{photo_id}/viewer-state")
    def update_viewer_state(
        photo_id: int, payload: ViewerStateUpdate
    ) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO pano_view_state (photo_id, north_offset, default_yaw, default_pitch, default_fov, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(photo_id) DO UPDATE SET
                    north_offset = excluded.north_offset,
                    default_yaw = excluded.default_yaw,
                    default_pitch = excluded.default_pitch,
                    default_fov = excluded.default_fov,
                    updated_at = excluded.updated_at
                """,
                (
                    photo_id,
                    payload.north_offset,
                    payload.default_yaw,
                    payload.default_pitch,
                    payload.default_fov,
                    now,
                ),
            )
            log_audit(
                conn, "viewer_state.update", "photo", photo_id, payload.model_dump()
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM pano_view_state WHERE photo_id = ?", (photo_id,)
            ).fetchone()
        return dict(row)

    @app.get("/api/photos/{photo_id}/annotations")
    def list_annotations(photo_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pano_annotations WHERE photo_id = ? ORDER BY id",
                (photo_id,),
            ).fetchall()
        return [
            dict(row) | {"style": loads_json(row["style_json"], {})} for row in rows
        ]

    @app.post("/api/photos/{photo_id}/annotations")
    def create_annotation(photo_id: int, payload: AnnotationCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pano_annotations (photo_id, annotation_type, label, yaw, pitch, style_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    photo_id,
                    payload.annotation_type,
                    payload.label,
                    payload.yaw,
                    payload.pitch,
                    dumps_json(payload.style),
                    now,
                    now,
                ),
            )
            annotation_id = cursor.lastrowid
            log_audit(
                conn, "annotation.create", "photo", photo_id, payload.model_dump()
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM pano_annotations WHERE id = ?", (annotation_id,)
            ).fetchone()
        return dict(row) | {"style": loads_json(row["style_json"], {})}

    @app.delete("/api/annotations/{annotation_id}")
    def delete_annotation(annotation_id: int) -> dict[str, bool]:
        with db.connect() as conn:
            conn.execute("DELETE FROM pano_annotations WHERE id = ?", (annotation_id,))
            conn.commit()
        return {"ok": True}

    @app.get("/api/photos/{photo_id}/notes")
    def list_notes(photo_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pano_notes WHERE photo_id = ? ORDER BY created_at DESC",
                (photo_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/photos/{photo_id}/notes")
    def create_note(photo_id: int, payload: NoteCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO pano_notes (photo_id, note_text, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (photo_id, payload.note_text, now, now),
            )
            note_id = cursor.lastrowid
            log_audit(conn, "note.create", "photo", photo_id, payload.model_dump())
            conn.commit()
            row = conn.execute(
                "SELECT * FROM pano_notes WHERE id = ?", (note_id,)
            ).fetchone()
        return dict(row)

    @app.delete("/api/notes/{note_id}")
    def delete_note(note_id: int) -> dict[str, bool]:
        with db.connect() as conn:
            conn.execute("DELETE FROM pano_notes WHERE id = ?", (note_id,))
            conn.commit()
        return {"ok": True}

    @app.get("/api/photos/{photo_id}/issues")
    def list_issues(photo_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pano_issues WHERE photo_id = ? ORDER BY created_at DESC",
                (photo_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/photos/{photo_id}/issues")
    def create_issue(photo_id: int, payload: IssueCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pano_issues (photo_id, title, issue_text, severity, status, assigned_to, yaw, pitch, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    photo_id,
                    payload.title,
                    payload.issue_text,
                    payload.severity,
                    payload.status,
                    payload.assigned_to,
                    payload.yaw,
                    payload.pitch,
                    now,
                    now,
                ),
            )
            issue_id = cursor.lastrowid
            log_audit(conn, "issue.create", "photo", photo_id, payload.model_dump())
            conn.commit()
            row = conn.execute(
                "SELECT * FROM pano_issues WHERE id = ?", (issue_id,)
            ).fetchone()
        return dict(row)

    @app.delete("/api/issues/{issue_id}")
    def delete_issue(issue_id: int) -> dict[str, bool]:
        with db.connect() as conn:
            conn.execute("DELETE FROM pano_issues WHERE id = ?", (issue_id,))
            conn.commit()
        return {"ok": True}

    @app.post("/api/photos/{photo_id}/hotspots")
    def create_hotspot(photo_id: int, payload: HotspotCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pano_hotspots (photo_id, target_photo_id, yaw, pitch, label, hotspot_type, disabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'manual', ?, ?, ?)
                """,
                (
                    photo_id,
                    payload.target_photo_id,
                    payload.yaw,
                    payload.pitch,
                    payload.label,
                    1 if payload.disabled else 0,
                    now,
                    now,
                ),
            )
            hotspot_id = cursor.lastrowid
            log_audit(conn, "hotspot.create", "photo", photo_id, payload.model_dump())
            conn.commit()
            row = conn.execute(
                "SELECT * FROM pano_hotspots WHERE id = ?", (hotspot_id,)
            ).fetchone()
        return dict(row)

    @app.put("/api/hotspots/{hotspot_id}")
    def update_hotspot(hotspot_id: int, payload: HotspotCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE pano_hotspots
                SET target_photo_id = ?, yaw = ?, pitch = ?, label = ?, disabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.target_photo_id,
                    payload.yaw,
                    payload.pitch,
                    payload.label,
                    1 if payload.disabled else 0,
                    now,
                    hotspot_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM pano_hotspots WHERE id = ?", (hotspot_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Hotspot not found")
        return dict(row)

    @app.delete("/api/hotspots/{hotspot_id}")
    def delete_hotspot(hotspot_id: int) -> dict[str, bool]:
        with db.connect() as conn:
            conn.execute("DELETE FROM pano_hotspots WHERE id = ?", (hotspot_id,))
            conn.commit()
        return {"ok": True}

    @app.get("/api/projects/{project_id}/duplicates")
    def list_duplicates(project_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT pano_duplicates.*, p1.original_path AS photo_path, p2.original_path AS duplicate_path
                FROM pano_duplicates
                JOIN photos AS p1 ON p1.id = pano_duplicates.photo_id
                JOIN photos AS p2 ON p2.id = pano_duplicates.duplicate_photo_id
                WHERE p1.project_id = ? OR p2.project_id = ?
                ORDER BY pano_duplicates.created_at DESC
                """,
                (project_id, project_id),
            ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/projects/{project_id}/duplicates/scan")
    def scan_duplicates(project_id: int) -> dict[str, int]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, content_hash FROM photos WHERE project_id = ? AND content_hash IS NOT NULL",
                (project_id,),
            ).fetchall()
            grouped: dict[str, list[int]] = {}
            for row in rows:
                grouped.setdefault(row["content_hash"], []).append(row["id"])
            conn.execute(
                """
                DELETE FROM pano_duplicates
                WHERE photo_id IN (SELECT id FROM photos WHERE project_id = ?)
                   OR duplicate_photo_id IN (SELECT id FROM photos WHERE project_id = ?)
                """,
                (project_id, project_id),
            )
            inserted = 0
            now = utc_now()
            for hash_value, photo_ids in grouped.items():
                if len(photo_ids) < 2:
                    continue
                for index, left in enumerate(sorted(photo_ids)):
                    for right in sorted(photo_ids)[index + 1 :]:
                        conn.execute(
                            """
                            INSERT INTO pano_duplicates (photo_id, duplicate_photo_id, content_hash, status, created_at)
                            VALUES (?, ?, ?, 'detected', ?)
                            """,
                            (left, right, hash_value, now),
                        )
                        inserted += 1
            conn.commit()
        return {"duplicates": inserted}

    @app.put("/api/photos/{photo_id}/review")
    def update_review(photo_id: int, payload: ReviewUpdate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO archived_panos (photo_id, folder_id, reviewed, archived_at, updated_at)
                VALUES (?, NULL, ?, ?, ?)
                ON CONFLICT(photo_id) DO UPDATE SET reviewed = excluded.reviewed, updated_at = excluded.updated_at
                """,
                (photo_id, 1 if payload.reviewed else 0, now, now),
            )
            log_audit(
                conn, "review.update", "photo", photo_id, {"reviewed": payload.reviewed}
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM archived_panos WHERE photo_id = ?", (photo_id,)
            ).fetchone()
        return dict(row)

    @app.get("/api/audit-events")
    def list_audit_events(limit: int = 200) -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            dict(row) | {"payload": loads_json(row["payload_json"], {})} for row in rows
        ]

    @app.get("/api/collections/{collection_id}/report.csv")
    def export_collection_csv(collection_id: int) -> FileResponse:
        import csv

        report_dir = cfg.data_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"collection_{collection_id}.csv"
        with db.connect() as conn:
            detail = collection_detail(collection_id)
            with report_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Collection", detail["collection"]["name"]])
                writer.writerow(["Photo ID", "File", "Area", "Tags", "Issues", "Notes"])
                for photo in detail["photos"]:
                    writer.writerow(
                        [
                            photo["id"],
                            Path(photo["original_path"]).name,
                            photo["area_name"] or "",
                            ", ".join(tag["name"] for tag in photo["tags"]),
                            len(
                                conn.execute(
                                    "SELECT id FROM pano_issues WHERE photo_id = ?",
                                    (photo["id"],),
                                ).fetchall()
                            ),
                            len(
                                conn.execute(
                                    "SELECT id FROM pano_notes WHERE photo_id = ?",
                                    (photo["id"],),
                                ).fetchall()
                            ),
                        ]
                    )
        return FileResponse(report_path, filename=report_path.name)

    @app.get("/api/collections/{collection_id}/report.pdf")
    def export_collection_pdf(collection_id: int) -> FileResponse:
        import fitz

        report_dir = cfg.data_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"collection_{collection_id}.pdf"
        detail = collection_detail(collection_id)
        document = fitz.open()
        page = document.new_page()
        page.insert_text(
            (48, 48),
            f"PANO PRO Collection Report: {detail['collection']['name']}",
            fontsize=18,
        )
        y = 84
        for photo in detail["photos"][:30]:
            tags = ", ".join(tag["name"] for tag in photo["tags"][:4])
            page.insert_text(
                (48, y),
                f"{Path(photo['original_path']).name} | {photo['area_name'] or '-'} | {tags}",
                fontsize=10,
            )
            y += 16
            if y > 760:
                page = document.new_page()
                y = 48
        document.save(report_path)
        document.close()
        return FileResponse(report_path, filename=report_path.name)

    return app


app = create_app()
