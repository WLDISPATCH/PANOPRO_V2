"""Smart Mode routes: one-click SD import and register/rename/upload/archive export.

Smart Export is a per-photo state machine on photos.upload_status:
NULL -> 'registered' -> 'uploaded' -> 'archived'. Each run advances every
smart-imported, renamed photo as far as it can and reports failures, so a
partially failed export is simply re-run. Only photos imported by Smart
Import (smart_original_name IS NOT NULL) are ever touched.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from pano_namer.database import Database
from pano_namer.schemas import (
    RenameRunCreate,
    SmartDrivesResponse,
    SmartExportRequest,
    SmartExportResponse,
    SmartFtpTestResponse,
    SmartImportRequest,
    SmartImportResponse,
    SmartSettingsPayload,
    SmartSettingsResponse,
)
from pano_namer.services import ftp_export, pano_registry, sd_card, shared_naming, smart_mode
from pano_namer.services.common import utc_now
from pano_namer.services.shared_naming import SharedNamingError

from .projects import fetch_project

_UNDATED_FOLDER = "undated"


def _dated_folder_name(capture_ts: str | None) -> str:
    if not capture_ts:
        return _UNDATED_FOLDER
    try:
        return datetime.fromisoformat(capture_ts).strftime("%y%m%d")
    except ValueError:
        return _UNDATED_FOLDER


def register_smart_routes(
    app: FastAPI,
    db: Database,
    import_photo_paths: Callable[[int, list[Path]], dict[str, Any]],
    run_rename: Callable[[int, RenameRunCreate], dict[str, Any]],
) -> None:
    def settings_response(settings: smart_mode.SmartModeSettings) -> dict[str, Any]:
        return {
            "ui_mode": settings.ui_mode,
            "import_base_path": settings.import_base_path,
            "archive_base_path": settings.archive_base_path,
            "ftp_host": settings.ftp_host,
            "ftp_port": settings.ftp_port,
            "ftp_username": settings.ftp_username,
            "ftp_password": settings.ftp_password,
            "ftp_remote_path": settings.ftp_remote_path,
            "ftp_protocol": settings.ftp_protocol,
            "ftp_enabled": settings.ftp_enabled,
            "ignore_folders": settings.ignore_folders,
        }

    @app.get("/api/smart/settings", response_model=SmartSettingsResponse)
    def get_smart_settings() -> dict[str, Any]:
        with db.connect() as conn:
            settings = smart_mode.load_settings(conn)
        return settings_response(settings)

    @app.put("/api/smart/settings", response_model=SmartSettingsResponse)
    def put_smart_settings(payload: SmartSettingsPayload) -> dict[str, Any]:
        with db.connect() as conn:
            settings = smart_mode.load_settings(conn)
            for field_name in (
                "ui_mode",
                "import_base_path",
                "archive_base_path",
                "ftp_host",
                "ftp_port",
                "ftp_username",
                "ftp_password",
                "ftp_remote_path",
                "ftp_protocol",
                "ftp_enabled",
                "ignore_folders",
            ):
                value = getattr(payload, field_name)
                if value is not None:
                    setattr(settings, field_name, value)
            if settings.ui_mode not in {
                smart_mode.UI_MODE_ADVANCED,
                smart_mode.UI_MODE_SMART,
            }:
                raise HTTPException(
                    status_code=400, detail="ui_mode must be 'advanced' or 'smart'."
                )
            if settings.ftp_protocol not in smart_mode.UPLOAD_PROTOCOLS:
                raise HTTPException(
                    status_code=400,
                    detail="ftp_protocol must be 'ftp', 'ftps', or 'sftp'.",
                )
            smart_mode.save_settings(conn, settings)
            conn.commit()
            settings = smart_mode.load_settings(conn)
        return settings_response(settings)

    @app.get("/api/smart/drives", response_model=SmartDrivesResponse)
    def list_smart_drives() -> dict[str, Any]:
        return {"drives": [str(root) for root in sd_card.removable_drives_with_dcim()]}

    @app.post("/api/smart/ftp-test", response_model=SmartFtpTestResponse)
    def test_smart_ftp() -> dict[str, Any]:
        with db.connect() as conn:
            settings = smart_mode.load_settings(conn)
        if not settings.ftp_configured():
            return {"ok": False, "error": "FTP host and username are required."}
        try:
            ftp_export.test_connection(settings)
        except ftp_export.FtpExportError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "error": None}

    def _prepare_smart_import(
        payload: SmartImportRequest,
    ) -> tuple[Path, Path, Any, list[str]]:
        """Validate settings/source before any streaming begins (guards must
        surface as proper HTTP errors, which is impossible mid-stream)."""
        with db.connect() as conn:
            fetch_project(conn, payload.project_id)
            settings = smart_mode.load_settings(conn)
            naming_settings = shared_naming.load_settings(conn)
        ignore_folders = settings.ignore_folders

        if not settings.import_base_path:
            raise HTTPException(
                status_code=400,
                detail="Set the Smart Import folder in System settings first.",
            )
        base_path = Path(settings.import_base_path)

        if payload.source_path:
            source_root = Path(payload.source_path)
            if not source_root.is_dir():
                raise HTTPException(
                    status_code=400, detail=f"Folder not found: {source_root}"
                )
        else:
            drives = sd_card.removable_drives_with_dcim()
            if not drives:
                raise HTTPException(
                    status_code=404,
                    detail="No SD card with a DCIM folder was found. Insert the "
                    "card or choose a folder manually.",
                )
            if len(drives) > 1:
                raise HTTPException(
                    status_code=409,
                    detail="Multiple removable drives found: "
                    + ", ".join(str(d) for d in drives)
                    + ". Choose one manually.",
                )
            source_root = drives[0]
        return base_path, source_root, naming_settings, ignore_folders

    def _smart_import_events(
        project_id: int,
        base_path: Path,
        source_root: Path,
        naming_settings,
        ignore_folders: list[str] | None = None,
    ):
        """Run the import, yielding live progress events; last event is
        {"stage": "done", "result": summary} or {"stage": "error", ...}."""
        yield {"stage": "detect", "source_path": str(source_root)}

        scan = None
        for event in sd_card.scan_events(source_root, ignore_folders):
            if event["type"] == "result":
                scan = event["result"]
            else:
                yield {
                    "stage": "scan",
                    "scanned": event["scanned"],
                    "total": event["total"],
                    "panos": event["panos"],
                }

        registry_checked = False
        registry_rows: list[dict[str, Any]] = []
        if naming_settings.is_configured() and scan.panos:
            yield {"stage": "dedupe", "checking": len(scan.panos)}
            try:
                registry_rows = pano_registry.fetch_registry_rows(
                    naming_settings, [pano.original_name for pano in scan.panos]
                )
                registry_checked = True
            except SharedNamingError as exc:
                yield {"stage": "error", "detail": str(exc)}
                return

        duplicates_skipped = 0
        copied = 0
        already_copied = 0
        import_paths: list[Path] = []
        original_names: dict[str, str] = {}
        for index, pano in enumerate(scan.panos, start=1):
            if registry_checked and pano_registry.is_registered_duplicate(
                registry_rows, pano.original_name, pano.gps_lat, pano.gps_lon
            ):
                duplicates_skipped += 1
            else:
                target_dir = base_path / _dated_folder_name(pano.capture_ts)
                target_dir.mkdir(parents=True, exist_ok=True)
                target_path = target_dir / pano.original_name
                if target_path.exists():
                    already_copied += 1
                else:
                    shutil.copy2(pano.path, target_path)
                    copied += 1
                import_paths.append(target_path)
                original_names[str(target_path)] = pano.original_name
            if index % 3 == 0 or index == len(scan.panos):
                yield {
                    "stage": "copy",
                    "processed": index,
                    "total": len(scan.panos),
                    "copied": copied,
                    "duplicates": duplicates_skipped,
                }

        yield {"stage": "stage", "total": len(import_paths)}
        import_result = (
            import_photo_paths(project_id, import_paths)
            if import_paths
            else {"imported": [], "results": [], "summary": {"imported": 0, "duplicates": 0, "errors": 0}}
        )

        imported_photos = import_result["imported"]
        if imported_photos:
            now = utc_now()
            with db.connect() as conn:
                for photo in imported_photos:
                    conn.execute(
                        """
                        UPDATE photos
                        SET is_panorama = 1, smart_original_name = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            original_names.get(photo["original_path"]),
                            now,
                            photo["id"],
                        ),
                    )
                conn.commit()

        yield {
            "stage": "done",
            "result": {
                "source_path": str(source_root),
                "panos_found": len(scan.panos),
                "normal_skipped": scan.skipped_normal,
                "unreadable_skipped": scan.skipped_unreadable,
                "duplicates_skipped": duplicates_skipped,
                "copied": copied,
                "already_copied": already_copied,
                "staged": import_result["summary"]["imported"],
                "registry_checked": registry_checked,
                "import_summary": import_result["summary"],
            },
        }

    @app.post("/api/smart/import", response_model=SmartImportResponse)
    def smart_import(payload: SmartImportRequest) -> dict[str, Any]:
        base_path, source_root, naming_settings, ignore_folders = _prepare_smart_import(
            payload
        )
        final: dict[str, Any] | None = None
        for event in _smart_import_events(
            payload.project_id, base_path, source_root, naming_settings, ignore_folders
        ):
            if event["stage"] == "error":
                raise HTTPException(status_code=503, detail=event["detail"])
            if event["stage"] == "done":
                final = event["result"]
        return final

    @app.post("/api/smart/import/stream")
    def smart_import_stream(payload: SmartImportRequest) -> StreamingResponse:
        base_path, source_root, naming_settings, ignore_folders = _prepare_smart_import(
            payload
        )

        def ndjson():
            try:
                for event in _smart_import_events(
                    payload.project_id,
                    base_path,
                    source_root,
                    naming_settings,
                    ignore_folders,
                ):
                    yield json.dumps(event) + "\n"
            except Exception as exc:  # surfaced as an event; headers already sent
                yield json.dumps({"stage": "error", "detail": str(exc)}) + "\n"

        return StreamingResponse(ndjson(), media_type="application/x-ndjson")

    @app.post("/api/smart/export", response_model=SmartExportResponse)
    def smart_export(payload: SmartExportRequest) -> dict[str, Any]:
        project_id = payload.project_id
        errors: list[str] = []
        with db.connect() as conn:
            fetch_project(conn, project_id)
            settings = smart_mode.load_settings(conn)
            naming_settings = shared_naming.load_settings(conn)

        if not naming_settings.is_configured():
            raise HTTPException(
                status_code=400,
                detail="Supabase must be configured (System settings) so exported "
                "panos can be registered for duplicate detection.",
            )
        upload_enabled = settings.ftp_enabled
        if upload_enabled and not settings.ftp_configured():
            raise HTTPException(
                status_code=400,
                detail="Set the FTP server in System settings, or turn off "
                "server upload to export without it.",
            )
        if not settings.archive_base_path:
            raise HTTPException(
                status_code=400,
                detail="Set the archive folder in System settings before exporting.",
            )

        # Phase 1: rename pending smart-imported photos. "No eligible photos"
        # is fine — the run may be a retry that only needs upload/archive.
        renamed = 0
        try:
            run = run_rename(project_id, RenameRunCreate(photo_ids=None))
            renamed = int(run["summary"].get("renamed", 0)) + int(
                run["summary"].get("unchanged", 0)
            )
        except HTTPException as exc:
            if exc.status_code != 400:
                raise
        except Exception as exc:
            errors.append(f"Rename failed: {exc}")

        # Phase 2: register renamed-but-unregistered photos in Supabase.
        registered = 0
        computer_name = naming_settings.resolved_computer_name()
        with db.connect() as conn:
            to_register = conn.execute(
                """
                SELECT id, smart_original_name, gps_lat, gps_lon, capture_ts,
                       proposed_filename
                FROM photos
                WHERE project_id = ? AND applied = 1
                  AND smart_original_name IS NOT NULL
                  AND upload_status IS NULL
                """,
                (project_id,),
            ).fetchall()
        if to_register:
            rows = [
                pano_registry.registry_row_for_photo(
                    original_name=row["smart_original_name"],
                    gps_lat=row["gps_lat"],
                    gps_lon=row["gps_lon"],
                    capture_ts=row["capture_ts"],
                    final_name=row["proposed_filename"],
                    computer_name=computer_name,
                )
                for row in to_register
            ]
            try:
                pano_registry.register_panos(naming_settings, rows)
                now = utc_now()
                with db.connect() as conn:
                    conn.executemany(
                        "UPDATE photos SET upload_status = 'registered', updated_at = ? WHERE id = ?",
                        [(now, row["id"]) for row in to_register],
                    )
                    conn.commit()
                registered = len(to_register)
            except SharedNamingError as exc:
                errors.append(str(exc))

        # Phase 3: FTP upload (skipped entirely when server upload is off;
        # photos then archive straight from 'registered').
        uploaded = 0
        failed = 0
        to_upload = []
        if upload_enabled:
            with db.connect() as conn:
                to_upload = conn.execute(
                    """
                    SELECT id, original_path, capture_ts
                    FROM photos
                    WHERE project_id = ? AND applied = 1
                      AND smart_original_name IS NOT NULL
                      AND upload_status = 'registered'
                    """,
                    (project_id,),
                ).fetchall()
        if to_upload:
            items = []
            for row in to_upload:
                path = Path(row["original_path"])
                if not path.exists():
                    failed += 1
                    errors.append(f"Missing file, cannot upload: {path.name}")
                    continue
                items.append(
                    ftp_export.UploadItem(
                        photo_id=row["id"],
                        path=path,
                        remote_subdir=f"{_dated_folder_name(row['capture_ts'])}/PANOS",
                    )
                )
            try:
                results = ftp_export.upload_files(settings, items)
            except ftp_export.FtpExportError as exc:
                errors.append(str(exc))
                results = []
            now = utc_now()
            with db.connect() as conn:
                for result in results:
                    if result.status == "uploaded":
                        uploaded += 1
                        conn.execute(
                            "UPDATE photos SET upload_status = 'uploaded', uploaded_at = ?, updated_at = ? WHERE id = ?",
                            (now, now, result.photo_id),
                        )
                    else:
                        failed += 1
                        errors.append(
                            f"Upload failed for {result.filename}: {result.detail}"
                        )
                conn.commit()

        # Phase 4: archive files locally. With upload off, 'registered'
        # photos archive directly and keep that status distinction via
        # uploaded_at staying NULL.
        archived = 0
        archivable_statuses = "('uploaded')" if upload_enabled else "('uploaded', 'registered')"
        archive_base = Path(settings.archive_base_path)
        with db.connect() as conn:
            to_archive = conn.execute(
                f"""
                SELECT id, original_path, capture_ts
                FROM photos
                WHERE project_id = ? AND applied = 1
                  AND smart_original_name IS NOT NULL
                  AND upload_status IN {archivable_statuses}
                """,
                (project_id,),
            ).fetchall()
            now = utc_now()
            for row in to_archive:
                source = Path(row["original_path"])
                if not source.exists():
                    failed += 1
                    errors.append(f"Missing file, cannot archive: {source.name}")
                    continue
                target_dir = (
                    archive_base / _dated_folder_name(row["capture_ts"]) / "PANOS"
                )
                target = target_dir / source.name
                try:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        raise FileExistsError(f"{target} already exists")
                    shutil.move(str(source), str(target))
                except OSError as exc:
                    failed += 1
                    errors.append(f"Archive failed for {source.name}: {exc}")
                    continue
                conn.execute(
                    """
                    UPDATE photos
                    SET original_path = ?, upload_status = 'archived', updated_at = ?
                    WHERE id = ?
                    """,
                    (str(target), now, row["id"]),
                )
                archived += 1
            conn.commit()

        return {
            "renamed": renamed,
            "registered": registered,
            "uploaded": uploaded,
            "archived": archived,
            "failed": failed,
            "errors": errors,
        }
