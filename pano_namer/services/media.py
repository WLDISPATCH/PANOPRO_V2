from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

# Stitched 360 panos (e.g. DJI M4E at 14400x7200 = ~104M pixels) exceed
# Pillow's default ~89.5M-pixel decompression-bomb guard, which crashes
# thumbnail generation. The app only opens local drone imagery the user
# imported, not untrusted downloads, so lift the cap.
Image.MAX_IMAGE_PIXELS = None


def content_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def prepare_thumbnail(
    source_path: Path, size: tuple[int, int] = (320, 180)
) -> tuple[bytes, int, int]:
    with Image.open(source_path) as image:
        image.draft("RGB", (size[0] * 2, size[1] * 2))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail(size)
        width, height = image.size
        output = BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue(), width, height


def ensure_thumbnail(
    source_path: Path,
    cache_dir: Path,
    photo_id: int,
    size: tuple[int, int] = (320, 180),
) -> tuple[Path, int, int]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = cache_dir / f"photo_{photo_id}.jpg"
    data, width, height = prepare_thumbnail(source_path, size)
    thumb_path.write_bytes(data)
    return thumb_path, width, height


def ensure_viewer_image(
    source_path: Path,
    cache_dir: Path,
    photo_id: int,
    max_width: int = 8192,
) -> Path:
    """Return a WebGL-safe viewer copy of a pano, capped at max_width.

    Panos already within the cap are served straight from disk (no copy).
    Oversized panos (14400px M4E output) are downscaled once into the cache
    and reused until the source file changes. 8192px keeps the whole
    equirectangular image inside a single WebGL texture on field-laptop GPUs
    while staying ~4x lighter to download than the 14400px original.
    """
    with Image.open(source_path) as probe:
        width, height = probe.size
    if width <= max_width:
        return source_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"photo_{photo_id}.jpg"
    if cache_path.exists() and cache_path.stat().st_mtime >= source_path.stat().st_mtime:
        return cache_path

    target_height = round(height * max_width / width)
    with Image.open(source_path) as image:
        image.draft("RGB", (max_width, target_height))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail((max_width, target_height))
        image.save(cache_path, format="JPEG", quality=88, optimize=True)
    return cache_path
