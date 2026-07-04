# Smart Mode — Design Spec (draft)

Status: brainstorm / pre-implementation
Date: 2026-07-03

## Concept

Smart Mode is a simplified operating mode for PANO PRO aimed at the field workflow:
pull the SD card out of the drone, plug it in, press one button to import, press one
button to export. It hides everything except a single "Smart View" tab (the Review
map) with two primary buttons — **Smart Import** and **Smart Export** — plus a small
Advanced/Smart toggle in the bottom-left of the sidebar nav.

Advanced mode remains the full existing app; Smart Mode is a UI + automation layer
over the same backend pipeline (import → area match → stage names → rename), not a
separate system.

## What we verified on real data

Inspected stitched panos from `C:\Desktop\260316_Panos` (DJI Matrice 4E):

| Signal | Value on stitched 360s |
|---|---|
| XMP `GPano:ProjectionType` | `"equirectangular"` — definitive pano marker |
| Aspect ratio | exactly 2:1 (14400×7200) — fallback signal |
| GPS | `drone-dji:GpsLatitude` / `GpsLongitude` (already parsed by `services/photos.py`) |
| Capture time | `xmp:CreateDate` with timezone |
| Make/Model | `tiff:Make="DJI"`, `tiff:Model="M4E"` |

Raw stitch-source tiles (in `DCIM/PANORAMA/...`) and regular photos do **not** carry
the `GPano` equirectangular tag, so classification is purely metadata-driven — no
reliance on DJI's folder naming (`dji-forthills-...` etc.).

## Smart Import

1. **SD card detection** — poll for removable drives (Windows `GetDriveType ==
   DRIVE_REMOVABLE`) containing a `DCIM` folder. Auto-select when exactly one
   candidate exists; manual folder picker as fallback (also makes it testable
   without a card).
2. **Scan & classify** — walk `DCIM` recursively for JPGs; read the first ~2 MB of
   each file for XMP; classify:
   - `GPano:ProjectionType == equirectangular` → **360 pano**
   - else 2:1 ratio at pano resolution → **pano (fallback)**
   - everything else (raw tiles, normal photos, video) → **skipped**
   Smart Mode handles stitched 360 panos only; normal photos are counted in the
   summary but never copied or staged.
   Extract original filename, GPS lat/long, capture timestamp during the same pass.
3. **Duplicate check** — batch-query the Supabase `pano_registry` table by original
   filename, then confirm with GPS proximity (~3 m) / capture timestamp locally.
   Matches are skipped (counted and reported, never copied).
4. **Copy** — non-duplicates are copied (original names kept) into
   `<smart_import_base_path>\<YYMMDD>\` where `YYMMDD` comes from each file's
   capture date. Base path is a one-time setting configured in Advanced mode →
   System → Settings.
5. **Stage** — feed the copied paths into the existing import pipeline
   (`import_photo_paths` in `main.py`): EXIF extraction, area matching
   (`services/matching.py`), proposed `YYMMDD_AREA_###` names, pins on the map.
6. **Summary toast/modal** — "Found 93 panos, 12 normal photos · 41 duplicates
   skipped · 52 staged on map".

## Smart Export

One button that runs, in order:

1. **Register in Supabase** — insert each exported photo into `pano_registry`
   (original name, lat/long, capture ts, final name, computer name). This is the
   data future Smart Imports dedupe against. Registering at export time (not import)
   means an aborted session can be re-imported cleanly.
2. **Rename** — run the existing durable rename pipeline
   (`services/rename.py` + `services/reservations.py`), including the existing
   shared-naming sequence sync so multi-computer numbering keeps working.
3. **FTP upload** — upload the renamed files to the existing FTP server via
   `ftplib`. Per-file status tracking with retry for transient failures; nothing is
   marked uploaded until the server confirms. Credentials/remote path from settings.
   (Server details / directory layout / FTPS-vs-FTP: TBD — see open questions.)
4. **Archive** — after a successful upload, move the renamed files from the dated
   import folder into `<archive_base_path>\<YYMMDD>\` (archive base path is a
   setting, like the import base path). The dated import folder is the working
   area; the archive is the long-term home.
5. **Summary** — renamed / registered / uploaded / archived / failed counts, with
   failures listed and re-runnable (export is idempotent: already-registered and
   already-uploaded photos are skipped on retry).

## Data model changes

Local SQLite (`database.py` migrations):
- `photos.is_panorama INTEGER` — set at import from XMP classification
- `photos.upload_status TEXT` / `photos.uploaded_at TEXT` — FTP tracking
- settings storage for: `ui_mode` (`advanced`/`smart`), `smart_import_base_path`,
  `smart_archive_base_path`, FTP `host/port/username/password/remote_path/use_tls`

Supabase (new table, same project as `used_pano_names`):

```sql
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
create index pano_registry_original_name_idx on pano_registry (original_name);
```

## Backend additions

Follow the existing service/route patterns:

- `services/sd_card.py` — removable-drive detection, DCIM scan, XMP classification
  (reuse/extend `read_photo_metadata` in `services/photos.py`)
- `services/pano_registry.py` — Supabase REST client, modeled on
  `services/shared_naming.py` (urllib pattern, same credential settings)
- `services/ftp_export.py` — ftplib upload with per-file results
- `api/routes/smart.py` — `POST /api/smart/scan`, `POST /api/smart/import`,
  `POST /api/smart/export`, plus settings GET/PUT (or extend
  `api/routes/settings.py`)

## Frontend additions

- **Toggle** — small Smart/Advanced pill pinned to the bottom of
  `<aside class="sidebar">` (after the `.tabs.sidebar-nav` block in `index.html`).
  Persisted via the settings API so it survives restarts.
- **Smart Mode layout** — a `smart-mode` class on `<body>`; CSS hides all tabs and
  panels except Review, relabels it "Smart View", trims the map command bar to
  essentials, and shows two large **Smart Import** / **Smart Export** buttons.
- **Progress UI** — step-list modal during import/export (Detecting SD → Scanning →
  Checking duplicates → Copying → Staging / Registering → Renaming → Uploading),
  since these are long multi-stage operations.

## Decisions

1. **Project binding** — Smart Mode uses whatever project the app is currently set
   to (last-active project); no separate pinned-project setting.
2. **Normal (non-pano) photos** — ignored entirely. Smart Import copies and stages
   stitched 360 panos only.
3. **Post-export archive** — after upload, renamed files are moved to an archive
   location configured in settings (`smart_archive_base_path`), organized by
   `YYMMDD` like the import folder.
4. **Registry timing** — photos are registered in Supabase at export time, so an
   imported-but-never-exported card re-stages cleanly on the next Smart Import.

## Open questions

1. **FTP details** — server host/credentials and directory layout. The settings UI
   (System → Settings → Smart Mode) supports FTP, FTPS (TLS), and SFTP (SSH) with a
   protocol dropdown; port is optional (defaults to 21/22 by protocol). Uploads
   mirror the `YYMMDD/` folder structure under the configured server folder. Owner
   fills in the server details when available.
