from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pano_namer.area_colors import next_available_area_color, normalize_area_color

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    storage_root TEXT NOT NULL,
    crs TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS overlays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    display_name TEXT,
    jpg_original_path TEXT NOT NULL,
    jpg_managed_path TEXT NOT NULL,
    crs TEXT,
    bounds_json TEXT,
    width INTEGER,
    height INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    dxf_original_path TEXT NOT NULL,
    dxf_managed_path TEXT NOT NULL,
    display_color TEXT NOT NULL,
    source_crs TEXT NOT NULL,
    footprint_wkt TEXT NOT NULL,
    footprint_bbox_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photo_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_uid TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'unknown',
    actor_label TEXT,
    client_device TEXT,
    status TEXT NOT NULL DEFAULT 'imported',
    photo_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, batch_uid)
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    photo_batch_id INTEGER REFERENCES photo_batches(id),
    original_path TEXT NOT NULL,
    capture_ts TEXT,
    gps_lat REAL,
    gps_lon REAL,
    projected_x REAL,
    projected_y REAL,
    matched_area_id INTEGER REFERENCES areas(id),
    match_mode TEXT,
    proposed_filename TEXT,
    applied INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rename_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    rollback_started_at TEXT,
    rollback_completed_at TEXT,
    summary_json TEXT NOT NULL,
    results_json TEXT NOT NULL,
    rollback_results_json TEXT
);


CREATE TABLE IF NOT EXISTS rename_sequence_counters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    capture_date TEXT NOT NULL,
    area_slug TEXT NOT NULL,
    next_sequence_number INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, capture_date, area_slug)
);

CREATE TABLE IF NOT EXISTS filename_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    photo_batch_id INTEGER REFERENCES photo_batches(id) ON DELETE SET NULL,
    rename_run_id INTEGER REFERENCES rename_runs(id) ON DELETE SET NULL,
    capture_date TEXT NOT NULL,
    area_slug TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    final_filename TEXT NOT NULL,
    target_path TEXT NOT NULL,
    reservation_status TEXT NOT NULL DEFAULT 'reserved',
    reserved_at TEXT NOT NULL,
    applied_at TEXT,
    released_at TEXT,
    error TEXT,
    reported_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, capture_date, area_slug, sequence_number),
    UNIQUE(project_id, final_filename),
    UNIQUE(project_id, target_path)
);

CREATE TABLE IF NOT EXISTS archive_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES archive_folders(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archived_panos (
    photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    folder_id INTEGER REFERENCES archive_folders(id) ON DELETE SET NULL,
    reviewed INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    cover_photo_id INTEGER REFERENCES photos(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    item_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(collection_id, photo_id)
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    tag_type TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pano_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE(photo_id, tag_id)
);

CREATE TABLE IF NOT EXISTS saved_filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    filter_scope TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pano_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    annotation_type TEXT NOT NULL,
    label TEXT,
    yaw REAL NOT NULL,
    pitch REAL NOT NULL,
    style_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pano_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    note_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pano_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    issue_text TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'open',
    assigned_to TEXT,
    yaw REAL,
    pitch REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pano_hotspots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    target_photo_id INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    yaw REAL NOT NULL,
    pitch REAL NOT NULL,
    label TEXT,
    hotspot_type TEXT NOT NULL DEFAULT 'manual',
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pano_view_state (
    photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    north_offset REAL NOT NULL DEFAULT 0,
    default_yaw REAL NOT NULL DEFAULT 0,
    default_pitch REAL NOT NULL DEFAULT 0,
    default_fov REAL NOT NULL DEFAULT 75,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pano_thumbnails (
    photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    thumb_path TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pano_duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    duplicate_photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'detected',
    created_at TEXT NOT NULL,
    UNIQUE(photo_id, duplicate_photo_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT,
    display_name TEXT,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


Migration = tuple[str, Callable[[sqlite3.Connection], None]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _migrate_area_display_colors(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "areas")
    if "display_color" not in columns:
        conn.execute("ALTER TABLE areas ADD COLUMN display_color TEXT")

    rows = conn.execute(
        "SELECT id, project_id, display_color FROM areas ORDER BY project_id ASC, id ASC"
    ).fetchall()
    colors_by_project: dict[int, list[str]] = {}
    for row in rows:
        project_id = row["project_id"]
        project_colors = colors_by_project.setdefault(project_id, [])
        existing_color = normalize_area_color(row["display_color"])
        if existing_color:
            project_colors.append(existing_color)
            continue
        assigned_color = next_available_area_color(project_colors)
        conn.execute(
            "UPDATE areas SET display_color = ? WHERE id = ?",
            (assigned_color, row["id"]),
        )
        project_colors.append(assigned_color)


def _migrate_rename_run_rollback_columns(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "rename_runs")
    if "rollback_started_at" not in columns:
        conn.execute("ALTER TABLE rename_runs ADD COLUMN rollback_started_at TEXT")
    if "rollback_completed_at" not in columns:
        conn.execute("ALTER TABLE rename_runs ADD COLUMN rollback_completed_at TEXT")
    if "rollback_results_json" not in columns:
        conn.execute("ALTER TABLE rename_runs ADD COLUMN rollback_results_json TEXT")


def _migrate_photo_content_hash(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "photos")
    if "content_hash" not in columns:
        conn.execute("ALTER TABLE photos ADD COLUMN content_hash TEXT")


def _migrate_photo_batches(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS photo_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            batch_uid TEXT NOT NULL,
            source_kind TEXT NOT NULL DEFAULT 'unknown',
            actor_label TEXT,
            client_device TEXT,
            status TEXT NOT NULL DEFAULT 'imported',
            photo_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, batch_uid)
        )
        """)

    columns = _table_columns(conn, "photos")
    if "photo_batch_id" not in columns:
        conn.execute(
            "ALTER TABLE photos ADD COLUMN photo_batch_id INTEGER REFERENCES photo_batches(id)"
        )

    now = _utc_now()
    batch_rows = conn.execute(
        """
        SELECT
            project_id,
            batch_id,
            COUNT(*) AS photo_count,
            MIN(COALESCE(created_at, ?)) AS created_at,
            MAX(COALESCE(updated_at, created_at, ?)) AS updated_at,
            MIN(COALESCE(applied, 0)) AS all_applied
        FROM photos
        WHERE batch_id IS NOT NULL AND batch_id != ''
        GROUP BY project_id, batch_id
        """,
        (now, now),
    ).fetchall()

    for row in batch_rows:
        created_at = row["created_at"] or now
        updated_at = row["updated_at"] or created_at
        status = "applied" if row["all_applied"] else "imported"
        completed_at = updated_at if status == "applied" else None
        conn.execute(
            """
            INSERT INTO photo_batches (
                project_id, batch_uid, source_kind, status, photo_count,
                created_at, completed_at, updated_at
            )
            VALUES (?, ?, 'legacy', ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, batch_uid) DO UPDATE SET
                status = excluded.status,
                photo_count = excluded.photo_count,
                completed_at = excluded.completed_at,
                updated_at = excluded.updated_at
            """,
            (
                row["project_id"],
                row["batch_id"],
                status,
                row["photo_count"],
                created_at,
                completed_at,
                updated_at,
            ),
        )
        batch = conn.execute(
            "SELECT id FROM photo_batches WHERE project_id = ? AND batch_uid = ?",
            (row["project_id"], row["batch_id"]),
        ).fetchone()
        if batch is not None:
            conn.execute(
                """
                UPDATE photos
                SET photo_batch_id = ?
                WHERE project_id = ? AND batch_id = ?
                  AND (photo_batch_id IS NULL OR photo_batch_id != ?)
                """,
                (batch["id"], row["project_id"], row["batch_id"], batch["id"]),
            )

    index_statements = (
        "CREATE INDEX IF NOT EXISTS idx_photo_batches_project_batch_uid ON photo_batches(project_id, batch_uid)",
        "CREATE INDEX IF NOT EXISTS idx_photo_batches_project_created_at ON photo_batches(project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_photos_project_photo_batch_id ON photos(project_id, photo_batch_id)",
    )
    for statement in index_statements:
        conn.execute(statement)


def _migrate_filename_reservations(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rename_sequence_counters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            capture_date TEXT NOT NULL,
            area_slug TEXT NOT NULL,
            next_sequence_number INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, capture_date, area_slug)
        )
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS filename_reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            photo_batch_id INTEGER REFERENCES photo_batches(id) ON DELETE SET NULL,
            rename_run_id INTEGER REFERENCES rename_runs(id) ON DELETE SET NULL,
            capture_date TEXT NOT NULL,
            area_slug TEXT NOT NULL,
            sequence_number INTEGER NOT NULL,
            final_filename TEXT NOT NULL,
            target_path TEXT NOT NULL,
            reservation_status TEXT NOT NULL DEFAULT 'reserved',
            reserved_at TEXT NOT NULL,
            applied_at TEXT,
            released_at TEXT,
            error TEXT,
            reported_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, capture_date, area_slug, sequence_number),
            UNIQUE(project_id, final_filename),
            UNIQUE(project_id, target_path)
        )
        """)
    index_statements = (
        "CREATE INDEX IF NOT EXISTS idx_filename_reservations_project_photo_id ON filename_reservations(project_id, photo_id)",
        "CREATE INDEX IF NOT EXISTS idx_filename_reservations_project_photo_batch_id ON filename_reservations(project_id, photo_batch_id)",
        "CREATE INDEX IF NOT EXISTS idx_filename_reservations_project_rename_run_id ON filename_reservations(project_id, rename_run_id)",
        "CREATE INDEX IF NOT EXISTS idx_filename_reservations_project_status ON filename_reservations(project_id, reservation_status)",
        "CREATE INDEX IF NOT EXISTS idx_filename_reservations_project_scope ON filename_reservations(project_id, capture_date, area_slug)",
        "CREATE INDEX IF NOT EXISTS idx_rename_sequence_counters_project_scope ON rename_sequence_counters(project_id, capture_date, area_slug)",
    )
    for statement in index_statements:
        conn.execute(statement)


def _migrate_filename_reservation_report_columns(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "filename_reservations")
    if "error" not in columns:
        conn.execute("ALTER TABLE filename_reservations ADD COLUMN error TEXT")
    if "reported_at" not in columns:
        conn.execute("ALTER TABLE filename_reservations ADD COLUMN reported_at TEXT")


def _migrate_current_query_indexes(conn: sqlite3.Connection) -> None:
    index_statements = (
        "CREATE INDEX IF NOT EXISTS idx_photos_project_applied ON photos(project_id, applied)",
        "CREATE INDEX IF NOT EXISTS idx_photos_project_batch_id ON photos(project_id, batch_id)",
        "CREATE INDEX IF NOT EXISTS idx_photos_project_original_path ON photos(project_id, original_path)",
        "CREATE INDEX IF NOT EXISTS idx_photos_project_matched_area_id ON photos(project_id, matched_area_id)",
        "CREATE INDEX IF NOT EXISTS idx_areas_project_active ON areas(project_id, active)",
        "CREATE INDEX IF NOT EXISTS idx_rename_runs_project_completed_at ON rename_runs(project_id, completed_at)",
        "CREATE INDEX IF NOT EXISTS idx_pano_duplicates_photo_id ON pano_duplicates(photo_id)",
        "CREATE INDEX IF NOT EXISTS idx_pano_duplicates_duplicate_photo_id ON pano_duplicates(duplicate_photo_id)",
    )
    for statement in index_statements:
        conn.execute(statement)


def _migrate_users_admin(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
    index_statements = (
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
        "CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin)",
    )
    for statement in index_statements:
        conn.execute(statement)


def _migrate_app_settings(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT NOT NULL
        )
        """)


def _migrate_area_sync_uid(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "areas")
    if "sync_uid" not in columns:
        conn.execute("ALTER TABLE areas ADD COLUMN sync_uid TEXT")


def _migrate_overlay_display_name(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "overlays")
    if "display_name" not in columns:
        conn.execute("ALTER TABLE overlays ADD COLUMN display_name TEXT")
    rows = conn.execute(
        "SELECT id, display_name, jpg_original_path, jpg_managed_path FROM overlays"
    ).fetchall()
    for row in rows:
        if row["display_name"]:
            continue
        source_path = row["jpg_original_path"] or row["jpg_managed_path"] or ""
        display_name = Path(source_path).stem or f"Overlay {row['id']}"
        conn.execute(
            "UPDATE overlays SET display_name = ? WHERE id = ?",
            (display_name, row["id"]),
        )


MIGRATIONS: tuple[Migration, ...] = (
    ("20260508_0001_area_display_colors", _migrate_area_display_colors),
    ("20260508_0002_rename_run_rollback_columns", _migrate_rename_run_rollback_columns),
    ("20260508_0003_photo_content_hash", _migrate_photo_content_hash),
    ("20260508_0004_current_query_indexes", _migrate_current_query_indexes),
    ("20260511_0005_photo_batches", _migrate_photo_batches),
    ("20260511_0006_filename_reservations", _migrate_filename_reservations),
    (
        "20260512_0007_filename_reservation_reports",
        _migrate_filename_reservation_report_columns,
    ),
    ("20260512_0008_users_admin", _migrate_users_admin),
    ("20260702_0009_app_settings", _migrate_app_settings),
    ("20260702_0010_area_sync_uid", _migrate_area_sync_uid),
    ("20260703_0011_overlay_display_name", _migrate_overlay_display_name),
)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._run_migrations(conn)
            conn.commit()

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """)
        applied_versions = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for version, migrate in MIGRATIONS:
            if version in applied_versions:
                continue
            migrate(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
