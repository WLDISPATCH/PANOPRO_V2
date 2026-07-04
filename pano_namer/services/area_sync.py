from __future__ import annotations

import json
import sqlite3
import urllib.parse
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from pano_namer.area_colors import next_available_area_color, normalize_area_color
from pano_namer.config import FIXED_CRS
from pano_namer.services.common import dumps_json, slugify_filename_stem, utc_now
from pano_namer.services.dxf import extract_area_geometry_wkt
from pano_namer.services.shared_naming import (
    SharedNamingError,
    SharedNamingSettings,
    SharedNamingUnavailableError,
    _headers,
    _request,
    load_settings,
)

AREA_BUCKET = "area-files"


def _parse_ts(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def template_slug(template_name: str) -> str:
    return slugify_filename_stem(template_name).lower()


# ---- Supabase REST helpers (same transport as shared_naming) ----

def _table_url(settings: SharedNamingSettings, params: dict[str, str] | None = None) -> str:
    base = settings.supabase_url.rstrip("/")
    url = f"{base}/rest/v1/shared_areas"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def _storage_url(settings: SharedNamingSettings, storage_path: str) -> str:
    base = settings.supabase_url.rstrip("/")
    return f"{base}/storage/v1/object/{AREA_BUCKET}/{urllib.parse.quote(storage_path)}"


def fetch_remote_areas(settings: SharedNamingSettings, template_name: str) -> list[dict[str, Any]]:
    status, body = _request(
        "GET",
        _table_url(settings, {"template_name": f"eq.{template_name}", "select": "*"}),
        _headers(settings),
        None,
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase area registry lookup failed with HTTP {status}."
        )
    return json.loads(body or b"[]")


def upsert_remote_area(settings: SharedNamingSettings, row: dict[str, Any]) -> None:
    status, _body = _request(
        "POST",
        _table_url(settings, {"on_conflict": "uid"}),
        _headers(settings, {"Prefer": "resolution=merge-duplicates,return=minimal"}),
        json.dumps([row]).encode("utf-8"),
    )
    if status not in {200, 201, 204}:
        raise SharedNamingUnavailableError(
            f"Supabase area registry update failed with HTTP {status}."
        )


def upload_area_file(settings: SharedNamingSettings, storage_path: str, data: bytes) -> None:
    status, _body = _request(
        "POST",
        _storage_url(settings, storage_path),
        _headers(settings, {"x-upsert": "true", "Content-Type": "application/octet-stream"}),
        data,
    )
    if status not in {200, 201}:
        raise SharedNamingUnavailableError(
            f"Supabase area file upload failed with HTTP {status}."
        )


def download_area_file(settings: SharedNamingSettings, storage_path: str) -> bytes:
    status, body = _request(
        "GET", _storage_url(settings, storage_path), _headers(settings), None
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase area file download failed with HTTP {status}."
        )
    return body


# ---- Drawn-area KML export ----

def kml_for_polygon_wkt(footprint_wkt: str) -> bytes:
    """Export a projected polygon as WGS84 KML so drawn areas sync as files."""
    from pyproj import Transformer
    from shapely import wkt as shapely_wkt

    geometry = shapely_wkt.loads(footprint_wkt)
    if geometry.is_empty:
        raise ValueError("Area has no geometry to export.")
    polygons = (
        [geometry]
        if geometry.geom_type == "Polygon"
        else [part for part in getattr(geometry, "geoms", []) if not part.is_empty]
    )
    if not polygons:
        raise ValueError("Area has no polygon geometry to export.")
    transformer = Transformer.from_crs(FIXED_CRS, "EPSG:4326", always_xy=True)
    placemarks = []
    for polygon in polygons:
        coords = []
        for x, y in polygon.exterior.coords:
            lon, lat = transformer.transform(x, y)
            coords.append(f"{lon:.8f},{lat:.8f},0")
        placemarks.append(
            "<Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>"
            + " ".join(coords)
            + "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
        )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        + "".join(placemarks)
        + "</Document></kml>"
    )
    return document.encode("utf-8")


# ---- Sync core ----

def _areas_dir(storage, project_id: int) -> Path:
    path = storage.project_dir(project_id) / "areas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _local_file_hash(row: sqlite3.Row) -> str | None:
    managed = row["dxf_managed_path"]
    if not managed:
        return None
    path = Path(managed)
    if not path.exists():
        return None
    return file_sha256(path)


def _ensure_drawn_areas_file_backed(conn: sqlite3.Connection, storage, project_id: int) -> int:
    """Give drawn areas (geometry, no file) a KML file so they sync like imports."""
    skipped = 0
    rows = conn.execute(
        """
        SELECT * FROM areas
        WHERE project_id = ? AND active = 1
          AND (dxf_managed_path IS NULL OR dxf_managed_path = '')
          AND footprint_wkt != 'POLYGON EMPTY'
        """,
        (project_id,),
    ).fetchall()
    for row in rows:
        try:
            data = kml_for_polygon_wkt(row["footprint_wkt"])
        except Exception:
            skipped += 1
            continue
        path = _areas_dir(storage, project_id) / f"drawn_{uuid4().hex}.kml"
        path.write_bytes(data)
        conn.execute(
            "UPDATE areas SET dxf_original_path = ?, dxf_managed_path = ? WHERE id = ?",
            (str(path), str(path), row["id"]),
        )
    return skipped


def _push_area(
    conn: sqlite3.Connection,
    settings: SharedNamingSettings,
    template_name: str,
    row: sqlite3.Row | dict[str, Any],
    uid: str,
    *,
    deleted_at: str | None = None,
) -> None:
    registry_row: dict[str, Any] = {
        "uid": uid,
        "template_name": template_name,
        "name": row["name"],
        "display_color": row["display_color"],
        "computer_name": settings.resolved_computer_name(),
        "updated_at": row["updated_at"],
        "deleted_at": deleted_at,
    }
    if deleted_at is None:
        managed = Path(row["dxf_managed_path"])
        data = managed.read_bytes()
        ext = managed.suffix.lower() or ".kml"
        storage_path = f"{template_slug(template_name)}/{uid}{ext}"
        upload_area_file(settings, storage_path, data)
        registry_row.update(
            {
                "file_ext": ext,
                "file_hash": sha256(data).hexdigest(),
                "file_path": storage_path,
            }
        )
    else:
        registry_row.update(
            {
                "file_ext": Path(row["dxf_managed_path"] or "x.kml").suffix.lower() or ".kml",
                "file_hash": "",
                "file_path": f"{template_slug(template_name)}/{uid}",
            }
        )
    upsert_remote_area(settings, registry_row)
    if not row["sync_uid"]:
        conn.execute("UPDATE areas SET sync_uid = ? WHERE id = ?", (uid, row["id"]))


def _pull_file(settings: SharedNamingSettings, storage, project_id: int, remote: dict[str, Any]) -> Path:
    data = download_area_file(settings, remote["file_path"])
    ext = remote.get("file_ext") or ".kml"
    path = _areas_dir(storage, project_id) / f"sync_{remote['uid']}_{uuid4().hex[:8]}{ext}"
    path.write_bytes(data)
    return path


def _pull_create(
    conn: sqlite3.Connection,
    settings: SharedNamingSettings,
    storage,
    project_id: int,
    remote: dict[str, Any],
) -> None:
    path = _pull_file(settings, storage, project_id, remote)
    footprint_wkt, bbox = extract_area_geometry_wkt(path)
    color = normalize_area_color(remote.get("display_color"))
    if color is None:
        existing = [
            r["display_color"]
            for r in conn.execute(
                "SELECT display_color FROM areas WHERE project_id = ? AND active = 1",
                (project_id,),
            ).fetchall()
            if r["display_color"]
        ]
        color = next_available_area_color(existing)
    conn.execute(
        """
        INSERT INTO areas (
            project_id, name, dxf_original_path, dxf_managed_path, display_color, source_crs,
            footprint_wkt, footprint_bbox_json, active, sync_uid, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            project_id,
            remote["name"],
            str(path),
            str(path),
            color,
            FIXED_CRS,
            footprint_wkt,
            dumps_json(bbox),
            remote["uid"],
            utc_now(),
            remote["updated_at"],
        ),
    )


def _pull_update(
    conn: sqlite3.Connection,
    settings: SharedNamingSettings,
    storage,
    project_id: int,
    remote: dict[str, Any],
    local: sqlite3.Row,
    *,
    file_changed: bool,
) -> None:
    if file_changed:
        path = _pull_file(settings, storage, project_id, remote)
        footprint_wkt, bbox = extract_area_geometry_wkt(path)
        conn.execute(
            """
            UPDATE areas
            SET name = ?, display_color = ?, dxf_original_path = ?, dxf_managed_path = ?,
                source_crs = ?, footprint_wkt = ?, footprint_bbox_json = ?,
                active = 1, sync_uid = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                remote["name"],
                normalize_area_color(remote.get("display_color")) or local["display_color"],
                str(path),
                str(path),
                FIXED_CRS,
                footprint_wkt,
                dumps_json(bbox),
                remote["uid"],
                remote["updated_at"],
                local["id"],
            ),
        )
    else:
        conn.execute(
            "UPDATE areas SET name = ?, display_color = ?, active = 1, sync_uid = ?, updated_at = ? WHERE id = ?",
            (
                remote["name"],
                normalize_area_color(remote.get("display_color")) or local["display_color"],
                remote["uid"],
                remote["updated_at"],
                local["id"],
            ),
        )


def run_area_sync(db, storage, project_id: int) -> dict[str, Any]:
    """Two-way area sync against the shared Supabase registry.

    Last-writer-wins on updated_at; pulls set the local updated_at to the
    remote value (and pushes publish the local value) so repeated runs
    converge instead of ping-ponging.
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
    with db.connect() as conn:
        settings = load_settings(conn)
        if not settings.sync_areas or not settings.is_configured():
            summary.update(ok=False, error="Area sync is not enabled or configured.")
            return summary
        project = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            summary.update(ok=False, error="Project not found.")
            return summary
        template_name = project["name"]

        try:
            summary["skipped"] += _ensure_drawn_areas_file_backed(conn, storage, project_id)
            remote_rows = fetch_remote_areas(settings, template_name)

            local_rows = conn.execute(
                "SELECT * FROM areas WHERE project_id = ?", (project_id,)
            ).fetchall()
            local_by_uid = {row["sync_uid"]: row for row in local_rows if row["sync_uid"]}
            active_by_name = {row["name"]: row for row in local_rows if row["active"]}
            matched_uids: set[str] = set()
            geometry_changed = False

            for remote in remote_rows:
                uid = remote["uid"]
                matched_uids.add(uid)
                local = local_by_uid.get(uid)
                if local is None:
                    candidate = active_by_name.get(remote["name"])
                    if candidate is not None and not candidate["sync_uid"]:
                        conn.execute(
                            "UPDATE areas SET sync_uid = ? WHERE id = ?",
                            (uid, candidate["id"]),
                        )
                        local = conn.execute(
                            "SELECT * FROM areas WHERE id = ?", (candidate["id"],)
                        ).fetchone()

                remote_ts = _parse_ts(remote.get("updated_at"))
                local_ts = _parse_ts(local["updated_at"]) if local is not None else None

                if remote.get("deleted_at"):
                    deleted_ts = _parse_ts(remote["deleted_at"])
                    if local is not None and local["active"]:
                        if local_ts and local_ts > deleted_ts:
                            _push_area(conn, settings, template_name, local, uid)
                            summary["pushed_updated"] += 1
                        else:
                            conn.execute(
                                "UPDATE areas SET active = 0, updated_at = ? WHERE id = ?",
                                (remote["deleted_at"], local["id"]),
                            )
                            summary["deactivated"] += 1
                            geometry_changed = True
                    continue

                if local is None:
                    _pull_create(conn, settings, storage, project_id, remote)
                    summary["pulled_new"] += 1
                    geometry_changed = True
                    continue

                if not local["active"]:
                    if local_ts and local_ts > remote_ts:
                        _push_area(
                            conn, settings, template_name, local, uid,
                            deleted_at=local["updated_at"],
                        )
                        summary["tombstoned"] += 1
                    else:
                        _pull_update(
                            conn, settings, storage, project_id, remote, local,
                            file_changed=True,
                        )
                        summary["pulled_updated"] += 1
                        geometry_changed = True
                    continue

                local_hash = _local_file_hash(local)
                file_changed = local_hash != remote.get("file_hash")
                meta_changed = (
                    local["name"] != remote["name"]
                    or (local["display_color"] or "") != (remote.get("display_color") or "")
                )
                if not file_changed and not meta_changed:
                    continue
                if local_ts and local_ts > remote_ts:
                    _push_area(conn, settings, template_name, local, uid)
                    summary["pushed_updated"] += 1
                else:
                    _pull_update(
                        conn, settings, storage, project_id, remote, local,
                        file_changed=file_changed,
                    )
                    summary["pulled_updated"] += 1
                    if file_changed:
                        geometry_changed = True

            for row in local_rows:
                uid = row["sync_uid"]
                if uid and uid in matched_uids:
                    continue
                if not row["active"]:
                    continue
                if not row["dxf_managed_path"] or row["footprint_wkt"] == "POLYGON EMPTY":
                    summary["skipped"] += 1
                    continue
                fresh = conn.execute(
                    "SELECT * FROM areas WHERE id = ?", (row["id"],)
                ).fetchone()
                _push_area(conn, settings, template_name, fresh, uid or uuid4().hex)
                summary["pushed_new"] += 1

            if geometry_changed:
                refresh_pending_photo_matches(conn, project_id)
            conn.commit()
        except SharedNamingUnavailableError as exc:
            conn.rollback()
            summary.update(
                ok=False,
                error=(
                    f"Supabase is unreachable ({exc}). "
                    "Areas will sync on the next successful run."
                ),
            )
        except SharedNamingError as exc:
            conn.rollback()
            summary.update(ok=False, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            conn.rollback()
            summary.update(ok=False, error=f"Area sync failed: {exc}")
    return summary


def refresh_pending_photo_matches(conn: sqlite3.Connection, project_id: int) -> None:
    from pano_namer.api.routes.areas import (
        refresh_pending_photo_matches as _refresh,
    )

    _refresh(conn, project_id)


# ---- Global sync: bootstrap every template found on the network ----


def fetch_remote_template_names(settings: SharedNamingSettings) -> list[str]:
    """Distinct template names on the network, skipping fully-deleted templates."""
    status, body = _request(
        "GET",
        _table_url(settings, {"select": "template_name,deleted_at"}),
        _headers(settings),
        None,
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase area registry lookup failed with HTTP {status}."
        )
    rows = json.loads(body or b"[]")
    live_by_key: dict[str, str] = {}
    for row in rows:
        name = (row.get("template_name") or "").strip()
        if not name or row.get("deleted_at"):
            continue
        live_by_key.setdefault(name.lower(), name)
    return sorted(live_by_key.values(), key=str.lower)


def _ensure_project(conn: sqlite3.Connection, storage, template_name: str) -> tuple[int, bool]:
    """Find a project by name (case-insensitive) or create it like POST /api/projects."""
    row = conn.execute(
        "SELECT id FROM projects WHERE name = ? COLLATE NOCASE",
        (template_name,),
    ).fetchone()
    if row is not None:
        return int(row["id"]), False
    now = utc_now()
    storage_root = str(storage.config.storage_dir / "projects")
    cursor = conn.execute(
        "INSERT INTO projects (name, storage_root, crs, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (template_name.strip(), storage_root, FIXED_CRS, now, now),
    )
    project_id = cursor.lastrowid
    conn.commit()
    storage.project_dir(project_id)
    return int(project_id), True


_SYNC_COUNTER_KEYS = (
    "pulled_new",
    "pulled_updated",
    "pushed_new",
    "pushed_updated",
    "deactivated",
    "tombstoned",
    "skipped",
)


def run_global_area_sync(db, storage, selected_project_id: int | None = None) -> dict[str, Any]:
    """Sync every template known to the network, creating missing ones locally.

    Remote-known templates get a full two-way sync. The currently selected
    project is also synced (publishing it to the network) when its name is not
    on the network yet; other local-only templates are never pushed implicitly.
    """
    summary: dict[str, Any] = {
        "ok": True,
        "error": None,
        "templates_created": 0,
        "created_names": [],
        "templates_synced": 0,
        "errors": [],
    }
    summary.update({key: 0 for key in _SYNC_COUNTER_KEYS})

    with db.connect() as conn:
        settings = load_settings(conn)
        if not settings.sync_areas or not settings.is_configured():
            summary.update(ok=False, error="Area sync is not enabled or configured.")
            return summary
        try:
            remote_names = fetch_remote_template_names(settings)
        except SharedNamingUnavailableError as exc:
            summary.update(ok=False, error=str(exc))
            return summary

        project_ids: list[int] = []
        remote_keys = {name.lower() for name in remote_names}
        for template_name in remote_names:
            try:
                project_id, created = _ensure_project(conn, storage, template_name)
            except Exception as exc:  # pragma: no cover - defensive
                summary["errors"].append(
                    f"Could not create template '{template_name}': {exc}"
                )
                continue
            if created:
                summary["templates_created"] += 1
                summary["created_names"].append(template_name)
            project_ids.append(project_id)

        if selected_project_id is not None:
            selected = conn.execute(
                "SELECT id, name FROM projects WHERE id = ?", (selected_project_id,)
            ).fetchone()
            if selected is not None and selected["name"].lower() not in remote_keys:
                project_ids.append(int(selected["id"]))

    for project_id in project_ids:
        result = run_area_sync(db, storage, project_id)
        summary["templates_synced"] += 1
        for key in _SYNC_COUNTER_KEYS:
            summary[key] += int(result.get(key, 0))
        if not result.get("ok") and result.get("error"):
            summary["errors"].append(str(result["error"]))

    return summary
