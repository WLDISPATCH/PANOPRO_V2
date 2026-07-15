"""Two-way sync of project map overlays via Supabase.

Mirrors area_sync: overlays for a template are shared through a
``shared_overlays`` table plus an ``overlay-files`` storage bucket, with
last-writer-wins on ``updated_at`` and tombstones for deletes. Only the
rendered overlay image + its bounds/size metadata are synced; each machine
rebuilds its own tile pyramid locally (issue #20). Rides the same trigger and
config as area sync (Shared Pano Naming's ``sync_areas``).

Supabase table (run once in the SQL editor -- see
docs/supabase_shared_overlays.sql):

    create table if not exists shared_overlays (
        uid text primary key, template_name text not null, display_name text,
        bounds_json text, width int, height int, crs text, file_ext text,
        file_hash text, file_path text, computer_name text,
        updated_at timestamptz, deleted_at timestamptz
    );
"""

from __future__ import annotations

import json
import urllib.parse
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from pano_namer.config import FIXED_CRS
from pano_namer.services import overlay_tiles
from pano_namer.services.area_sync import _parse_ts, file_sha256, template_slug
from pano_namer.services.common import utc_now
from pano_namer.services.shared_naming import (
    SharedNamingError,
    SharedNamingSettings,
    SharedNamingUnavailableError,
    _headers,
    _request,
    load_settings,
)

OVERLAY_BUCKET = "overlay-files"


# ---- Supabase REST/storage helpers (same transport as shared_naming) ----

def _table_url(settings: SharedNamingSettings, params: dict[str, str] | None = None) -> str:
    base = settings.supabase_url.rstrip("/")
    url = f"{base}/rest/v1/shared_overlays"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def _storage_url(settings: SharedNamingSettings, storage_path: str) -> str:
    base = settings.supabase_url.rstrip("/")
    return f"{base}/storage/v1/object/{OVERLAY_BUCKET}/{urllib.parse.quote(storage_path)}"


def fetch_remote_overlays(settings: SharedNamingSettings, template_name: str) -> list[dict[str, Any]]:
    status, body = _request(
        "GET",
        _table_url(settings, {"template_name": f"eq.{template_name}", "select": "*"}),
        _headers(settings),
        None,
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase overlay registry lookup failed with HTTP {status}."
        )
    return json.loads(body or b"[]")


def upsert_remote_overlay(settings: SharedNamingSettings, row: dict[str, Any]) -> None:
    status, _body = _request(
        "POST",
        _table_url(settings, {"on_conflict": "uid"}),
        _headers(settings, {"Prefer": "resolution=merge-duplicates,return=minimal"}),
        json.dumps([row]).encode("utf-8"),
    )
    if status not in {200, 201, 204}:
        raise SharedNamingUnavailableError(
            f"Supabase overlay registry update failed with HTTP {status}."
        )


def upload_overlay_file(settings: SharedNamingSettings, storage_path: str, data: bytes) -> None:
    status, _body = _request(
        "POST",
        _storage_url(settings, storage_path),
        _headers(settings, {"x-upsert": "true", "Content-Type": "application/octet-stream"}),
        data,
    )
    if status not in {200, 201}:
        raise SharedNamingUnavailableError(
            f"Supabase overlay file upload failed with HTTP {status}."
        )


def download_overlay_file(settings: SharedNamingSettings, storage_path: str) -> bytes:
    status, body = _request(
        "GET", _storage_url(settings, storage_path), _headers(settings), None
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase overlay file download failed with HTTP {status}."
        )
    return body


# ---- Sync core ----

def _overlays_dir(storage, project_id: int) -> Path:
    path = storage.project_dir(project_id) / "overlays"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _local_file_hash(row) -> str | None:
    managed = row["jpg_managed_path"]
    if not managed:
        return None
    path = Path(managed)
    if not path.exists():
        return None
    return file_sha256(path)


def _push_overlay(conn, settings, template_name, row, uid, *, deleted_at=None) -> None:
    registry_row: dict[str, Any] = {
        "uid": uid,
        "template_name": template_name,
        "display_name": row["display_name"] or "",
        "bounds_json": row["bounds_json"] or "",
        "width": row["width"],
        "height": row["height"],
        "crs": row["crs"] or FIXED_CRS,
        "computer_name": settings.resolved_computer_name(),
        "updated_at": row["updated_at"],
        "deleted_at": deleted_at,
    }
    if deleted_at is None:
        managed = Path(row["jpg_managed_path"])
        data = managed.read_bytes()
        ext = managed.suffix.lower() or ".png"
        storage_path = f"{template_slug(template_name)}/{uid}{ext}"
        upload_overlay_file(settings, storage_path, data)
        registry_row.update(
            {"file_ext": ext, "file_hash": sha256(data).hexdigest(), "file_path": storage_path}
        )
    else:
        ext = Path(row["jpg_managed_path"] or "x.png").suffix.lower() or ".png"
        registry_row.update(
            {"file_ext": ext, "file_hash": "", "file_path": f"{template_slug(template_name)}/{uid}"}
        )
    upsert_remote_overlay(settings, registry_row)
    if not row["sync_uid"]:
        conn.execute("UPDATE overlays SET sync_uid = ? WHERE id = ?", (uid, row["id"]))


def _pull_file(settings, storage, project_id, remote) -> Path:
    data = download_overlay_file(settings, remote["file_path"])
    ext = remote.get("file_ext") or ".png"
    path = _overlays_dir(storage, project_id) / f"sync_{remote['uid']}_{uuid4().hex[:8]}{ext}"
    path.write_bytes(data)
    return path


def _build_tiles(conn, data_dir: Path, overlay_id: int) -> None:
    row = conn.execute("SELECT * FROM overlays WHERE id = ?", (overlay_id,)).fetchone()
    try:
        overlay_tiles.build_tiles_for_overlay_row(conn, data_dir, row)
    except Exception:  # pragma: no cover - tiling is best-effort, image fallback remains
        pass


def _pull_create(conn, settings, storage, data_dir, project_id, remote) -> None:
    path = _pull_file(settings, storage, project_id, remote)
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO overlays (
            project_id, display_name, jpg_original_path, jpg_managed_path, crs,
            bounds_json, width, height, active, sync_uid, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            project_id,
            remote.get("display_name") or "Project Overlay",
            str(path),
            str(path),
            remote.get("crs") or FIXED_CRS,
            remote.get("bounds_json") or None,
            remote.get("width"),
            remote.get("height"),
            remote["uid"],
            now,
            remote["updated_at"],
        ),
    )
    _build_tiles(conn, data_dir, cursor.lastrowid)


def _pull_update(conn, settings, storage, data_dir, project_id, remote, local, *, file_changed) -> None:
    if file_changed:
        path = _pull_file(settings, storage, project_id, remote)
        conn.execute(
            """
            UPDATE overlays
            SET display_name = ?, jpg_original_path = ?, jpg_managed_path = ?, crs = ?,
                bounds_json = ?, width = ?, height = ?, active = 1, sync_uid = ?,
                pmtiles_path = NULL, updated_at = ?
            WHERE id = ?
            """,
            (
                remote.get("display_name") or local["display_name"],
                str(path),
                str(path),
                remote.get("crs") or FIXED_CRS,
                remote.get("bounds_json") or None,
                remote.get("width"),
                remote.get("height"),
                remote["uid"],
                remote["updated_at"],
                local["id"],
            ),
        )
        _build_tiles(conn, data_dir, local["id"])
    else:
        conn.execute(
            "UPDATE overlays SET display_name = ?, active = 1, sync_uid = ?, updated_at = ? WHERE id = ?",
            (
                remote.get("display_name") or local["display_name"],
                remote["uid"],
                remote["updated_at"],
                local["id"],
            ),
        )


def run_overlay_sync(db, storage, project_id: int) -> dict[str, Any]:
    """Two-way overlay sync against the shared Supabase registry.

    Last-writer-wins on updated_at; pulls download the image and rebuild tiles
    locally. Gated on the same Shared Pano Naming config as area sync.
    """
    summary: dict[str, Any] = {
        "ok": True,
        "error": None,
        "pulled_new": 0,
        "pulled_updated": 0,
        "pushed_new": 0,
        "pushed_updated": 0,
        "deactivated": 0,
        "tombstoned": 0,
        "skipped": 0,
    }
    data_dir = storage.config.data_dir
    with db.connect() as conn:
        settings = load_settings(conn)
        if not settings.sync_areas or not settings.is_configured():
            summary.update(ok=False, error="Overlay sync is not enabled or configured.")
            return summary
        project = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            summary.update(ok=False, error="Project not found.")
            return summary
        template_name = project["name"]

        try:
            remote_rows = fetch_remote_overlays(settings, template_name)
            local_rows = conn.execute(
                "SELECT * FROM overlays WHERE project_id = ?", (project_id,)
            ).fetchall()
            local_by_uid = {row["sync_uid"]: row for row in local_rows if row["sync_uid"]}
            matched_uids: set[str] = set()

            for remote in remote_rows:
                uid = remote["uid"]
                matched_uids.add(uid)
                local = local_by_uid.get(uid)
                remote_ts = _parse_ts(remote.get("updated_at"))
                local_ts = _parse_ts(local["updated_at"]) if local is not None else None

                if remote.get("deleted_at"):
                    deleted_ts = _parse_ts(remote["deleted_at"])
                    if local is not None and local["active"]:
                        if local_ts and local_ts > deleted_ts:
                            _push_overlay(conn, settings, template_name, local, uid)
                            summary["pushed_updated"] += 1
                        else:
                            conn.execute(
                                "UPDATE overlays SET active = 0, updated_at = ? WHERE id = ?",
                                (remote["deleted_at"], local["id"]),
                            )
                            summary["deactivated"] += 1
                    continue

                if local is None:
                    _pull_create(conn, settings, storage, data_dir, project_id, remote)
                    summary["pulled_new"] += 1
                    continue

                if not local["active"]:
                    if local_ts and local_ts > remote_ts:
                        _push_overlay(
                            conn, settings, template_name, local, uid,
                            deleted_at=local["updated_at"],
                        )
                        summary["tombstoned"] += 1
                    else:
                        _pull_update(
                            conn, settings, storage, data_dir, project_id, remote, local,
                            file_changed=True,
                        )
                        summary["pulled_updated"] += 1
                    continue

                local_hash = _local_file_hash(local)
                file_changed = local_hash != remote.get("file_hash")
                meta_changed = (local["display_name"] or "") != (remote.get("display_name") or "")
                if not file_changed and not meta_changed:
                    continue
                if local_ts and local_ts > remote_ts:
                    _push_overlay(conn, settings, template_name, local, uid)
                    summary["pushed_updated"] += 1
                else:
                    _pull_update(
                        conn, settings, storage, data_dir, project_id, remote, local,
                        file_changed=file_changed,
                    )
                    summary["pulled_updated"] += 1

            for row in local_rows:
                uid = row["sync_uid"]
                if uid and uid in matched_uids:
                    continue
                if not row["active"]:
                    continue
                if not row["jpg_managed_path"] or not Path(row["jpg_managed_path"]).exists():
                    summary["skipped"] += 1
                    continue
                fresh = conn.execute(
                    "SELECT * FROM overlays WHERE id = ?", (row["id"],)
                ).fetchone()
                _push_overlay(conn, settings, template_name, fresh, uid or uuid4().hex)
                summary["pushed_new"] += 1

            conn.commit()
        except SharedNamingUnavailableError as exc:
            conn.rollback()
            summary.update(
                ok=False,
                error=(
                    f"Supabase is unreachable ({exc}). "
                    "Overlays will sync on the next successful run."
                ),
            )
        except SharedNamingError as exc:
            conn.rollback()
            summary.update(ok=False, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            conn.rollback()
            summary.update(ok=False, error=f"Overlay sync failed: {exc}")
    return summary
