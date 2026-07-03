from __future__ import annotations

import json
import mimetypes
from html import escape
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from pano_namer.services.site_insight_uploads import (
    ALLOWED_SITE_INSIGHT_EXTENSIONS,
    asset_path_for,
    delete_site_insight_upload,
    SiteInsightSettings,
    list_upload_metadata,
    read_metadata,
    save_site_insight_upload,
    upload_dir_for,
)


def register_site_insight_routes(app: FastAPI, settings: SiteInsightSettings) -> None:
    if not settings.enabled:
        return

    app.state.site_insight_settings = settings

    @app.get("/site-insight", include_in_schema=False)
    def site_insight_landing() -> RedirectResponse:
        return RedirectResponse("/site-insight/uploads", status_code=303)

    @app.get("/site-insight/uploads", include_in_schema=False)
    def site_insight_uploads_page() -> HTMLResponse:
        return HTMLResponse(render_upload_page(settings))

    @app.post("/api/site-insight/uploads")
    async def create_site_insight_upload(file: UploadFile = File(...)) -> dict:
        return await save_site_insight_upload(file, settings)

    @app.get("/api/site-insight/uploads")
    def list_site_insight_uploads() -> list[dict]:
        return list_upload_metadata(settings)

    @app.get("/api/site-insight/uploads/{upload_id}")
    def get_site_insight_upload(upload_id: str) -> dict:
        return read_metadata(settings, upload_id)

    @app.delete("/api/site-insight/uploads/{upload_id}")
    def delete_site_insight_upload_route(upload_id: str) -> dict:
        return delete_site_insight_upload(settings, upload_id)

    @app.get("/site-insight/uploads/{upload_id}/preview.png", include_in_schema=False)
    def site_insight_preview(upload_id: str) -> FileResponse:
        upload_dir = upload_dir_for(settings, upload_id)
        preview_path = upload_dir / "preview.png"
        if not preview_path.exists():
            raise HTTPException(status_code=404, detail="Preview not found")
        return FileResponse(
            preview_path, media_type="image/png", filename="preview.png"
        )

    @app.get("/site-insight/uploads/{upload_id}/viewer", include_in_schema=False)
    def site_insight_viewer(upload_id: str) -> HTMLResponse:
        metadata = read_metadata(settings, upload_id)
        model_path = viewer_model_path(settings, upload_id, metadata)
        if not model_path.exists():
            raise HTTPException(status_code=404, detail="Upload not found")
        return HTMLResponse(render_viewer_page(metadata))

    @app.get("/site-insight/uploads/{upload_id}/raw", include_in_schema=False)
    def site_insight_raw_model(upload_id: str) -> FileResponse:
        metadata = read_metadata(settings, upload_id)
        model_path = viewer_model_path(settings, upload_id, metadata)
        if not model_path.exists():
            raise HTTPException(status_code=404, detail="Upload not found")
        media_type, _ = mimetypes.guess_type(model_path.name)
        return FileResponse(
            model_path,
            media_type=media_type
            or metadata.get("content_type")
            or "application/octet-stream",
        )

    @app.get("/site-insight/uploads/{upload_id}/download", include_in_schema=False)
    def site_insight_download(upload_id: str) -> FileResponse:
        metadata = read_metadata(settings, upload_id)
        original_path = original_model_path(settings, upload_id, metadata)
        if not original_path.exists():
            raise HTTPException(status_code=404, detail="Upload not found")
        return FileResponse(
            original_path,
            filename=Path(str(metadata["original_filename"])).name,
            media_type=metadata.get("content_type") or "application/octet-stream",
        )

    @app.get(
        "/site-insight/uploads/{upload_id}/asset/{asset_path:path}",
        include_in_schema=False,
    )
    def site_insight_upload_asset(upload_id: str, asset_path: str) -> FileResponse:
        metadata = read_metadata(settings, upload_id)
        path = asset_path_for(settings, upload_id, asset_path, metadata)
        media_type, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=media_type or "application/octet-stream")


def original_model_path(
    settings: SiteInsightSettings, upload_id: str, metadata: dict
) -> Path:
    stored_filename = Path(str(metadata["stored_filename"])).name
    return upload_dir_for(settings, upload_id) / stored_filename


def viewer_model_path(
    settings: SiteInsightSettings, upload_id: str, metadata: dict
) -> Path:
    primary_model = metadata.get("primary_model") or {}
    if metadata.get("package_type") == "zip" and primary_model.get("path"):
        return asset_path_for(settings, upload_id, str(primary_model["path"]), metadata)
    return original_model_path(settings, upload_id, metadata)


def render_viewer_page(metadata: dict) -> str:
    upload_id = str(metadata["upload_id"])
    original_filename = Path(str(metadata["original_filename"])).name
    primary_model = metadata.get("primary_model") or {}
    material_file = metadata.get("material_file") or None
    model_files = metadata.get("model_files") or [primary_model]
    tile_count = len(
        [item for item in model_files if str(item.get("extension", "")).lower() == ".obj"]
    )
    package_mode = (
        "Complete tile set"
        if metadata.get("package_type") == "zip" and tile_count > 1
        else "Single model"
    )
    file_extension = str(
        primary_model.get("extension")
        or metadata.get("file_extension")
        or Path(original_filename).suffix
    ).lower()
    size_bytes = int(metadata.get("size_bytes") or 0)
    preview_status = str(metadata.get("preview_status") or "unknown")
    raw_url = f"/site-insight/uploads/{upload_id}/raw"
    download_url = f"/site-insight/uploads/{upload_id}/download"
    model_url = str(primary_model.get("url") or raw_url)
    primary_asset_path = str(
        primary_model.get("path") or metadata.get("stored_filename") or ""
    )
    asset_base_url = f"/site-insight/uploads/{upload_id}/asset/"
    viewer_config = json.dumps(
        {
            "filename": original_filename,
            "extension": file_extension,
            "rawUrl": raw_url,
            "modelUrl": model_url,
            "downloadUrl": download_url,
            "previewStatus": preview_status,
            "sizeBytes": size_bytes,
            "packageType": metadata.get("package_type") or "single",
            "assetBaseUrl": asset_base_url,
            "primaryAssetPath": primary_asset_path,
            "materialUrl": (
                material_file.get("url") if isinstance(material_file, dict) else None
            ),
            "materialPath": (
                material_file.get("path") if isinstance(material_file, dict) else None
            ),
            "modelFiles": model_files,
            "tileCount": tile_count,
            "packageMode": package_mode,
            "defaultViewMode": "all" if tile_count > 1 else "single",
            "packageFiles": metadata.get("package_files") or [],
            "defaultOrientation": "z-up",
        }
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SITE-INSIGHT Model Viewer</title>
  <style>
    body {{ background: #0f172a; color: #e5edf8; font-family: Arial, sans-serif; margin: 0; }}
    header {{ align-items: flex-start; background: #111827; border-bottom: 1px solid #243044; display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; padding: 18px 22px; }}
    h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
    .meta {{ color: #a7b4c7; display: flex; flex-wrap: wrap; gap: 12px; font-size: 0.93rem; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .viewer-controls {{ align-items: center; background: #0f172a; border-bottom: 1px solid #243044; display: flex; flex-wrap: wrap; gap: 10px 14px; padding: 10px 22px; }}
    .viewer-controls label {{ color: #dbeafe; font-weight: 700; }}
    .viewer-controls select {{ background: #111827; border: 1px solid #475569; border-radius: 8px; color: #e5edf8; padding: 7px 10px; }}
    .package-panel {{ background: #0b1120; border-bottom: 1px solid #243044; color: #cbd5e1; padding: 10px 22px; }}
    .package-panel summary {{ cursor: pointer; font-weight: 700; }}
    .tile-list {{ display: grid; gap: 4px; margin-top: 8px; max-height: 110px; overflow: auto; }}
    .tile-status {{ color: #93c5fd; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.84rem; }}
    .orientation-note {{ color: #a7b4c7; font-size: 0.9rem; }}
    a.button {{ background: #2563eb; border-radius: 8px; color: white; font-weight: 700; padding: 9px 12px; text-decoration: none; }}
    a.secondary {{ background: #334155; }}
    #viewer {{ background: #050816; height: calc(100vh - 158px); min-height: 460px; position: relative; width: 100%; }}
    #message {{ background: rgba(15,23,42,.86); border: 1px solid #334155; border-radius: 12px; left: 50%; max-width: 720px; padding: 16px 18px; position: absolute; text-align: center; top: 50%; transform: translate(-50%, -50%); z-index: 2; }}
    #message.error {{ border-color: #ef4444; color: #fecaca; }}
    canvas {{ display: block; }}
  </style>
</head>
<body>
<header>
  <div>
    <h1>SITE-INSIGHT Model Viewer</h1>
    <div class="meta">
      <span><strong>File:</strong> {escape(original_filename)}</span>
      <span><strong>Primary model:</strong> {escape(primary_asset_path or original_filename)}</span>
      <span><strong>Detected tiles:</strong> {tile_count}</span>
      <span><strong>Preview:</strong> {escape(preview_status)}</span>
      <span><strong>Size:</strong> <span id="size"></span></span>
    </div>
  </div>
  <nav class="actions" aria-label="Viewer actions">
    <a class="button secondary" href="/site-insight/uploads">Back to uploads</a>
    <a class="button" href="{escape(download_url)}">Download original</a>
  </nav>
</header>
<section class="viewer-controls" aria-label="Model orientation controls">
  <label for="view-mode">View mode</label>
  <select id="view-mode" name="view-mode">
    <option value="all" selected>All tiles</option>
    <option value="single">Single tile</option>
  </select>
  <label for="single-tile">Tile</label>
  <select id="single-tile" name="single-tile"></select>
  <label for="orientation">Orientation</label>
  <select id="orientation" name="orientation">
    <option value="z-up" selected>Z-up / Survey / Terra</option>
    <option value="y-up">Y-up / Three.js</option>
    <option value="x-up">X-up / Experimental</option>
  </select>
  <span class="orientation-note">If your model appears vertical, switch orientation.</span>
</section>
<section class="package-panel" aria-label="Package tile summary">
  <div><strong>Package mode:</strong> {escape(package_mode)} · <strong>Detected model tiles:</strong> {tile_count}</div>
  <details open>
    <summary>Tile loading status</summary>
    <div id="tile-list" class="tile-list"></div>
  </details>
</section>
<main id="viewer">
  <div id="message">Loading model…</div>
</main>
<script type="importmap">{{"imports":{{"three":"https://cdn.jsdelivr.net/npm/three@0.165.0/build/three.module.js"}}}}</script>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'https://cdn.jsdelivr.net/npm/three@0.165.0/examples/jsm/controls/OrbitControls.js';
import {{ PLYLoader }} from 'https://cdn.jsdelivr.net/npm/three@0.165.0/examples/jsm/loaders/PLYLoader.js';
import {{ GLTFLoader }} from 'https://cdn.jsdelivr.net/npm/three@0.165.0/examples/jsm/loaders/GLTFLoader.js';
import {{ OBJLoader }} from 'https://cdn.jsdelivr.net/npm/three@0.165.0/examples/jsm/loaders/OBJLoader.js';
import {{ MTLLoader }} from 'https://cdn.jsdelivr.net/npm/three@0.165.0/examples/jsm/loaders/MTLLoader.js';

const config = {viewer_config};
const supported = new Set(['.ply', '.glb', '.gltf', '.obj']);
const viewer = document.getElementById('viewer');
const message = document.getElementById('message');
const orientationSelect = document.getElementById('orientation');
const viewModeSelect = document.getElementById('view-mode');
const singleTileSelect = document.getElementById('single-tile');
const tileList = document.getElementById('tile-list');
const orientationStorageKey = 'siteInsight.viewer.orientation';
const orientations = new Set(['z-up', 'y-up', 'x-up']);
const savedOrientation = localStorage.getItem(orientationStorageKey);
const initialOrientation = orientations.has(savedOrientation) ? savedOrientation : (config.defaultOrientation || 'z-up');
orientationSelect.value = orientations.has(initialOrientation) ? initialOrientation : 'z-up';
document.getElementById('size').textContent = fmtBytes(config.sizeBytes);
const modelFiles = Array.isArray(config.modelFiles) && config.modelFiles.length ? config.modelFiles : [{{ path: config.primaryAssetPath, extension: config.extension, asset_url: config.modelUrl, material_file: config.materialPath }}];
viewModeSelect.value = config.defaultViewMode === 'all' ? 'all' : 'single';
if (modelFiles.length <= 1) viewModeSelect.value = 'single';
singleTileSelect.innerHTML = modelFiles.map((file, idx) => `<option value="${{idx}}">${{escapeHtml(file.path || file.asset_url || `Tile ${{idx + 1}}`)}}</option>`).join('');
singleTileSelect.disabled = viewModeSelect.value === 'all';
renderTileList(new Map());

function fmtBytes(bytes) {{
  if (!bytes) return '0 B';
  const units = ['B','KB','MB','GB'];
  let size = Number(bytes); let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {{ size /= 1024; idx++; }}
  return `${{size.toFixed(idx ? 1 : 0)}} ${{units[idx]}}`;
}}
function showError(text) {{ message.textContent = text; message.classList.add('error'); message.style.display = 'block'; }}
function showStatus(text) {{ message.textContent = text; message.classList.remove('error'); message.style.display = 'block'; }}
function hideStatus() {{ message.style.display = 'none'; }}
function escapeHtml(value) {{ return String(value ?? '').replace(/[&<>\"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c])); }}
function renderTileList(statuses) {{
  tileList.innerHTML = modelFiles.map((file, idx) => `<div class="tile-status">${{escapeHtml(statuses.get(idx) || 'pending')}} — ${{escapeHtml(file.path || file.asset_url || `Tile ${{idx + 1}}`)}}</div>`).join('') || '<div class="tile-status">No package model files detected.</div>';
}}

if (!supported.has(config.extension)) {{
  showError(`Interactive viewing is not available yet for ${{config.extension || 'this file type'}}. Supported MVP formats: .ply, .glb, .gltf, .obj. Use Download original for this upload.`);
}} else {{
  initViewer().catch(error => showError(error.message || 'Unable to load model.'));
}}

async function initViewer() {{
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x050816);
  const camera = new THREE.PerspectiveCamera(60, viewer.clientWidth / viewer.clientHeight, 0.01, 100000);
  camera.position.set(3, 3, 3);

  const renderer = new THREE.WebGLRenderer({{ antialias: true }});
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.setSize(viewer.clientWidth, viewer.clientHeight);
  viewer.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x334155, 2.0));
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
  keyLight.position.set(8, 10, 6);
  scene.add(keyLight);
  const grid = new THREE.GridHelper(20, 20, 0x475569, 0x1e293b);
  scene.add(grid);

  const modelRoot = new THREE.Group();
  modelRoot.name = 'site-insight-oriented-model-root';
  applyOrientation(modelRoot, orientationSelect.value);
  scene.add(modelRoot);

  async function reloadModel() {{
    showStatus(viewModeSelect.value === 'all' ? `Loading ${{modelFiles.length}} model tiles…` : 'Loading selected tile…');
    modelRoot.clear();
    const loadedObject = await loadObject(config);
    modelRoot.add(loadedObject);
    applyOrientation(modelRoot, orientationSelect.value);
    fitCameraToObject(camera, controls, modelRoot);
    hideStatus();
  }}

  await reloadModel();

  viewModeSelect.addEventListener('change', () => {{
    singleTileSelect.disabled = viewModeSelect.value === 'all';
    reloadModel().catch(error => showError(error.message || 'Unable to load model.'));
  }});
  singleTileSelect.addEventListener('change', () => {{
    if (viewModeSelect.value === 'single') reloadModel().catch(error => showError(error.message || 'Unable to load model.'));
  }});

  orientationSelect.addEventListener('change', () => {{
    const orientation = orientationSelect.value;
    localStorage.setItem(orientationStorageKey, orientation);
    applyOrientation(modelRoot, orientation);
    fitCameraToObject(camera, controls, modelRoot);
  }});

  window.addEventListener('resize', () => {{
    camera.aspect = viewer.clientWidth / viewer.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(viewer.clientWidth, viewer.clientHeight);
  }});

  function animate() {{
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }}
  animate();
}}

async function loadObject(config) {{
  const extension = config.extension;
  const url = config.modelUrl || config.rawUrl;
  if (config.packageType === 'zip' && extension === '.obj' && viewModeSelect.value === 'all' && modelFiles.length > 1) {{
    return loadObjTileSet(modelFiles);
  }}
  return new Promise((resolve, reject) => {{
    if (extension === '.ply') {{
      new PLYLoader().load(url, geometry => {{
        geometry.computeBoundingSphere();
        if (!geometry.attributes.normal) geometry.computeVertexNormals();
        const material = new THREE.MeshStandardMaterial({{ color: 0xdbeafe, roughness: 0.65, metalness: 0.05, vertexColors: Boolean(geometry.attributes.color), side: THREE.DoubleSide }});
        resolve(new THREE.Mesh(geometry, material));
      }}, undefined, reject);
    }} else if (extension === '.glb' || extension === '.gltf') {{
      new GLTFLoader().load(url, gltf => resolve(gltf.scene), undefined, reject);
    }} else if (extension === '.obj') {{
      const idx = Math.max(0, Math.min(modelFiles.length - 1, Number(singleTileSelect.value || 0)));
      loadObj(modelFiles[idx] || config, resolve, reject);
    }} else {{
      reject(new Error('Unsupported model type.'));
    }}
  }});
}}

function assetDirectory(path) {{
  const idx = String(path || '').lastIndexOf('/');
  return idx >= 0 ? String(path).slice(0, idx + 1) : '';
}}

function applyOrientation(root, orientation) {{
  if (orientation === 'z-up') {{
    root.rotation.set(-Math.PI / 2, 0, 0);
  }} else if (orientation === 'x-up') {{
    // Experimental: rotate source X-up data so +X maps into Three.js +Y.
    root.rotation.set(0, 0, Math.PI / 2);
  }} else {{
    root.rotation.set(0, 0, 0);
  }}
  root.updateMatrixWorld(true);
}}

function modelAssetPath(model) {{ return String(model.path || model.primaryAssetPath || config.primaryAssetPath || ''); }}
function modelMaterialPath(model) {{ return String(model.material_file || model.materialPath || config.materialPath || ''); }}

async function loadObjTileSet(files) {{
  const group = new THREE.Group();
  group.name = 'site-insight-complete-tile-set';
  const statuses = new Map(files.map((_, idx) => [idx, 'pending']));
  renderTileList(statuses);
  await Promise.all(files.map((file, idx) => new Promise((resolve, reject) => {{
    statuses.set(idx, 'loading');
    renderTileList(statuses);
    loadObj(file, object => {{
      object.name = file.path || `tile-${{idx + 1}}`;
      group.add(object);
      statuses.set(idx, 'loaded');
      renderTileList(statuses);
      resolve(object);
    }}, error => {{
      statuses.set(idx, 'failed');
      renderTileList(statuses);
      reject(error);
    }});
  }})));
  return group;
}}

function loadObj(model, resolve, reject) {{
  const objLoader = new OBJLoader();
  const assetPath = modelAssetPath(model);
  if (config.packageType === 'zip') {{
    const objDir = assetDirectory(assetPath);
    objLoader.setPath(config.assetBaseUrl + objDir);
  }}
  const objName = config.packageType === 'zip' ? String(assetPath || '').split('/').pop() : (config.modelUrl || config.rawUrl);
  const materialPath = modelMaterialPath(model);
  if (materialPath && config.packageType === 'zip') {{
    const mtlDir = assetDirectory(materialPath);
    const mtlName = String(materialPath).split('/').pop();
    const mtlLoader = new MTLLoader();
    mtlLoader.setPath(config.assetBaseUrl + mtlDir);
    mtlLoader.setResourcePath(config.assetBaseUrl + mtlDir);
    mtlLoader.load(mtlName, materials => {{
      materials.preload();
      objLoader.setMaterials(materials);
      objLoader.load(objName, resolve, undefined, reject);
    }}, undefined, () => objLoader.load(objName, resolve, undefined, reject));
  }} else {{
    objLoader.load(config.packageType === 'zip' ? objName : (config.modelUrl || config.rawUrl), resolve, undefined, reject);
  }}
}}

function fitCameraToObject(camera, controls, object) {{
  object.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  const distance = maxDim / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
  const direction = new THREE.Vector3(1, 0.75, 1).normalize();
  camera.near = Math.max(distance / 1000, 0.01);
  camera.far = Math.max(distance * 1000, 1000);
  camera.position.copy(center).add(direction.multiplyScalar(distance * 1.8));
  camera.lookAt(center);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}}
</script>
</body>
</html>"""


def render_upload_page(settings: SiteInsightSettings) -> str:
    allowed = ", ".join(sorted(ALLOWED_SITE_INSIGHT_EXTENSIONS))
    max_mb = settings.max_upload_mb
    escaped_allowed = escape(allowed)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>SITE-INSIGHT File Uploads</title>
  <style>
    body {{ background: #f6f8fb; color: #172033; font-family: Arial, sans-serif; margin: 0; }}
    main {{ margin: 0 auto; max-width: 1100px; padding: 32px 20px; }}
    h1 {{ margin-bottom: 8px; }}
    .card {{ background: #fff; border: 1px solid #d9e1ec; border-radius: 14px; box-shadow: 0 8px 24px rgba(23,32,51,.06); margin: 18px 0; padding: 20px; }}
    .note {{ color: #55657e; font-size: 0.95rem; }}
    form {{ align-items: center; display: flex; flex-wrap: wrap; gap: 12px; }}
    button {{ background: #1d4ed8; border: 0; border-radius: 8px; color: white; cursor: pointer; font-weight: 700; padding: 10px 14px; }}
    button:disabled {{ background: #8aa4d6; cursor: wait; }}
    .danger {{ background: #b91c1c; margin-left: 8px; }}
    .danger:disabled {{ background: #dca5a5; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #e4e9f2; padding: 10px; text-align: left; vertical-align: middle; }}
    th {{ color: #44536b; font-size: 0.82rem; text-transform: uppercase; }}
    img {{ background: #eef2f7; border-radius: 8px; max-height: 88px; max-width: 130px; object-fit: contain; }}
    .status {{ border-radius: 999px; display: inline-block; font-size: 0.82rem; padding: 4px 8px; }}
    .succeeded {{ background: #dcfce7; color: #166534; }}
    .failed {{ background: #fee2e2; color: #991b1b; }}
    .skipped {{ background: #fef3c7; color: #92400e; }}
    .pending {{ background: #e0e7ff; color: #3730a3; }}
  </style>
</head>
<body>
<main>
  <h1>SITE-INSIGHT File Uploads</h1>
  <p class=\"note\">Temporary private SITE-INSIGHT upload pipeline inside PANO PRO. Uploads are stored in SITE-INSIGHT storage outside the repo.</p>
  <section class=\"card\">
    <form id=\"upload-form\">
      <input id=\"file\" name=\"file\" type=\"file\" required />
      <button id=\"upload-button\" type=\"submit\">Upload file</button>
    </form>
    <p class=\"note\">Allowed file types: {escaped_allowed}</p>
    <p class=\"note\">For textured DJI Terra output, upload the full ZIP package with the OBJ, MTL, and texture images rather than a single model file.</p>
    <p class=\"note\">Maximum upload size: {max_mb} MB. Nginx must allow at least this size with <code>client_max_body_size</code>.</p>
    <p id=\"message\" class=\"note\"></p>
  </section>
  <section class=\"card\">
    <h2>Uploaded files</h2>
    <div id=\"uploads\">Loading uploads…</div>
  </section>
</main>
<script>
const uploadsEl = document.getElementById('uploads');
const messageEl = document.getElementById('message');
const button = document.getElementById('upload-button');
function fmtBytes(bytes) {{
  if (!bytes) return '0 B';
  const units = ['B','KB','MB','GB'];
  let size = Number(bytes); let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {{ size /= 1024; idx++; }}
  return `${{size.toFixed(idx ? 1 : 0)}} ${{units[idx]}}`;
}}
function esc(value) {{ return String(value ?? '').replace(/[&<>\"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c])); }}
function packageSummary(item) {{
  const count = Number(item.package_file_count || 0);
  if (!count) return '—';
  const objTiles = (item.model_files || []).filter(file => file.extension === '.obj').length;
  const tileSummary = objTiles > 1 ? `<div><strong>OBJ tile set: ${{objTiles}} tiles</strong></div>` : '';
  const names = (item.package_files || []).slice(0, 5).map(file => esc(file.path)).join('<br>');
  return `${{tileSummary}}<details><summary>${{count}} file${{count === 1 ? '' : 's'}}</summary>${{names}}${{count > 5 ? '<br>…' : ''}}</details>`;
}}
async function loadUploads() {{
  const res = await fetch('/api/site-insight/uploads');
  if (!res.ok) {{ uploadsEl.textContent = 'Unable to load uploads.'; return; }}
  const uploads = await res.json();
  if (!uploads.length) {{ uploadsEl.textContent = 'No SITE-INSIGHT files uploaded yet.'; return; }}
  uploadsEl.innerHTML = `<table><thead><tr><th>Preview</th><th>File</th><th>Primary model</th><th>Package contents</th><th>Type</th><th>Uploaded</th><th>Size</th><th>Preview status</th><th>Actions</th></tr></thead><tbody>${{uploads.map(item => `
    <tr>
      <td>${{item.preview_status === 'succeeded' ? `<img src="${{item.preview_url}}" alt="Preview for ${{esc(item.original_filename)}}">` : '—'}}</td>
      <td>${{esc(item.original_filename)}}</td>
      <td>${{esc(item.primary_model?.path || item.stored_filename || '—')}}</td>
      <td>${{packageSummary(item)}}</td>
      <td>${{esc(item.file_extension)}} / ${{esc(item.content_type || 'unknown')}}</td>
      <td>${{esc(item.uploaded_at)}}</td>
      <td>${{fmtBytes(item.size_bytes)}}</td>
      <td><span class="status ${{esc(item.preview_status)}}">${{esc(item.preview_status)}}</span></td>
      <td><a href="/site-insight/uploads/${{encodeURIComponent(item.upload_id)}}/viewer">View</a> · <a href="${{item.download_url}}">Download</a> <button class="danger delete-upload" type="button" data-upload-id="${{esc(item.upload_id)}}">Delete</button></td>
    </tr>`).join('')}}</tbody></table>`;
}}
uploadsEl.addEventListener('click', async event => {{
  const deleteButton = event.target.closest('.delete-upload');
  if (!deleteButton) return;
  const uploadId = deleteButton.dataset.uploadId;
  if (!uploadId) return;
  if (!confirm('Delete this SITE-INSIGHT upload? This cannot be undone.')) return;
  deleteButton.disabled = true; messageEl.textContent = 'Deleting upload…';
  try {{
    const res = await fetch(`/api/site-insight/uploads/${{encodeURIComponent(uploadId)}}`, {{ method: 'DELETE' }});
    if (!res.ok) {{ const err = await res.json().catch(() => ({{detail: 'Delete failed.'}})); throw new Error(err.detail || 'Delete failed.'); }}
    messageEl.textContent = 'Upload deleted.'; await loadUploads();
  }} catch (error) {{
    messageEl.textContent = error.message || 'Delete failed.';
    deleteButton.disabled = false;
  }}
}});
document.getElementById('upload-form').addEventListener('submit', async event => {{
  event.preventDefault();
  const fileInput = document.getElementById('file');
  if (!fileInput.files.length) return;
  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  button.disabled = true; messageEl.textContent = 'Uploading…';
  try {{
    const res = await fetch('/api/site-insight/uploads', {{ method: 'POST', body: formData }});
    if (!res.ok) {{ const err = await res.json().catch(() => ({{detail: 'Upload failed.'}})); throw new Error(err.detail || 'Upload failed.'); }}
    fileInput.value = ''; messageEl.textContent = 'Upload complete.'; await loadUploads();
  }} catch (error) {{ messageEl.textContent = error.message; }}
  finally {{ button.disabled = false; }}
}});
loadUploads();
</script>
</body>
</html>"""
