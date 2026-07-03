# PanoPro Repo Expert Prompt

Use this context when asking an agent to work in the PANO PRO / PanoPro repository.

## Branding
- The product is **PANO PRO** in prominent app titles, installer-facing names, and primary UI headings.
- Use **PanoPro** in normal prose, docs, developer references, and product identity text.
- Use **PANOPRO** only for established repo, server, or environment naming such as `PANOPRO_AUTH_*`.
- Legacy Joe-based product names are incorrect branding and should not be reintroduced.

## Product direction
PanoPro is a private industrial pano/photo management, review, inspection, and reporting platform. It began as a DJI aerial 360 photo import/rename workflow using date/location metadata and DXF/KML boundaries, but it should not be narrowed back to only a file renamer.

Preserve the core product concepts during changes:
- DJI pano/photo import
- DXF/KML area matching
- map review
- reliable safe rename workflow
- archive folders and collections
- synchronized map/list/viewer behavior
- 360 viewer direction and hotspots
- notes, issues, and annotations
- tags and metadata filtering
- duplicate review and thumbnails
- report exports and audit history
- weekly auto-collections
- auth gate behavior
- production FastAPI/Uvicorn deployment

## Internal identifiers to preserve
Do not rename these without a deliberate migration plan because they are internal compatibility points:
- Python package/import path `pano_namer`
- local data folder `.pano_namer_data`
- database file `pano_namer.db`
- existing API route names and table names
- existing environment variables such as `PANOPRO_AUTH_*`
- production deployment entry point `pano_namer.main:app`
