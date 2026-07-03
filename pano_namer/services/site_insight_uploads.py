from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status

from pano_namer.services.site_insight_preview import generate_preview

DEFAULT_SITE_INSIGHT_UPLOAD_DIR = Path("/var/lib/site-insight/uploads")
DEFAULT_SITE_INSIGHT_MAX_UPLOAD_MB = 250
ALLOWED_SITE_INSIGHT_EXTENSIONS = {
    ".stl",
    ".obj",
    ".ply",
    ".3mf",
    ".glb",
    ".gltf",
    ".fbx",
    ".dxf",
    ".step",
    ".stp",
    ".zip",
}
SITE_INSIGHT_PACKAGE_MODEL_EXTENSIONS = {".obj", ".ply", ".glb", ".gltf"}
SITE_INSIGHT_PACKAGE_ASSET_EXTENSIONS = {
    ".obj",
    ".mtl",
    ".ply",
    ".glb",
    ".gltf",
    ".bin",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
SITE_INSIGHT_DANGEROUS_PACKAGE_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".hta",
    ".html",
    ".js",
    ".mjs",
    ".php",
    ".ps1",
    ".py",
    ".scr",
    ".sh",
    ".vbs",
}
SITE_INSIGHT_MAX_PACKAGE_FILES = 2000


@dataclass(frozen=True, slots=True)
class SiteInsightSettings:
    enabled: bool
    upload_dir: Path
    max_upload_mb: int

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> "SiteInsightSettings":
        enabled = os.getenv("SITE_INSIGHT_ENABLED", "false").lower() == "true"
        upload_dir = Path(
            os.getenv("SITE_INSIGHT_UPLOAD_DIR", str(DEFAULT_SITE_INSIGHT_UPLOAD_DIR))
        ).expanduser()
        max_upload_mb_raw = os.getenv(
            "SITE_INSIGHT_MAX_UPLOAD_MB", str(DEFAULT_SITE_INSIGHT_MAX_UPLOAD_MB)
        )
        try:
            max_upload_mb = int(max_upload_mb_raw)
        except ValueError:
            max_upload_mb = DEFAULT_SITE_INSIGHT_MAX_UPLOAD_MB
        if max_upload_mb <= 0:
            max_upload_mb = DEFAULT_SITE_INSIGHT_MAX_UPLOAD_MB
        return cls(enabled=enabled, upload_dir=upload_dir, max_upload_mb=max_upload_mb)


def sanitize_filename(filename: str | None) -> str:
    basename = Path((filename or "upload").replace("\\", "/")).name
    sanitized = re.sub(r"[^A-Za-z0-9._ -]+", "_", basename).strip(" .")
    return sanitized or "upload"


def extension_for_filename(filename: str | None) -> str:
    return Path(sanitize_filename(filename)).suffix.lower()


def validate_upload_id(upload_id: str) -> str:
    try:
        return str(UUID(upload_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Upload not found") from exc


def ensure_upload_root(settings: SiteInsightSettings) -> Path:
    root = settings.upload_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload_dir_for(settings: SiteInsightSettings, upload_id: str) -> Path:
    safe_id = validate_upload_id(upload_id)
    root = ensure_upload_root(settings)
    path = (root / safe_id).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=404, detail="Upload not found")
    return path


def metadata_path_for(settings: SiteInsightSettings, upload_id: str) -> Path:
    return upload_dir_for(settings, upload_id) / "metadata.json"


def public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in metadata.items() if not key.startswith("internal_")
    }


def read_metadata(settings: SiteInsightSettings, upload_id: str) -> dict[str, Any]:
    path = metadata_path_for(settings, upload_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Upload not found")
    with path.open("r", encoding="utf-8") as handle:
        return public_metadata(json.load(handle))


def delete_site_insight_upload(
    settings: SiteInsightSettings, upload_id: str
) -> dict[str, Any]:
    upload_dir = upload_dir_for(settings, upload_id)
    if not upload_dir.exists() or not upload_dir.is_dir():
        raise HTTPException(status_code=404, detail="Upload not found")
    shutil.rmtree(upload_dir)
    return {"deleted": True, "upload_id": validate_upload_id(upload_id)}


def list_upload_metadata(settings: SiteInsightSettings) -> list[dict[str, Any]]:
    root = ensure_upload_root(settings)
    records: list[dict[str, Any]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            UUID(child.name)
        except ValueError:
            continue
        metadata_path = child / "metadata.json"
        if not metadata_path.exists():
            continue
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                records.append(public_metadata(json.load(handle)))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(
        records, key=lambda item: str(item.get("uploaded_at", "")), reverse=True
    )


def safe_package_relative_path(name: str) -> Path:
    normalized = name.replace("\\", "/")
    rel = Path(normalized)
    if (
        not normalized.strip()
        or normalized.startswith("/")
        or rel.is_absolute()
        or any(part in ("", ".", "..") for part in rel.parts)
    ):
        raise HTTPException(
            status_code=400, detail="ZIP package contains an unsafe path."
        )
    return rel


def validate_package_member(info: zipfile.ZipInfo) -> Path | None:
    if info.is_dir():
        return None
    rel = safe_package_relative_path(info.filename)
    extension = rel.suffix.lower()
    if extension in SITE_INSIGHT_DANGEROUS_PACKAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="ZIP package contains a blocked executable or script file.",
        )
    if extension not in SITE_INSIGHT_PACKAGE_ASSET_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"ZIP package contains unsupported file type: {extension or 'none'}.",
        )
    return rel


def detect_primary_model(package_files: list[dict[str, Any]]) -> dict[str, Any]:
    model_files = [
        item
        for item in package_files
        if str(item.get("extension", "")).lower()
        in SITE_INSIGHT_PACKAGE_MODEL_EXTENSIONS
    ]
    if not model_files:
        raise HTTPException(
            status_code=400,
            detail="ZIP package must include a supported model file (.obj, .ply, .glb, or .gltf).",
        )
    for preferred in (".obj", ".ply", ".glb", ".gltf"):
        matches = [item for item in model_files if item["extension"] == preferred]
        if matches:
            return sorted(
                matches,
                key=lambda item: (
                    len(str(item["path"]).split("/")),
                    str(item["path"]).lower(),
                ),
            )[0]
    return model_files[0]


def detect_material_file(
    primary_model: dict[str, Any], package_files: list[dict[str, Any]]
) -> dict[str, Any] | None:
    return detect_material_file_for_model(primary_model, package_files)


def detect_material_file_for_model(
    model_file: dict[str, Any], package_files: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if model_file.get("extension") != ".obj":
        return None
    model_path = Path(str(model_file["path"]))
    mtl_files = [item for item in package_files if item.get("extension") == ".mtl"]
    if not mtl_files:
        return None
    same_stem = [
        item
        for item in mtl_files
        if Path(str(item["path"])).with_suffix("").as_posix().lower()
        == model_path.with_suffix("").as_posix().lower()
    ]
    if same_stem:
        return same_stem[0]
    if len(mtl_files) == 1:
        return mtl_files[0]
    same_dir = [
        item
        for item in mtl_files
        if Path(str(item["path"])).parent == model_path.parent
    ]
    return same_dir[0] if same_dir else mtl_files[0]


def detect_model_files(package_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    obj_files = [item for item in package_files if item.get("extension") == ".obj"]
    if obj_files:
        models = sorted(obj_files, key=lambda item: str(item["path"]).lower())
    else:
        primary_model = detect_primary_model(package_files)
        models = [primary_model]
    detected: list[dict[str, Any]] = []
    for model in models:
        material_file = detect_material_file_for_model(model, package_files)
        detected.append(
            {
                **model,
                "material_file": str(material_file["path"])
                if material_file is not None
                else None,
            }
        )
    return detected


def package_asset_url(upload_id: str, asset_path: str) -> str:
    return f"/site-insight/uploads/{upload_id}/asset/{asset_path}"


def asset_path_for(
    settings: SiteInsightSettings,
    upload_id: str,
    asset_path: str,
    metadata: dict[str, Any] | None = None,
) -> Path:
    metadata = metadata or read_metadata(settings, upload_id)
    upload_dir = upload_dir_for(settings, upload_id)
    rel = safe_package_relative_path(asset_path)
    allowed_paths = {
        str(item.get("path")) for item in metadata.get("package_files", [])
    }
    if rel.as_posix() not in allowed_paths:
        raise HTTPException(status_code=404, detail="Asset not found")
    path = (upload_dir / rel).resolve()
    if upload_dir not in path.parents:
        raise HTTPException(status_code=404, detail="Asset not found")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return path


def extract_site_insight_package(
    zip_path: Path, target_dir: Path, settings: SiteInsightSettings
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any] | None,
    list[dict[str, Any]],
]:
    package_files: list[dict[str, Any]] = []
    total_uncompressed = 0
    try:
        with zipfile.ZipFile(zip_path) as package:
            members = [info for info in package.infolist() if not info.is_dir()]
            if len(members) > SITE_INSIGHT_MAX_PACKAGE_FILES:
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP package contains more than {SITE_INSIGHT_MAX_PACKAGE_FILES} files.",
                )
            planned: list[tuple[zipfile.ZipInfo, Path]] = []
            for info in members:
                rel = validate_package_member(info)
                if rel is None:
                    continue
                total_uncompressed += info.file_size
                if total_uncompressed > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Extracted package exceeds SITE-INSIGHT limit of {settings.max_upload_mb} MB.",
                    )
                destination = (target_dir / rel).resolve()
                if target_dir not in destination.parents:
                    raise HTTPException(
                        status_code=400, detail="ZIP package contains an unsafe path."
                    )
                planned.append((info, rel))
                package_files.append(
                    {
                        "path": rel.as_posix(),
                        "extension": rel.suffix.lower(),
                        "size_bytes": info.file_size,
                    }
                )
            model_files = detect_model_files(package_files)
            primary_model = model_files[0]
            material_file = detect_material_file(primary_model, package_files)
            for info, rel in planned:
                destination = target_dir / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
            return (
                sorted(package_files, key=lambda item: item["path"].lower()),
                primary_model,
                material_file,
                model_files,
            )
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=400, detail="Upload is not a valid ZIP package."
        ) from exc


async def save_site_insight_upload(
    upload: UploadFile, settings: SiteInsightSettings
) -> dict[str, Any]:
    original_filename = sanitize_filename(upload.filename)
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_SITE_INSIGHT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="File extension is not allowed for SITE-INSIGHT uploads.",
        )

    root = ensure_upload_root(settings)
    upload_id = str(uuid4())
    target_dir = (root / upload_id).resolve()
    if root not in target_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid upload target.")
    target_dir.mkdir(parents=False, exist_ok=False)

    stored_filename = f"original{extension}"
    original_path = target_dir / stored_filename
    preview_path = target_dir / "preview.png"
    metadata_path = target_dir / "metadata.json"
    sha256 = hashlib.sha256()
    size_bytes = 0

    try:
        with original_path.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Upload exceeds SITE-INSIGHT limit of {settings.max_upload_mb} MB.",
                    )
                sha256.update(chunk)
                output.write(chunk)

        primary_model = {
            "path": stored_filename,
            "extension": extension,
            "url": f"/site-insight/uploads/{upload_id}/raw",
            "size_bytes": size_bytes,
        }
        material_file = None
        model_files: list[dict[str, Any]] = [primary_model]
        package_files: list[dict[str, Any]] = []
        package_type = "single"
        preview_source_path = original_path

        if extension == ".zip":
            (
                package_files,
                primary_model,
                material_file,
                model_files,
            ) = extract_site_insight_package(original_path, target_dir, settings)
            package_type = "zip"
            primary_model = {
                **primary_model,
                "url": package_asset_url(upload_id, str(primary_model["path"])),
                "asset_url": package_asset_url(upload_id, str(primary_model["path"])),
            }
            model_files = [
                {
                    **model_file,
                    "asset_url": package_asset_url(upload_id, str(model_file["path"])),
                }
                for model_file in model_files
            ]
            if material_file is not None:
                material_file = {
                    **material_file,
                    "url": package_asset_url(upload_id, str(material_file["path"])),
                }
            preview_source_path = target_dir / str(primary_model["path"])

        metadata: dict[str, Any] = {
            "upload_id": upload_id,
            "original_filename": original_filename,
            "stored_filename": stored_filename,
            "file_extension": extension,
            "content_type": upload.content_type,
            "size_bytes": size_bytes,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "preview_status": "pending",
            "preview_error": None,
            "sha256": sha256.hexdigest(),
            "download_url": f"/site-insight/uploads/{upload_id}/download",
            "preview_url": f"/site-insight/uploads/{upload_id}/preview.png",
            "package_type": package_type,
            "primary_model": primary_model,
            "model_files": model_files,
            "material_file": material_file,
            "package_files": package_files,
            "package_file_count": len(package_files),
        }

        preview = generate_preview(preview_source_path, preview_path)
        metadata["preview_status"] = preview.status
        metadata["preview_error"] = preview.error

        with metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)

        return public_metadata(metadata)
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    finally:
        await upload.close()
