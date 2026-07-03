from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pano_namer.services.common import utc_now
from pano_namer.services.rename import RenamePlanItem
from pano_namer.services.reservations import (
    _eligible,
    area_slug,
    canonical_capture_date,
)

OFFLINE_MESSAGE = (
    "Cannot create shared pano names while offline. "
    "Reconnect to Supabase or disable Shared Pano Naming for this export."
)

REQUEST_TIMEOUT_SECONDS = 10.0

# Matches a pano name stem such as 260702_OPTA_045. The area part may itself
# contain underscores; the trailing digit run is always the sequence number.
EXISTING_NAME_RE = re.compile(r"^(\d{6})_(.+)_(\d+)$")

_SETTING_ENABLED = "shared_naming.enabled"
_SETTING_URL = "shared_naming.supabase_url"
_SETTING_ANON_KEY = "shared_naming.supabase_anon_key"
_SETTING_COMPUTER_NAME = "shared_naming.computer_name"
_SETTING_SYNC_AREAS = "shared_naming.sync_areas"


class SharedNamingError(Exception):
    """Base error for shared pano naming operations."""


class SharedNamingUnavailableError(SharedNamingError):
    """Supabase could not be reached or returned an unexpected response."""


class SharedNamingConflictError(SharedNamingError):
    """At least one requested pano name already exists in the shared registry."""


@dataclass(slots=True)
class SharedNamingSettings:
    enabled: bool = False
    supabase_url: str = ""
    supabase_anon_key: str = ""
    computer_name: str = ""
    sync_areas: bool = False

    def is_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    def resolved_computer_name(self) -> str:
        return self.computer_name or default_computer_name()


def default_computer_name() -> str:
    return os.environ.get("COMPUTERNAME") or socket.gethostname() or ""


def load_settings(conn: sqlite3.Connection) -> SharedNamingSettings:
    rows = conn.execute(
        "SELECT key, value FROM app_settings WHERE key LIKE 'shared_naming.%'"
    ).fetchall()
    values = {row["key"]: row["value"] or "" for row in rows}
    return SharedNamingSettings(
        enabled=values.get(_SETTING_ENABLED, "").strip().lower() == "true",
        supabase_url=values.get(_SETTING_URL, "").strip(),
        supabase_anon_key=values.get(_SETTING_ANON_KEY, "").strip(),
        computer_name=values.get(_SETTING_COMPUTER_NAME, "").strip(),
        sync_areas=values.get(_SETTING_SYNC_AREAS, "").strip().lower() == "true",
    )


def save_settings(conn: sqlite3.Connection, settings: SharedNamingSettings) -> None:
    now = utc_now()
    values = {
        _SETTING_ENABLED: "true" if settings.enabled else "false",
        _SETTING_URL: settings.supabase_url.strip(),
        _SETTING_ANON_KEY: settings.supabase_anon_key.strip(),
        _SETTING_COMPUTER_NAME: settings.computer_name.strip(),
        _SETTING_SYNC_AREAS: "true" if settings.sync_areas else "false",
    }
    for key, value in values.items():
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )


def date_code_from_canonical(capture_date: str) -> str:
    """Convert the allocator's YYYY-MM-DD scope date to the YYMMDD name stamp."""
    return datetime.fromisoformat(capture_date).strftime("%y%m%d")


def group_keys_for_rows(
    photo_rows: list[sqlite3.Row | dict[str, Any]],
) -> dict[tuple[str, str], int]:
    """Group eligible pending rows by the allocator's (capture_date, area_slug) key.

    Returns each group's eligible photo count so callers can also build previews.
    """
    groups: dict[tuple[str, str], int] = {}
    for row in photo_rows:
        if not _eligible(row):
            continue
        capture_ts = (
            row["capture_ts"] if isinstance(row, sqlite3.Row) else row.get("capture_ts")
        )
        area_name = (
            row["area_name"] if isinstance(row, sqlite3.Row) else row.get("area_name")
        )
        key = (canonical_capture_date(capture_ts), area_slug(area_name))
        groups[key] = groups.get(key, 0) + 1
    return groups


def registry_rows_for_plans(
    plans: list[RenamePlanItem], computer_name: str
) -> list[dict[str, Any]]:
    """Build used_pano_names rows from reservation plans.

    Names are registered as stems without extension (260702_OPTA_001), parsed
    back from the reserved filename so the registry always matches local files.
    """
    rows: list[dict[str, Any]] = []
    for plan in plans:
        stem = Path(plan.final_name).stem
        match = EXISTING_NAME_RE.match(stem)
        if match is None:
            continue
        rows.append(
            {
                "name": stem,
                "date_code": match.group(1),
                "area_code": match.group(2),
                "sequence_number": int(match.group(3)),
                "computer_name": computer_name,
            }
        )
    return rows


def registry_row_for_stem(stem: str, computer_name: str) -> dict[str, Any] | None:
    """Parse an existing filename stem into a registry row, or None if unrecognized."""
    match = EXISTING_NAME_RE.match(stem)
    if match is None:
        return None
    return {
        "name": stem,
        "date_code": match.group(1),
        "area_code": match.group(2),
        "sequence_number": int(match.group(3)),
        "computer_name": computer_name,
    }


def _request(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    """Single HTTP transport chokepoint; tests monkeypatch this function."""
    request = urllib.request.Request(url, data=body, method=method)
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SharedNamingUnavailableError(OFFLINE_MESSAGE) from exc


def _rest_url(settings: SharedNamingSettings, query_params: dict[str, str] | None = None) -> str:
    base = settings.supabase_url.rstrip("/")
    url = f"{base}/rest/v1/used_pano_names"
    if query_params:
        url += "?" + urllib.parse.urlencode(query_params)
    return url


def _headers(
    settings: SharedNamingSettings, extra: dict[str, str] | None = None
) -> dict[str, str]:
    headers = {
        "apikey": settings.supabase_anon_key,
        "Authorization": f"Bearer {settings.supabase_anon_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def fetch_max_sequence(
    settings: SharedNamingSettings, date_code: str, area_code: str
) -> int:
    status, body = _request(
        "GET",
        _rest_url(
            settings,
            {
                "date_code": f"eq.{date_code}",
                "area_code": f"eq.{area_code}",
                "select": "sequence_number",
                "order": "sequence_number.desc",
                "limit": "1",
            },
        ),
        _headers(settings),
        None,
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase lookup failed with HTTP {status}. {OFFLINE_MESSAGE}"
        )
    rows = json.loads(body or b"[]")
    if not rows:
        return 0
    return int(rows[0]["sequence_number"])


def register_names(
    settings: SharedNamingSettings, rows: list[dict[str, Any]]
) -> None:
    if not rows:
        return
    status, _body = _request(
        "POST",
        _rest_url(settings),
        _headers(settings, {"Prefer": "return=minimal"}),
        json.dumps(rows).encode("utf-8"),
    )
    if status == 409:
        raise SharedNamingConflictError(
            "One or more pano names were already taken in the shared registry."
        )
    if status not in {200, 201, 204}:
        raise SharedNamingUnavailableError(
            f"Supabase insert failed with HTTP {status}. {OFFLINE_MESSAGE}"
        )


def register_names_ignore_duplicates(
    settings: SharedNamingSettings, rows: list[dict[str, Any]]
) -> int:
    """Insert rows, skipping names that already exist. Returns the number added."""
    if not rows:
        return 0
    status, body = _request(
        "POST",
        _rest_url(settings, {"on_conflict": "name"}),
        _headers(
            settings,
            {"Prefer": "resolution=ignore-duplicates,return=representation"},
        ),
        json.dumps(rows).encode("utf-8"),
    )
    if status not in {200, 201}:
        raise SharedNamingUnavailableError(
            f"Supabase insert failed with HTTP {status}. {OFFLINE_MESSAGE}"
        )
    return len(json.loads(body or b"[]"))


def test_connection(settings: SharedNamingSettings) -> None:
    status, _body = _request(
        "GET",
        _rest_url(settings, {"select": "id", "limit": "1"}),
        _headers(settings),
        None,
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase returned HTTP {status}. Check the URL, anon key, and that the "
            "used_pano_names table exists with select/insert policies."
        )
