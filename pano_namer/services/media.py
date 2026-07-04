from __future__ import annotations

import hashlib
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


def ensure_thumbnail(source_path: Path, cache_dir: Path, photo_id: int, size: tuple[int, int] = (320, 180)) -> tuple[Path, int, int]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = cache_dir / f"photo_{photo_id}.jpg"
    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail(size)
        width, height = image.size
        image.save(thumb_path, format="JPEG", quality=85, optimize=True)
    return thumb_path, width, height
