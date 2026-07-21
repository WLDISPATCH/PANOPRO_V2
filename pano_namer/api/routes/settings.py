from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from pano_namer.config import FIXED_CRS
from pano_namer.database import Database
from pano_namer.schemas import (
    AreaSyncSummary,
    CloudPanosResponse,
    GlobalAreaSyncRequest,
    GlobalAreaSyncSummary,
    SharedNamingBackfillResponse,
    SharedNamingPreviewResponse,
    SharedNamingSettingsPayload,
    SharedNamingSettingsResponse,
    SharedNamingTestResponse,
)
from pano_namer.services import area_sync, overlay_sync, pano_registry, shared_naming

_SYNC_COUNTER_KEYS = (
    "pulled_new", "pulled_updated", "pushed_new", "pushed_updated",
    "deactivated", "tombstoned", "skipped",
)


def _merge_overlay_counts(result: dict, overlay: dict) -> dict:
    # Overlay sync rides area sync; fold its counts into the same summary.
    if overlay.get("ok"):
        for key in _SYNC_COUNTER_KEYS:
            result[key] = result.get(key, 0) + overlay.get(key, 0)
    return result
from pano_namer.services.shared_naming import (
    SharedNamingError,
    SharedNamingSettings,
)
from pano_namer.services.storage import StorageService

from .projects import fetch_project


def register_settings_routes(app: FastAPI, db: Database, storage: StorageService) -> None:
    def settings_response(settings: SharedNamingSettings) -> dict[str, Any]:
        return {
            "enabled": settings.enabled,
            "supabase_url": settings.supabase_url,
            "supabase_anon_key": settings.supabase_anon_key,
            "computer_name": settings.computer_name,
            "default_computer_name": shared_naming.default_computer_name(),
            "sync_areas": settings.sync_areas,
        }

    @app.get("/api/settings/shared-naming", response_model=SharedNamingSettingsResponse)
    def get_shared_naming_settings() -> dict[str, Any]:
        with db.connect() as conn:
            settings = shared_naming.load_settings(conn)
        return settings_response(settings)

    @app.put("/api/settings/shared-naming", response_model=SharedNamingSettingsResponse)
    def put_shared_naming_settings(
        payload: SharedNamingSettingsPayload,
    ) -> dict[str, Any]:
        settings = SharedNamingSettings(
            enabled=payload.enabled,
            supabase_url=payload.supabase_url,
            supabase_anon_key=payload.supabase_anon_key,
            computer_name=payload.computer_name,
            sync_areas=payload.sync_areas,
        )
        with db.connect() as conn:
            shared_naming.save_settings(conn, settings)
            conn.commit()
            settings = shared_naming.load_settings(conn)
        return settings_response(settings)

    @app.post(
        "/api/projects/{project_id}/area-sync/run", response_model=AreaSyncSummary
    )
    def run_area_sync_route(project_id: int) -> dict[str, Any]:
        result = area_sync.run_area_sync(db, storage, project_id)
        overlay = overlay_sync.run_overlay_sync(db, storage, project_id)
        return _merge_overlay_counts(result, overlay)

    @app.post("/api/area-sync/run", response_model=GlobalAreaSyncSummary)
    def run_global_area_sync_route(payload: GlobalAreaSyncRequest) -> dict[str, Any]:
        result = area_sync.run_global_area_sync(db, storage, payload.project_id)
        if payload.project_id:
            overlay = overlay_sync.run_overlay_sync(db, storage, payload.project_id)
            _merge_overlay_counts(result, overlay)
        return result

    @app.get("/api/cloud-panos", response_model=CloudPanosResponse)
    def get_cloud_panos() -> dict[str, Any]:
        """Org-wide list of exported panos (name + projected location) for the
        cloud-data display. Passive: returns {ok:false} rather than erroring
        when Supabase is offline or shared naming is not configured."""
        with db.connect() as conn:
            settings = shared_naming.load_settings(conn)
        if not settings.is_configured():
            return {
                "ok": False,
                "connected": False,
                "panos": [],
                "error": "Supabase URL and anon key are required.",
            }
        try:
            rows = pano_registry.fetch_exported_panos(settings)
        except SharedNamingError as exc:
            return {"ok": False, "connected": False, "panos": [], "error": str(exc)}

        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:4326", FIXED_CRS, always_xy=True)
        own = settings.resolved_computer_name()
        panos: list[dict[str, Any]] = []
        for row in rows:
            # Skip this computer's own exports — they already live in the local
            # Completed list, so the cloud view shows only what other machines
            # shot. computer_name is the discriminator.
            if own and row.get("computer_name") == own:
                continue
            lat, lon = row.get("gps_lat"), row.get("gps_lon")
            projected_x = projected_y = None
            if lat is not None and lon is not None:
                projected_x, projected_y = transformer.transform(lon, lat)
            panos.append(
                {
                    "final_name": row.get("final_name"),
                    "computer_name": row.get("computer_name"),
                    "capture_ts": row.get("capture_ts"),
                    "projected_x": projected_x,
                    "projected_y": projected_y,
                    "is_own": False,
                }
            )
        return {"ok": True, "connected": True, "panos": panos, "error": None}

    @app.post(
        "/api/settings/shared-naming/test", response_model=SharedNamingTestResponse
    )
    def test_shared_naming_connection() -> dict[str, Any]:
        with db.connect() as conn:
            settings = shared_naming.load_settings(conn)
        if not settings.is_configured():
            return {"ok": False, "error": "Supabase URL and anon key are required."}
        try:
            shared_naming.test_connection(settings)
        except SharedNamingError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "error": None}

    @app.get(
        "/api/projects/{project_id}/shared-naming/preview",
        response_model=SharedNamingPreviewResponse,
    )
    def shared_naming_preview(project_id: int) -> dict[str, Any]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            settings = shared_naming.load_settings(conn)
            if not settings.enabled:
                return {"enabled": False, "connected": False, "groups": []}
            rows = conn.execute(
                """
                SELECT photos.*, areas.name AS area_name
                FROM photos
                LEFT JOIN areas ON photos.matched_area_id = areas.id
                WHERE photos.project_id = ? AND photos.applied = 0
                """,
                (project_id,),
            ).fetchall()
            groups = shared_naming.group_keys_for_rows(rows)
            local_next: dict[tuple[str, str], int] = {}
            for capture_date, scoped_area_slug in groups:
                counter = conn.execute(
                    """
                    SELECT next_sequence_number
                    FROM rename_sequence_counters
                    WHERE project_id = ? AND capture_date = ? AND area_slug = ?
                    """,
                    (project_id, capture_date, scoped_area_slug),
                ).fetchone()
                local_next[(capture_date, scoped_area_slug)] = (
                    int(counter["next_sequence_number"]) if counter else 1
                )

        if not settings.is_configured():
            return {
                "enabled": True,
                "connected": False,
                "groups": [],
                "error": "Supabase URL and anon key are required.",
            }

        preview_groups: list[dict[str, Any]] = []
        try:
            for (capture_date, scoped_area_slug), count in sorted(groups.items()):
                date_code = shared_naming.date_code_from_canonical(capture_date)
                shared_max = shared_naming.fetch_max_sequence(
                    settings, date_code, scoped_area_slug
                )
                starts_at = max(shared_max, local_next[(capture_date, scoped_area_slug)] - 1) + 1
                preview_groups.append(
                    {
                        "prefix": f"{date_code}_{scoped_area_slug}",
                        "photos": count,
                        "starts_at": starts_at,
                    }
                )
        except SharedNamingError as exc:
            return {
                "enabled": True,
                "connected": False,
                "groups": [],
                "error": str(exc),
            }
        return {"enabled": True, "connected": True, "groups": preview_groups}

    @app.post(
        "/api/projects/{project_id}/shared-naming/backfill",
        response_model=SharedNamingBackfillResponse,
    )
    def shared_naming_backfill(project_id: int) -> dict[str, Any]:
        with db.connect() as conn:
            fetch_project(conn, project_id)
            settings = shared_naming.load_settings(conn)
            photo_rows = conn.execute(
                "SELECT original_path, proposed_filename, applied FROM photos WHERE project_id = ?",
                (project_id,),
            ).fetchall()

        if not settings.is_configured():
            raise HTTPException(
                status_code=400,
                detail="Supabase URL and anon key are required for shared naming.",
            )

        computer_name = settings.resolved_computer_name()
        stems: set[str] = set()
        for row in photo_rows:
            # A pending photo's proposed_filename is only a plan, not a used
            # name; register it solely once the rename has been applied.
            if row["original_path"]:
                stems.add(Path(row["original_path"]).stem)
            if row["applied"] and row["proposed_filename"]:
                stems.add(Path(row["proposed_filename"]).stem)

        registry_rows = []
        for stem in sorted(stems):
            registry_row = shared_naming.registry_row_for_stem(stem, computer_name)
            if registry_row is not None:
                registry_rows.append(registry_row)

        try:
            added = shared_naming.register_names_ignore_duplicates(
                settings, registry_rows
            )
        except SharedNamingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "scanned": len(photo_rows),
            "matched": len(registry_rows),
            "added": added,
        }
