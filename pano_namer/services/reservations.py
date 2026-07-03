from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pano_namer.services.common import slugify_filename_stem, utc_now
from pano_namer.services.rename import RenamePlanItem

ACTIVE_RESERVATION_STATUSES = {"reserved", "applied"}
REPORTABLE_RESERVATION_STATUSES = {"reserved", "failed"}


def canonical_capture_date(capture_ts: str) -> str:
    """Return the canonical YYYY-MM-DD sequence scope date for a capture timestamp."""
    return datetime.fromisoformat(capture_ts).date().isoformat()


def area_slug(area_name: str) -> str:
    """Return the stable filename-safe area slug used for reservation namespaces."""
    return slugify_filename_stem(area_name)


def build_reserved_filename(
    capture_ts: str, area_name: str, sequence_number: int, extension: str
) -> str:
    """Build a final filename using the current YYMMDD_AREA_001.ext naming style."""
    stamp = datetime.fromisoformat(capture_ts).strftime("%y%m%d")
    return f"{stamp}_{area_slug(area_name)}_{sequence_number:03d}{extension.lower()}"


def _row_value(row: sqlite3.Row | dict[str, Any], key: str) -> Any:
    if isinstance(row, sqlite3.Row):
        return row[key] if key in row.keys() else None
    return row.get(key)


def _eligible(row: sqlite3.Row | dict[str, Any]) -> bool:
    if _row_value(row, "applied"):
        return False
    if _row_value(row, "error"):
        return False
    return bool(
        _row_value(row, "capture_ts")
        and _row_value(row, "area_name")
        and _row_value(row, "original_path")
    )


def _has_active_reservation(
    conn: sqlite3.Connection, project_id: int, photo_id: int
) -> bool:
    placeholders = ",".join("?" for _ in ACTIVE_RESERVATION_STATUSES)
    row = conn.execute(
        f"""
        SELECT 1
        FROM filename_reservations
        WHERE project_id = ? AND photo_id = ? AND reservation_status IN ({placeholders})
        LIMIT 1
        """,
        [project_id, photo_id, *sorted(ACTIVE_RESERVATION_STATUSES)],
    ).fetchone()
    return row is not None


def reserve_filenames_for_photos(
    conn: sqlite3.Connection,
    project_id: int,
    photo_rows: list[sqlite3.Row | dict[str, Any]],
    min_sequences: dict[tuple[str, str], int] | None = None,
) -> list[RenamePlanItem]:
    """Reserve durable filenames for eligible pending photos.

    The caller must own a write transaction before invoking this function. The
    server-side rename route starts that transaction with ``BEGIN IMMEDIATE`` so
    SQLite serializes counter updates and two writers cannot allocate the same
    project/date/area sequence range at the same time. Desktop-assisted rename
    uses the same allocator but stops after creating ``reserved`` rows so the
    desktop can perform local filesystem work and report results later.

    ``min_sequences`` maps a ``(canonical_capture_date, area_slug)`` group to the
    highest sequence number already used elsewhere (the shared Supabase
    registry); allocation for that group starts above both the local counter
    and that shared maximum.
    """
    groups: dict[tuple[str, str], list[sqlite3.Row | dict[str, Any]]] = defaultdict(
        list
    )
    for row in photo_rows:
        if not _eligible(row):
            continue
        photo_id = _row_value(row, "id")
        if photo_id is None or _has_active_reservation(conn, project_id, int(photo_id)):
            continue
        capture_ts = _row_value(row, "capture_ts")
        area_name = _row_value(row, "area_name")
        groups[(canonical_capture_date(capture_ts), area_slug(area_name))].append(row)

    plans: list[RenamePlanItem] = []
    for (capture_date, scoped_area_slug), rows in sorted(groups.items()):
        rows.sort(
            key=lambda item: (
                _row_value(item, "capture_ts"),
                _row_value(item, "original_path"),
                _row_value(item, "id"),
            )
        )
        now = utc_now()
        counter = conn.execute(
            """
            SELECT id, next_sequence_number
            FROM rename_sequence_counters
            WHERE project_id = ? AND capture_date = ? AND area_slug = ?
            """,
            (project_id, capture_date, scoped_area_slug),
        ).fetchone()
        if counter is None:
            cursor = conn.execute(
                """
                INSERT INTO rename_sequence_counters (
                    project_id, capture_date, area_slug, next_sequence_number, created_at, updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (project_id, capture_date, scoped_area_slug, now, now),
            )
            counter_id = cursor.lastrowid
            next_sequence = 1
        else:
            counter_id = counter["id"]
            next_sequence = counter["next_sequence_number"]

        if min_sequences:
            shared_max = min_sequences.get((capture_date, scoped_area_slug), 0)
            next_sequence = max(next_sequence, shared_max + 1)

        for row in rows:
            source_path = Path(_row_value(row, "original_path")).resolve()
            extension = source_path.suffix
            while True:
                final_filename = build_reserved_filename(
                    _row_value(row, "capture_ts"),
                    _row_value(row, "area_name"),
                    next_sequence,
                    extension,
                )
                target_path = source_path.with_name(final_filename)
                reserved_collision = conn.execute(
                    """
                    SELECT 1
                    FROM filename_reservations
                    WHERE project_id = ? AND (final_filename = ? OR target_path = ?)
                    LIMIT 1
                    """,
                    (project_id, final_filename, str(target_path)),
                ).fetchone()
                applied_collision = conn.execute(
                    """
                    SELECT 1
                    FROM photos
                    WHERE project_id = ? AND applied = 1 AND proposed_filename = ?
                    LIMIT 1
                    """,
                    (project_id, final_filename),
                ).fetchone()
                target_occupied = target_path.exists() and target_path != source_path
                if (
                    reserved_collision is None
                    and applied_collision is None
                    and not target_occupied
                ):
                    break
                next_sequence += 1

            reserved_at = utc_now()
            cursor = conn.execute(
                """
                INSERT INTO filename_reservations (
                    project_id, photo_id, photo_batch_id, rename_run_id, capture_date, area_slug,
                    sequence_number, final_filename, target_path, reservation_status,
                    reserved_at, applied_at, released_at, error, reported_at, updated_at
                )
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, 'reserved', ?, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    project_id,
                    _row_value(row, "id"),
                    _row_value(row, "photo_batch_id"),
                    capture_date,
                    scoped_area_slug,
                    next_sequence,
                    final_filename,
                    str(target_path),
                    reserved_at,
                    reserved_at,
                ),
            )
            plans.append(
                RenamePlanItem(
                    photo_id=_row_value(row, "id"),
                    source_path=source_path,
                    original_path=source_path,
                    target_path=target_path,
                    final_name=final_filename,
                    reservation_id=cursor.lastrowid,
                )
            )
            next_sequence += 1

        conn.execute(
            """
            UPDATE rename_sequence_counters
            SET next_sequence_number = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_sequence, utc_now(), counter_id),
        )

    return plans


def report_filename_reservation_results(
    conn: sqlite3.Connection,
    project_id: int,
    result_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply desktop-reported local rename outcomes to reservations and photos."""
    results: list[dict[str, Any]] = []
    for item in result_rows:
        photo_id = int(item.get("photo_id") or 0)
        reservation_id = int(item.get("reservation_id") or 0)
        status = item.get("status")
        reported_at = utc_now()
        if status not in {"applied", "failed"}:
            results.append(
                {
                    "photo_id": photo_id,
                    "reservation_id": reservation_id,
                    "status": "error",
                    "detail": "Unsupported status.",
                }
            )
            continue

        reservation = conn.execute(
            """
            SELECT *
            FROM filename_reservations
            WHERE project_id = ? AND id = ? AND photo_id = ?
            """,
            (project_id, reservation_id, photo_id),
        ).fetchone()
        if reservation is None:
            results.append(
                {
                    "photo_id": photo_id,
                    "reservation_id": reservation_id,
                    "status": "error",
                    "detail": "Reservation not found.",
                }
            )
            continue
        if reservation["reservation_status"] not in REPORTABLE_RESERVATION_STATUSES:
            results.append(
                {
                    "photo_id": photo_id,
                    "reservation_id": reservation_id,
                    "status": "error",
                    "detail": f"Reservation is {reservation['reservation_status']} and cannot accept desktop results.",
                }
            )
            continue

        if status == "applied":
            final_path = str(item.get("final_path") or reservation["target_path"])
            conn.execute(
                """
                UPDATE photos
                SET original_path = ?, proposed_filename = ?, applied = 1, error = NULL, updated_at = ?
                WHERE project_id = ? AND id = ?
                """,
                (
                    final_path,
                    reservation["final_filename"],
                    reported_at,
                    project_id,
                    photo_id,
                ),
            )
            conn.execute(
                """
                UPDATE filename_reservations
                SET target_path = ?, reservation_status = 'applied', applied_at = ?, error = NULL, reported_at = ?, updated_at = ?
                WHERE project_id = ? AND id = ?
                """,
                (
                    final_path,
                    reported_at,
                    reported_at,
                    reported_at,
                    project_id,
                    reservation_id,
                ),
            )
            results.append(
                {
                    "photo_id": photo_id,
                    "reservation_id": reservation_id,
                    "status": "applied",
                    "final_path": final_path,
                }
            )
            continue

        error = str(item.get("error") or "Desktop reported rename failure.")
        conn.execute(
            """
            UPDATE photos
            SET error = ?, updated_at = ?
            WHERE project_id = ? AND id = ? AND applied = 0
            """,
            (error, reported_at, project_id, photo_id),
        )
        conn.execute(
            """
            UPDATE filename_reservations
            SET reservation_status = 'failed', error = ?, reported_at = ?, updated_at = ?
            WHERE project_id = ? AND id = ?
            """,
            (error, reported_at, reported_at, project_id, reservation_id),
        )
        results.append(
            {
                "photo_id": photo_id,
                "reservation_id": reservation_id,
                "status": "failed",
                "error": error,
            }
        )
    return results
