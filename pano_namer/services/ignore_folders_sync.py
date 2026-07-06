"""Two-way sync of the global Smart Mode ignore-folders list via Supabase.

The ignore list is a single machine-global setting, so it syncs as one row
(``key = 'ignore_folders'``) in a ``shared_smart_settings`` table using the
same Supabase transport as shared naming / area sync. Resolution is
whole-list last-writer-wins on ``updated_at`` -- no per-name tombstones are
needed because the entire list is replaced on each edit.

Supabase table (run once in the SQL editor):

    create table if not exists shared_smart_settings (
        key text primary key,
        value jsonb not null default '[]'::jsonb,
        computer_name text,
        updated_at timestamptz not null default now()
    );
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime
from typing import Any

from pano_namer.services import smart_mode
from pano_namer.services.shared_naming import (
    SharedNamingError,
    SharedNamingSettings,
    SharedNamingUnavailableError,
    _headers,
    _request,
    load_settings,
)

_ROW_KEY = "ignore_folders"


def _parse_ts(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)


def _table_url(settings: SharedNamingSettings, params: dict[str, str] | None = None) -> str:
    base = settings.supabase_url.rstrip("/")
    url = f"{base}/rest/v1/shared_smart_settings"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def fetch_remote(settings: SharedNamingSettings) -> dict[str, Any] | None:
    status, body = _request(
        "GET",
        _table_url(settings, {"key": f"eq.{_ROW_KEY}", "select": "*"}),
        _headers(settings),
        None,
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase smart-settings lookup failed with HTTP {status}."
        )
    rows = json.loads(body or b"[]")
    return rows[0] if rows else None


def push_remote(
    settings: SharedNamingSettings, folders: list[str], updated_at: str
) -> None:
    row = {
        "key": _ROW_KEY,
        "value": folders,
        "computer_name": settings.resolved_computer_name(),
        "updated_at": updated_at,
    }
    status, _body = _request(
        "POST",
        _table_url(settings, {"on_conflict": "key"}),
        _headers(settings, {"Prefer": "resolution=merge-duplicates,return=minimal"}),
        json.dumps([row]).encode("utf-8"),
    )
    if status not in {200, 201, 204}:
        raise SharedNamingUnavailableError(
            f"Supabase smart-settings update failed with HTTP {status}."
        )


def _remote_folders(remote: dict[str, Any]) -> list[str]:
    value = remote.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = []
    if not isinstance(value, list):
        return []
    return smart_mode.parse_ignore_folders("\n".join(str(item) for item in value))


def run_ignore_folders_sync(db) -> dict[str, Any]:
    """Reconcile the local ignore list with the shared Supabase row.

    Whole-list last-writer-wins: the newer ``updated_at`` wins. A machine
    that has never edited its list (no local timestamp) only pulls, so it
    never overwrites the network with an empty default.
    """
    summary: dict[str, Any] = {
        "ok": True,
        "error": None,
        "direction": "none",
        "ignore_folders": [],
    }
    with db.connect() as conn:
        naming = load_settings(conn)
        smart = smart_mode.load_settings(conn)
    summary["ignore_folders"] = smart.ignore_folders

    if not naming.is_configured():
        summary.update(ok=False, error="Supabase is not configured.")
        return summary

    try:
        remote = fetch_remote(naming)
        local_ts = _parse_ts(smart.ignore_folders_updated_at) if smart.ignore_folders_updated_at else None
        remote_ts = _parse_ts(remote["updated_at"]) if remote else None

        # Pull when the remote is strictly newer (or we have no local edit yet).
        if remote is not None and (local_ts is None or (remote_ts and remote_ts > local_ts)):
            folders = _remote_folders(remote)
            with db.connect() as conn:
                fresh = smart_mode.load_settings(conn)
                fresh.ignore_folders = folders
                fresh.ignore_folders_updated_at = str(remote["updated_at"])
                smart_mode.save_settings(conn, fresh)
                conn.commit()
            summary.update(direction="pulled", ignore_folders=folders)
            return summary

        # Push when we have a local edit that is newer than (or absent from) remote.
        if smart.ignore_folders_updated_at and (remote is None or (remote_ts and local_ts and local_ts > remote_ts)):
            push_remote(naming, smart.ignore_folders, smart.ignore_folders_updated_at)
            summary.update(direction="pushed")
            return summary
    except SharedNamingUnavailableError as exc:
        summary.update(ok=False, error=str(exc))
    except SharedNamingError as exc:
        summary.update(ok=False, error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        summary.update(ok=False, error=f"Ignore-folder sync failed: {exc}")
    return summary
