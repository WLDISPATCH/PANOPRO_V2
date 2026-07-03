# Backend Multi-User Rename Sequencing Audit

## Scope

This audit documents the current SQLite database, photo import flow, rename preview flow, rename apply and rollback behavior, and the metadata model that PANO PRO should evolve before supporting organization-owned, multi-user industrial pano workflows.

This document now records the implemented SQLite Phase 1–3 backend foundation and the remaining multi-user roadmap. It does not migrate the app to Postgres, rewrite the database layer, add organizations/users, or change deployment behavior.

## Current state

### Current tables

The SQLite schema is created in `pano_namer/database.py` with `CREATE TABLE IF NOT EXISTS` statements. The current application tables are:

| Table | Current purpose |
| --- | --- |
| `projects` | Project/template record with name, storage root, CRS, and timestamps. |
| `overlays` | Managed georeferenced overlay image metadata for a project. |
| `areas` | Project area definitions, managed source paths, display color, CRS, geometry WKT, bbox, and active flag. |
| `photos` | Imported photo metadata and rename state, including project, batch ID, original path, capture timestamp, GPS/projected coordinates, matched area, proposed filename, applied flag, content hash, and error. |
| `rename_runs` | Rename execution history with project, generated batch ID, timestamps, summary JSON, results JSON, and rollback JSON/timestamps. |
| `archive_folders` | Folder hierarchy for archived pano organization. |
| `archived_panos` | Per-photo archive/review state. |
| `collections` | Named collections, descriptions, cover photo, and timestamps. |
| `collection_items` | Photo membership/order in collections. |
| `tags` | User/system tag names and tag type. |
| `pano_tags` | Photo-to-tag join table. |
| `saved_filters` | Named saved filter JSON configs. |
| `pano_annotations` | Viewer annotations with yaw/pitch and style JSON. |
| `pano_notes` | Photo notes. |
| `pano_issues` | Issue records with severity/status/assignment and optional yaw/pitch. |
| `pano_hotspots` | Pano-to-pano/manual hotspots with target photo and yaw/pitch. |
| `pano_view_state` | Per-photo default viewer orientation/FOV state. |
| `pano_thumbnails` | Derived thumbnail path and dimensions; the image is stored on disk, not in the database. |
| `pano_duplicates` | Content-hash duplicate pairs and duplicate review status. |
| `audit_events` | Application audit events stored as action/entity/payload JSON. |
| `schema_migrations` | Lightweight SQLite migration ledger recording applied compatibility/index/reservation migrations. |
| `rename_sequence_counters` | Durable project/date/area sequence counters for collaborative rename allocation. |
| `filename_reservations` | Auditable filename reservations linked to photos, photo batches, and rename runs. |

There is no organization table, user table, or project membership table yet. Photo batches, rename sequence counters, and filename reservations are now represented in SQLite.

### Projects/templates

Projects are currently the top-level tenant-like object. They are represented by `projects.id`, `name`, `storage_root`, `crs`, `created_at`, and `updated_at`. The current API creates a project from `ProjectCreate.name` plus an optional `storage_root`; the route stores the fixed CRS and creates a project storage directory. The UI/product language may still use “template” in some places, but the backend table and API model are project-oriented.

The current `projects` table has no owner, organization, status, slug, or membership field. All projects are globally visible to the single authenticated app session when auth is enabled.

### Areas and matching

Areas belong to a project and can be imported from DXF/KML or created manually. Each area stores metadata paths, display color, CRS, footprint WKT, bbox JSON, active state, and timestamps. Matching is recalculated for pending photos only. If GPS is available, the current matcher chooses the smallest containing polygon first and otherwise falls back to the nearest area. If a user manually assigns an area, the pending photo keeps `match_mode = manual` unless the selected area becomes invalid.

### Photos, import batches, and storage

Imported photos are represented by rows in `photos`. The database stores paths and metadata only; original media stays on disk/file storage. The import path supports:

- importing local paths supplied in JSON;
- uploading files through the API, which saves them under the project storage directory before importing them;
- grouping all paths from one import call under one generated `batch_id` string in the `photos` table;
- reading capture timestamp/GPS metadata;
- calculating a content hash for duplicate detection;
- creating thumbnail files on disk and storing thumbnail metadata paths;
- creating default viewer state rows;
- auto-adding photos with timestamps to weekly collections;
- recording duplicate pairs and audit events.

Duplicate import detection currently checks exact `original_path` values already stored for the project during the import call. The legacy `photos.batch_id` string is preserved for compatibility, while `photo_batches` now records durable import batches and `filename_reservations` records reservation status and batch/run linkage for new rename runs.

### Rename previews

Rename preview uses only pending photos (`photos.applied = 0`) for a project, optionally filtered to requested `photo_ids`. The preview service calls `plan_renames`, then returns planned rows plus skipped rows for missing timestamp, missing area, existing error, or other ineligible state.

`plan_renames` currently groups eligible rows by capture date stamp only. It sorts each date group by capture timestamp and original path, starts `sequence = 1` for each date group, builds filenames as `YYMMDD_AREA_###.<lowercase extension>`, and increments until the candidate does not collide with the scanned filesystem names or with an already-planned target path. It scans filenames in the parent directories of the source paths and tracks newly planned names in memory during that one planning call.

### Rename apply and rollback

Rename apply now reserves authoritative filenames in the database before filesystem changes. It starts a SQLite `BEGIN IMMEDIATE` write transaction, allocates project/date/area sequence numbers from `rename_sequence_counters`, inserts `filename_reservations`, and then performs the existing filesystem two-step rename: each source file is first renamed to a random hidden temp name and then temp files are renamed to final target paths. If the second phase raises, staged temp files are moved back to their original paths.

After filesystem operations complete, the database updates successful rows to the reserved target path, stores the proposed/final filename, marks them applied, clears errors, records a `rename_runs` row, links reservations to that run, and marks successful reservations `applied`. Failed rows are marked with an error and their reservations are marked `failed`. Rename run results and summaries are stored as JSON on `rename_runs`.

Rollback is limited to the most recent completed rename run for a project. It loads `results_json`, moves renamed files back to their original paths where safe, marks restored rows pending (`applied = 0`), refreshes pending matches/proposed filenames, stores rollback results/timestamps on the rename run, and marks related `filename_reservations` rows `rolled_back`. Rollback does not delete reservation history and does not decrement `rename_sequence_counters`; rolled-back sequence numbers are not automatically reused.

## Collision and sequencing risks

### Where filename collisions can happen today

Filename collisions can happen in these cases:

1. **Between two independent preview/apply cycles.** Preview is not a reservation. A second user or second batch can preview the same sequence range before the first batch applies it.
2. **Between a preview and a changed filesystem.** The planner scans the source directories at planning time, but files can appear after preview or during another process.
3. **Between two app instances.** The current in-memory `planned_duplicate` check only covers one process and one planning call.
4. **Across directories with the same project/date/area sequence intent.** Sequence checks are based on source parent directories, not a central project/date/area namespace.
5. **During apply if an external process creates a target after staging starts.** `Path.rename` behavior varies by platform; on Windows it generally will not overwrite an existing target, but the app should not rely on this as its central collision-control strategy.
6. **During rollback after later renames.** The app prevents rolling back any run except the most recent project run, which reduces but does not eliminate all file-level conflicts if files have been externally modified.

### Does rename allocation consider existing files, pending rows, or both?

Today it considers both, but only locally and at plan time:

- **Existing files:** `plan_renames` scans each source parent directory and treats existing child names as occupied.
- **Current pending rows:** it plans over the selected pending database rows and tracks already-planned target paths in memory.
- **Applied database rows:** it does not centrally query applied rows as reservations. Applied rows only matter indirectly if their renamed files are still present on disk in a scanned parent directory.
- **Other pending rows not included in a filtered request:** they are not considered when `photo_ids` filters the preview/run unless their files exist on disk under target names.

### Is sequencing safe for two users or two batches processed close together?

Apply-time sequencing is now protected by durable reservations and project/date/area counters in SQLite. Preview remains estimated and non-binding, so two users can still preview the same range, but only rename apply allocates authoritative numbers. The apply route uses `BEGIN IMMEDIATE` before allocation so SQLite serializes writers and the second batch receives the next available sequence range.

## Recommended default sequencing scope

For industrial pano workflows, the default sequence scope should be:

`project_id + capture_date + area_slug`

This gives operators stable, human-readable filenames per project, date, and work area while allowing William's and Jeff's uploads for the same project/date/area to share one continuous sequence namespace. In the example workflow, William's batch can reserve `001-050`; Jeff's later or concurrent batch can reserve `051-100`.

Do **not** scope the default counter by batch. Batch scope would avoid intra-batch collisions but would allow two batches in the same project/date/area to both start at `001`, which conflicts with the desired shared project workflow. Batch should be recorded on photos and reservations for audit, rollback, and review, but not used as the default sequence namespace.

A configurable future policy could support `project + date` for customers that want a single daily sequence across all areas, but the best default for PANO PRO's area-based industrial review model is `project + capture_date + area_slug`.

## Recommended schema additions

### Phase 1 SQLite clarity and migration discipline

Add migration discipline before new tables become numerous:

- `schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)` or an integer `schema_version` strategy;
- explicit migration functions/files instead of only opportunistic `ALTER TABLE` checks;
- indexes for current hot paths, including:
  - `photos(project_id, applied)`;
  - `photos(project_id, batch_id)`;
  - `photos(project_id, original_path)` with a future unique constraint after cleanup;
  - `photos(project_id, matched_area_id)`;
  - `areas(project_id, active)`;
  - `rename_runs(project_id, completed_at)`;
  - `pano_duplicates(photo_id)` and `pano_duplicates(duplicate_photo_id)`.

### Phase 2 first-class photo batches

Before rename reservations, PANO PRO should record durable import batches in `photo_batches` while preserving the legacy `photos.batch_id` string for compatibility. This lets the app audit William's and Jeff's separate imports in the same shared project before later assigning conflict-safe filenames.

Recommended `photo_batches` fields:

- `id INTEGER PRIMARY KEY` while on SQLite;
- `project_id INTEGER NOT NULL`;
- `batch_uid TEXT NOT NULL`;
- `source_kind TEXT NOT NULL DEFAULT 'unknown'`;
- `actor_label TEXT` as a lightweight placeholder before real users exist;
- `client_device TEXT` as a lightweight placeholder before device identity exists;
- `status TEXT NOT NULL DEFAULT 'imported'`;
- `photo_count INTEGER NOT NULL DEFAULT 0`;
- `notes TEXT`;
- `created_at TEXT NOT NULL`;
- `completed_at TEXT`;
- `updated_at TEXT NOT NULL`;
- `UNIQUE(project_id, batch_uid)`.

`photos.photo_batch_id` should be nullable during the compatibility period and backfilled from each legacy `(project_id, batch_id)` group.

### Phase 3 batch-aware rename reservation

PANO PRO now uses `rename_sequence_counters` and `filename_reservations` for apply-time rename allocation. Historical rename runs are not backfilled; reservations apply to rename runs created after the Phase 3 migration.

Recommended `rename_sequence_counters` fields:

- `id INTEGER PRIMARY KEY` while on SQLite;
- `project_id INTEGER NOT NULL`;
- `capture_date TEXT NOT NULL` using canonical `YYYY-MM-DD`;
- `area_slug TEXT NOT NULL`;
- `next_sequence_number INTEGER NOT NULL`;
- `created_at TEXT NOT NULL`;
- `updated_at TEXT NOT NULL`;
- `UNIQUE(project_id, capture_date, area_slug)`.

Recommended `filename_reservations` fields:

- `id INTEGER PRIMARY KEY` while on SQLite;
- `project_id INTEGER NOT NULL`;
- `photo_id INTEGER NOT NULL`;
- `photo_batch_id INTEGER` nullable until every reservation can be tied to a durable `photo_batches` row;
- `rename_run_id INTEGER` nullable until apply;
- `capture_date TEXT NOT NULL`;
- `area_slug TEXT NOT NULL`;
- `sequence_number INTEGER NOT NULL`;
- `final_filename TEXT NOT NULL`;
- `target_path TEXT NOT NULL`;
- `reservation_status TEXT NOT NULL` with values such as `reserved`, `applied`, `released`, `failed`, `rolled_back`;
- `reserved_at TEXT NOT NULL`;
- `applied_at TEXT`;
- `released_at TEXT`;
- unique constraints on `(project_id, capture_date, area_slug, sequence_number)` and `(project_id, final_filename)` or `(project_id, target_path)` depending on storage policy.

Phase 3 should allocate sequences inside a single database transaction before file operations. On SQLite, use `BEGIN IMMEDIATE` for the allocation transaction so only one writer can update counters/reservations at a time. On Postgres later, use row-level locking such as `SELECT ... FOR UPDATE` or an atomic `INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING` pattern.

Preview remains non-binding in Phase 3. Final filenames are reserved only at apply time. The current backend model is:

1. preview shows an estimated plan without reserving;
2. run/commit acquires reservations transactionally;
3. apply file renames using the reserved filenames;
4. update reservation statuses and `rename_runs` results;
5. rollback updates reservation statuses rather than deleting history.

Before deploying this migration to production, back up the SQLite database and media directories. The migration adds tables and indexes without deleting photos, rename runs, photo batches, or legacy `photos.batch_id` data.

### Phase 4 organization/user/project ownership scaffolding

Before moving to true multi-user organizations, add ownership scaffolding while preserving the current single-user auth behavior:

- `organizations(id, name, slug, created_at, updated_at)`;
- `users(id, email, display_name, role/status fields, created_at, updated_at)`;
- `organization_memberships(organization_id, user_id, role, created_at, updated_at)`;
- `projects.organization_id` nullable at first, backfilled to a default private organization;
- `projects.created_by_user_id` nullable at first;
- future user/device ownership fields on `photo_batches` once real organizations and users exist;
- `photos.photo_batch_id` nullable at first, while preserving the existing `batch_id` string until migration is complete;
- audit event actor fields such as `actor_user_id` and `organization_id` nullable at first.

Do not rename auth environment variables in this phase. The current login gate can map to a default local admin user internally while still accepting `PANOPRO_AUTH_*` configuration.

### Phase 5 Postgres compatibility preparation

Before Postgres, isolate database access enough that SQL dialect differences are deliberate:

- centralize connection/transaction helpers;
- remove hidden assumptions around `sqlite3.Row` from domain services over time;
- use parameterized SQL consistently and avoid dynamic placeholder strings where practical;
- avoid SQLite-only conflict syntax unless wrapped by a repository/helper;
- use canonical timestamp/date formats and explicit UTC handling;
- make JSON fields explicit migration choices (`TEXT` in SQLite, `JSONB` in Postgres later);
- replace `INTEGER PRIMARY KEY AUTOINCREMENT` assumptions with a migration strategy for Postgres identity columns;
- audit foreign keys, indexes, and uniqueness constraints before export/import.

### Phase 6 production Postgres migration

Migrate production only after backups and migration tooling are tested:

- ship backup/export tooling for SQLite;
- add a repeatable SQLite-to-Postgres migration script;
- dry-run migration in CI or a staging copy;
- validate row counts, checksums for important JSON/path fields, foreign-key integrity, and reservation uniqueness;
- keep media on disk/object storage and migrate only metadata/paths/relationships;
- document rollback to SQLite from a pre-migration backup;
- rehearse Windows desktop local usage and server usage separately.

## Staged implementation roadmap

### Phase 1: Keep SQLite and improve schema clarity

1. Add a migration table and versioned migration runner that still initializes new local databases smoothly.
2. Convert current opportunistic column additions into named migrations.
3. Add non-invasive indexes for current query paths.
4. Add tests that initialize from empty DB and from a pre-migration SQLite fixture.
5. Do not change existing rename behavior in this phase beyond indexes/migration discipline.

### Phase 2: Add first-class photo batches

1. Add `photo_batches` with project-scoped unique batch identifiers and lightweight actor/device placeholders.
2. Add nullable `photos.photo_batch_id` while preserving `photos.batch_id` for compatibility.
3. Backfill legacy photos into durable batch rows by `(project_id, batch_id)`.
4. Update import flows to create and complete a batch row for each import attempt.
5. Keep rename behavior unchanged until reservation tables are introduced.

### Phase 3: Add batch-aware sequence reservations

1. Added `rename_sequence_counters` and `filename_reservations`.
2. Added a reservation service that derives `capture_date`, `area_slug`, sequence number, filename, and target path.
3. During rename run, reservations are allocated inside one transaction and reserved filenames are used for filesystem apply.
4. Existing temp-file staging and rollback behavior is preserved.
5. Reservations are marked `applied`, `failed`, or `rolled_back` as rename/rollback progresses.
6. Preview remains estimated/non-binding; final filenames are reserved only at apply time.

### Phase 4: Add organization/user/project ownership scaffolding

1. Add default organization and default local admin user records.
2. Backfill existing projects to the default organization.
3. Add nullable actor/owner columns and audit linkage.
4. Link durable photo batches to future ownership fields after real users/devices exist.
5. Preserve current single-user auth and environment variable names.

### Phase 5: Prepare for Postgres compatibility

1. Introduce repository/transaction boundaries for rename allocation and project/photo queries.
2. Keep raw SQL where useful, but isolate dialect-specific upsert/locking logic.
3. Add migration tests that can run on SQLite now and Postgres later.
4. Add a Postgres schema generation/migration dry-run path without switching production.

### Phase 6: Migrate production to Postgres after tested backups

1. Freeze writes or run maintenance mode.
2. Back up SQLite and media directories.
3. Run tested migration tooling.
4. Validate data integrity and filename reservations.
5. Switch server connection settings.
6. Keep rollback instructions and backups until production stability is confirmed.

## Required tests to add or update

### Sequence allocation

- Unit-test filename generation by `project_id + capture_date + area_slug`.
- Test allocation starts at `001` for a new scope.
- Test allocation continues after existing reservations.
- Test area slug normalization is stable and collision-aware.

### Concurrent/batch collision prevention

- Simulate William and Jeff importing separate batches for the same project/date/area.
- Run allocation twice and assert the second allocation receives the next range, not duplicate `001` values.
- Add a SQLite transaction test using separate connections to verify one writer cannot allocate the same scope concurrently.
- Later add the equivalent Postgres row-lock/upsert test.

### Rollback

- Preserve current test coverage that only the latest run can be rolled back.
- Assert rollback restores files, photo `applied` state, and reservation statuses.
- Assert rollback does not delete reservation history.
- Assert rollback fails safely if original target paths are blocked.

### Duplicate detection

- Keep content-hash duplicate pair tests.
- Add tests across batches in the same project.
- Add tests across projects once organization/project ownership is introduced, deciding whether duplicates are project-local or organization-visible.

### Organization/user ownership

- Test default organization/user bootstrap on existing databases.
- Test project ownership filters once multi-user routes exist.
- Test admin/operator permission boundaries.
- Test audit events include actor context when available.
- Test current single-user auth behavior still works and env var names remain unchanged.

### SQLite-to-Postgres migration later

- Test empty database migration.
- Test migration with projects, areas, pending/applied photos, rename runs, reservations, duplicate pairs, annotations, issues, collections, tags, thumbnails, hotspots, and audit events.
- Validate row counts, foreign keys, unique reservation constraints, JSON parseability, and path preservation.
- Test migration failure leaves the SQLite source untouched.

## Exact first implementation task to give Codex next

> Add a lightweight SQLite migration discipline without changing production behavior: create a `schema_migrations` table, move the existing compatibility column checks for `areas.display_color`, `photos.content_hash`, and `rename_runs.rollback_*` into named idempotent migrations, add safe indexes for `photos(project_id, applied)`, `photos(project_id, batch_id)`, `photos(project_id, original_path)`, `areas(project_id, active)`, and `rename_runs(project_id, completed_at)`, and add tests proving initialization works for both an empty database and a manually-created legacy database missing those columns. Do not add org/user tables or rename reservation tables yet.

## Risks before moving to Postgres

- The current schema now has a lightweight SQLite migration ledger, but it still needs a fuller forward-only migration discipline before Postgres-oriented multi-user changes.
- Rename sequence allocation now uses durable SQLite reservations for tested desktop/server flows, but still needs repository boundaries and Postgres-oriented locking before hosted multi-user deployment.
- JSON stored as text needs validation and migration decisions before using Postgres `JSONB`.
- `sqlite3.Row`, dynamic placeholder SQL, and SQLite upsert syntax are spread through route code.
- There is no first-class organization/user/batch ownership model yet.
- File paths are local-disk oriented and should be audited before server/object-storage deployment.
- Rollback behavior depends on local filesystem state and most-recent-run ordering; reservation statuses must preserve this safety property.
- Migration must not store media blobs in the database; only metadata, paths, relationships, and job/reservation state should move.

## Database/Desktop Phase 4: reservation-backed desktop rename flow

### Current server-side rename behavior

The existing `POST /api/projects/{project_id}/rename-runs` route remains the compatibility path for the current **Rename Eligible Photos** button. It now has these explicit properties:

- It opens a SQLite write transaction and allocates names through `filename_reservations`, so filename sequence numbers are centrally reserved by the backend before filesystem work begins.
- It immediately performs filesystem rename operations in the server/local runtime with the reservation plan.
- Successful `renamed` or `unchanged` results update `photos.original_path`, `photos.proposed_filename`, `photos.applied = 1`, and mark the matching reservation `applied`.
- Failed per-file results leave the photo unapplied, set the photo error, and mark the reservation `failed`.
- It records a `rename_runs` row with the run summary/results and links the reservations to that run.
- Rollback remains scoped to the latest completed rename run, restores the local file when possible, sets photos back to pending, and marks linked reservations `rolled_back` without deleting reservation history.

This path is safe for the single-machine desktop/server runtime, but it is intentionally not the final collaborative desktop model because the backend process must be able to see and mutate the same local paths as the user.

### New desktop-assisted reservation/result path

Phase 4 adds an additive API path for the collaborative desktop renamer:

1. `POST /api/projects/{project_id}/rename-reservations/commit`
   - Allocates durable backend reservations for eligible pending photos.
   - Does **not** rename local files.
   - Does **not** set `photos.applied`.
   - Returns a per-photo plan with `reservation_id`, `photo_id`, `source_path`, `target_path`, and `final_name`.
2. The desktop app can rename the user's local files directly using that plan.
3. `POST /api/projects/{project_id}/rename-reservations/report-results`
   - Accepts per-photo `applied` / `failed` results.
   - Applied results mark reservations `applied`, set `applied_at`/`reported_at`, update `photos.original_path` to the final path, set `photos.proposed_filename`, and set `photos.applied = 1`.
   - Failed results mark reservations `failed`, store reservation `error`/`reported_at`, and keep `photos.applied = 0`.

Reservation states are now used as follows:

- `reserved`: backend allocated the name, but no successful local/server rename has been reported.
- `applied`: server-side rename or desktop-reported local rename succeeded.
- `failed`: server-side rename or desktop-reported local rename failed; error details are preserved when reported.
- `released`: reserved for a future explicit abandon/release flow.
- `rolled_back`: a server-side applied rename was successfully rolled back.

### William/Jeff sequencing example

The backend remains the source of truth for sequence allocation. If William commits a batch for a project/date/area first, he receives `001-050`. If Jeff commits another batch for the same project/date/area later, Jeff receives `051-100`, even before William reports his local filesystem results. This is enforced by the shared `rename_sequence_counters` scope and durable `filename_reservations` rows.

### Next desktop wiring tasks

- Add a UI affordance that uses the commit endpoint for local-desktop reservation mode instead of the server-side rename-run endpoint.
- Have the PySide6 desktop shell perform the local file renames from the returned plan and call `report-results` with per-file success/failure.
- Keep the current server-side **Rename Eligible Photos** button available for the single-machine compatibility workflow until the desktop-assisted flow is fully exposed and reviewed.
- Add an explicit release/abandon flow if operators need to discard reserved-but-unapplied names.

No organizations, user roles, Postgres migration, object storage, media upload platform, or large UI redesign was added in Phase 4.
