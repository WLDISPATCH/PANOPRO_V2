"""Supabase-backed registry of exported panos used for Smart Import dedupe.

Smart Import queries this registry by original filename and confirms with
GPS proximity, so a pano that was already exported from any computer is
never copied off the card twice. Rows are registered at Smart Export time.

Requires this table in the same Supabase project as used_pano_names:

    create table pano_registry (
      id bigint generated always as identity primary key,
      original_name text not null,
      gps_lat double precision,
      gps_lon double precision,
      capture_ts timestamptz,
      is_panorama boolean default true,
      final_name text,
      computer_name text,
      created_at timestamptz default now()
    );
    create index pano_registry_original_name_idx
      on pano_registry (original_name);
"""

from __future__ import annotations

import json
import math
import urllib.parse
from typing import Any

from pano_namer.services.shared_naming import (
    SharedNamingSettings,
    SharedNamingUnavailableError,
    _headers,
    _request,
)

REGISTRY_OFFLINE_MESSAGE = (
    "Cannot check the shared pano registry while offline. "
    "Reconnect to Supabase before running Smart Import."
)

# Two GPS fixes of the same pano can drift slightly between reads; anything
# within this radius with the same original name is the same capture.
DUPLICATE_RADIUS_METERS = 5.0

_QUERY_CHUNK_SIZE = 100


def _registry_url(
    settings: SharedNamingSettings, query_params: dict[str, str] | None = None
) -> str:
    base = settings.supabase_url.rstrip("/")
    url = f"{base}/rest/v1/pano_registry"
    if query_params:
        url += "?" + urllib.parse.urlencode(query_params)
    return url


def _distance_meters(
    lat_a: float, lon_a: float, lat_b: float, lon_b: float
) -> float:
    lat_scale = 111_320.0
    lon_scale = lat_scale * math.cos(math.radians((lat_a + lat_b) / 2))
    return math.hypot((lat_a - lat_b) * lat_scale, (lon_a - lon_b) * lon_scale)


def fetch_registry_rows(
    settings: SharedNamingSettings, original_names: list[str]
) -> list[dict[str, Any]]:
    """Fetch registry rows matching any of the given original filenames."""
    rows: list[dict[str, Any]] = []
    unique_names = sorted(set(original_names))
    for start in range(0, len(unique_names), _QUERY_CHUNK_SIZE):
        chunk = unique_names[start : start + _QUERY_CHUNK_SIZE]
        quoted = ",".join('"' + name.replace('"', '\\"') + '"' for name in chunk)
        status, body = _request(
            "GET",
            _registry_url(
                settings,
                {
                    "original_name": f"in.({quoted})",
                    "select": "original_name,gps_lat,gps_lon,capture_ts",
                },
            ),
            _headers(settings),
            None,
        )
        if status != 200:
            raise SharedNamingUnavailableError(
                f"Supabase registry lookup failed with HTTP {status}. "
                f"{REGISTRY_OFFLINE_MESSAGE}"
            )
        rows.extend(json.loads(body or b"[]"))
    return rows


def fetch_exported_panos(
    settings: SharedNamingSettings, limit: int = 5000
) -> list[dict[str, Any]]:
    """Fetch every exported pano in the shared registry (org-wide).

    Powers the cloud-data display: names + real GPS of what the whole team has
    shot, from any computer. Only rows that were actually named/exported
    (final_name present) and flagged as panoramas are returned. Paginates so a
    large org isn't silently truncated by PostgREST's default row cap.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        status, body = _request(
            "GET",
            _registry_url(
                settings,
                {
                    "final_name": "not.is.null",
                    "is_panorama": "eq.true",
                    "select": "final_name,computer_name,capture_ts,gps_lat,gps_lon,created_at",
                    "order": "capture_ts.desc.nullslast",
                    "limit": str(_QUERY_CHUNK_SIZE),
                    "offset": str(offset),
                },
            ),
            _headers(settings),
            None,
        )
        if status != 200:
            raise SharedNamingUnavailableError(
                f"Supabase registry lookup failed with HTTP {status}. "
                f"{REGISTRY_OFFLINE_MESSAGE}"
            )
        page = json.loads(body or b"[]")
        rows.extend(page)
        if len(page) < _QUERY_CHUNK_SIZE or len(rows) >= limit:
            break
        offset += _QUERY_CHUNK_SIZE
    return rows[:limit]


def is_registered_duplicate(
    registry_rows: list[dict[str, Any]],
    original_name: str,
    gps_lat: float | None,
    gps_lon: float | None,
) -> bool:
    """True when a scanned pano matches a registry row.

    Name must match; GPS confirms when both sides have coordinates. A row
    without coordinates matches on name alone (better to skip a real
    duplicate than re-import one because an old row lacks GPS).
    """
    for row in registry_rows:
        if row.get("original_name") != original_name:
            continue
        row_lat = row.get("gps_lat")
        row_lon = row.get("gps_lon")
        if None in (row_lat, row_lon, gps_lat, gps_lon):
            return True
        if (
            _distance_meters(gps_lat, gps_lon, float(row_lat), float(row_lon))
            <= DUPLICATE_RADIUS_METERS
        ):
            return True
    return False


def register_panos(
    settings: SharedNamingSettings, rows: list[dict[str, Any]]
) -> None:
    """Insert exported panos into the registry."""
    if not rows:
        return
    status, _body = _request(
        "POST",
        _registry_url(settings),
        _headers(settings, {"Prefer": "return=minimal"}),
        json.dumps(rows).encode("utf-8"),
    )
    if status not in {200, 201, 204}:
        raise SharedNamingUnavailableError(
            f"Supabase registry insert failed with HTTP {status}. "
            f"{REGISTRY_OFFLINE_MESSAGE}"
        )


def registry_row_for_photo(
    original_name: str,
    gps_lat: float | None,
    gps_lon: float | None,
    capture_ts: str | None,
    final_name: str | None,
    computer_name: str,
) -> dict[str, Any]:
    return {
        "original_name": original_name,
        "gps_lat": gps_lat,
        "gps_lon": gps_lon,
        "capture_ts": capture_ts,
        "is_panorama": True,
        "final_name": final_name,
        "computer_name": computer_name,
    }


def test_registry_connection(settings: SharedNamingSettings) -> None:
    status, _body = _request(
        "GET",
        _registry_url(settings, {"select": "id", "limit": "1"}),
        _headers(settings),
        None,
    )
    if status != 200:
        raise SharedNamingUnavailableError(
            f"Supabase returned HTTP {status}. Check that the pano_registry "
            "table exists with select/insert policies."
        )
