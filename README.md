# PANO PRO

PanoPro is a private industrial pano/photo management platform for DJI aerial 360 imports, DXF/KML area matching, map-based review, safe rename workflows, archive organization, collections, 360 viewing, notes/issues/annotations, tags, duplicate review, thumbnails, reports, audit history, and future web-ready operations.

The historical Python package and local data names (`pano_namer`, `.pano_namer_data`, and `pano_namer.db`) are intentionally preserved as internal technical identifiers so existing imports, deployments, builds, and local data keep working.

Windows-first, web-ready app for importing DJI 360 photos, matching them to DXF- or KML-defined areas, reviewing them on a map, and safely renaming or organizing them for inspection and reporting workflows.

## Features

- Project library with managed DXF and KML areas
- Largest-polygon area footprint extraction from DXF or KML
- Fixed NAD83 / UTM zone 12 (`EPSG:26912`) project CRS
- Georeferenced PDF overlay handling
- DJI photo metadata extraction from EXIF/XMP
- GPS point-in-polygon matching with nearest-area fallback
- Batch rename planning using `YYMMDD_AREA_sequence`
- FastAPI service layer and PySide6 desktop host

## Quick Install (New Machine)

For setting up a fresh computer, use the one-click installer instead of the
manual steps below:

1. Download and unzip this repository.
2. Double-click **`install.bat`** in the unzipped folder.

The installer auto-installs Python 3.13 (via winget) if it isn't already
present, sets up a local environment with all dependencies, and creates a
**PANO PRO** shortcut on the desktop and Start Menu. Launch the app from that
shortcut. Keep the unzipped folder in place — it is the installed app. Re-run
`install.bat` any time to repair or update dependencies.

## Run From Source

1. Install Python 3.13.
2. Install dependencies:

```powershell
C:\Users\FH-UAV-II\AppData\Local\Programs\Python\Python313\python.exe -m pip install -r requirements.txt
```

3. Start the API in a browser:

```powershell
C:\Users\FH-UAV-II\AppData\Local\Programs\Python\Python313\python.exe -m uvicorn pano_namer.main:app --host 127.0.0.1 --port 8000
```

4. Or launch the desktop shell:

```powershell
C:\Users\FH-UAV-II\AppData\Local\Programs\Python\Python313\python.exe -m pano_namer.desktop
```

## Private Login Gate

Production deployments can force all public traffic through a simple signed-cookie login gate. It is disabled unless explicitly enabled, so local development behaves as before by default for everyday work.

Set these environment variables on the server or in the systemd unit before starting `uvicorn pano_namer.main:app --host 127.0.0.1 --port 8000`:

```bash
PANOPRO_AUTH_ENABLED=true
PANOPRO_AUTH_USERNAME=<private username>
PANOPRO_AUTH_PASSWORD=<private password>
PANOPRO_AUTH_SECRET=<long random signing secret>
PANOPRO_SESSION_MAX_AGE_SECONDS=43200
```

When enabled, `/`, `/docs`, `/redoc`, `/openapi.json`, and API routes redirect unauthenticated users to `/login?next=...`. Successful login returns the user to the originally requested path, and `/logout` clears the session cookie. Do not commit real credentials or signing secrets to the repo.

## SQLAdmin backend portal

PANO PRO includes a private backend admin portal mounted at `/admin`. The portal uses SQLAdmin with a small SQLAlchemy compatibility layer that points at the existing SQLite database (`AppConfig.db_path`, usually `.pano_namer_data/pano_namer.db`). The main application data path still uses the existing raw `sqlite3` database system; the SQLAlchemy models are only for admin-managed views.

Install the backend/admin dependencies with the normal project requirements command:

```bash
python -m pip install -r requirements.txt
```

The first admin-managed view is `Users`, backed by the `users` table. User password values are stored as hashes only and are not shown in normal list/detail admin views. These admin-managed users are phase 1 records for future multi-user/database-backed login work. The current production owner login is still controlled by `PANOPRO_AUTH_USERNAME` and `PANOPRO_AUTH_PASSWORD` through the private login gate above; database-backed login will come in a later phase.

When `PANOPRO_AUTH_ENABLED=true`, `/admin` is protected by the same private login gate as the rest of the app and redirects logged-out users to `/login`. Do not add public registration or commit real user credentials.

## SITE-INSIGHT temporary upload pipeline

SITE-INSIGHT is a separate, temporary incubation module inside this repository. It does not replace or rename PANO PRO. When enabled, authenticated users can upload supported 3D/model files, store them in SITE-INSIGHT storage outside the repo, optionally generate a PNG preview with F3D, review/download/delete uploads from `/site-insight/uploads`, and open supported models in an interactive browser viewer.

The routes are disabled by default and are only registered when this environment variable is set:

```bash
SITE_INSIGHT_ENABLED=true
```

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SITE_INSIGHT_ENABLED` | `false` | Enables the private SITE-INSIGHT routes under `/site-insight` and `/api/site-insight`. |
| `SITE_INSIGHT_UPLOAD_DIR` | `/var/lib/site-insight/uploads` | Directory where SITE-INSIGHT upload UUID folders are stored. Keep this outside `/var/www/PANOPRO`. |
| `SITE_INSIGHT_MAX_UPLOAD_MB` | `250` | Maximum accepted upload size in megabytes. |

Supported upload extensions are `.stl`, `.obj`, `.ply`, `.3mf`, `.glb`, `.gltf`, `.fbx`, `.dxf`, `.step`, `.stp`, and `.zip`. Each upload is stored in a UUID folder containing `original.<ext>`, `metadata.json`, and `preview.png` when preview generation succeeds. ZIP packages are safely extracted into the same UUID folder, limited by package file count and extracted size, scanned for blocked executable/script file types, and recorded in metadata with package contents plus the detected primary model and `model_files` list. Public API responses intentionally avoid exposing absolute server paths. Uploads can be deleted from the `/site-insight/uploads` UI; deletion removes the entire stored UUID folder for that SITE-INSIGHT upload from `SITE_INSIGHT_UPLOAD_DIR`.

Textured DJI Terra models usually require uploading the full OBJ package as a ZIP, not just a single PLY or OBJ file. A single ZIP upload can represent one complete Terra tiled model/project: when multiple `.obj` files are present, SITE-INSIGHT records all detected OBJ tiles in `metadata.json` and loads them together by default as one scene. Include every `.obj`, matching or shared `.mtl`, and all referenced `.jpg`/`.png` texture images in the ZIP so the browser viewer can load materials and textures through the protected asset route. PLY is still supported for geometry, but OBJ ZIP packages are recommended for textured Terra models.

F3D is optional and is used only for server-side static preview thumbnails. If `f3d` is not installed, uploads still succeed and metadata records `preview_status=skipped`. If F3D is installed, the app first tries `--rendering-backend=egl` and then falls back to `--rendering-backend=osmesa`; preview failures do not fail uploads.

Interactive browser viewing is available from each upload's `View` link at `/site-insight/uploads/<upload_id>/viewer`. The MVP viewer loads Three.js from a CDN, fetches single-file uploads through the protected `/site-insight/uploads/<upload_id>/raw` route, and fetches ZIP package model/material/texture files through protected `/site-insight/uploads/<upload_id>/asset/<asset_path>` URLs scoped to the same upload UUID. It supports orbit rotation, pan, zoom, basic lighting, camera auto-fit, a tile-set View mode dropdown, tile loading status, and a persisted Orientation dropdown. Multi-OBJ ZIP packages default to **All tiles**, loading every detected OBJ into one root group and fitting the camera to the combined bounding box; **Single tile** remains available for inspecting one OBJ from the package. DJI Terra and survey/photogrammetry models are usually Z-up, with X/Y as the ground plane and Z as elevation, so the browser viewer defaults to Z-up / Survey / Terra orientation and rotates the root model group into Three.js's Y-up scene. If a model appears sideways or vertical, change the Orientation dropdown to Y-up / Three.js or X-up / Experimental; changing orientation immediately refits the camera. Initial interactive support is strongest for `.ply` and `.glb`/`.gltf`; OBJ ZIP packages use Three.js `MTLLoader` + `OBJLoader` so referenced texture images can load from the protected asset route. Other upload formats such as `.step`, `.stp`, `.dxf`, `.fbx`, `.stl`, and `.3mf` remain downloadable and can still have static F3D previews, but the browser viewer shows an unsupported-format message until loaders are added.

Server setup for the default storage location:

```bash
sudo mkdir -p /var/lib/site-insight/uploads
sudo chown -R <service-user>:<service-user> /var/lib/site-insight/uploads
```

If deploying behind Nginx, set `client_max_body_size` to at least the configured `SITE_INSIGHT_MAX_UPLOAD_MB` value, for example:

```nginx
client_max_body_size 250m;
```

Example systemd environment entries:

```ini
Environment=SITE_INSIGHT_ENABLED=true
Environment=SITE_INSIGHT_UPLOAD_DIR=/var/lib/site-insight/uploads
Environment=SITE_INSIGHT_MAX_UPLOAD_MB=250
```

## Notes

- The app now assumes all project geometry uses `EPSG:26912`.
- KML area files are assumed to be standard WGS84 longitude/latitude and are projected into `EPSG:26912` on import.
- Overlay import expects a georeferenced PDF and renders a PNG preview for the map.

## Deploy on DigitalOcean App Platform

This repo includes deploy-friendly defaults for DO buildpacks:

- `.python-version` pins Python to `3.13` (avoids accidental upgrades to unsupported interpreters).
- `requirements.txt` skips Windows-only desktop packages (`PySide6`, `pyinstaller`) on Linux builds.
- `Procfile` defines the web process: `uvicorn pano_namer.main:app`.

If you deploy as a Web Service, use the default `web` process and expose port `${PORT}`.

## Build For Another Computer

Portable build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

That produces:

- `dist\PANO-PRO\`
- `dist\PANO-PRO-v2.7.0-dev-windows.zip`

Windows installer, if Inno Setup 6 is installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -Installer
```

That also produces:

- `dist\installer\PANO-PRO-Setup-2.7.0-dev.exe`

Notes:

- The portable `dist\PANO-PRO` folder can be copied directly to another Windows machine and run as-is.
- The installer script is stored at `installer\PANO-PRO.iss`.
- The PyInstaller spec is stored at `PANO-PRO.spec`.

## Create Next Version Workspace

Create a sibling v2 workspace from the current repo:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_workspace.ps1 -TargetName "PanoPro v2" -Version "2.7.0-dev" -IncludeData
```

What it does:

- creates a sibling folder such as `..\PanoPro v2`
- copies source, tests, scripts, installer files, root docs/config, and `.pano_namer_data`
- excludes `build\`, `dist\`, `.test_tmp\`, `__pycache__\`, and `*.pyc`
- updates the new workspace version markers to the requested version

Notes:

- runtime data is included by default for v2 bootstraps
- use `-NoData` if you want a clean source-only workspace
- use `-Overwrite` to replace an existing target folder
