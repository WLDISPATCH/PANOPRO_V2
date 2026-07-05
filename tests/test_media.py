from __future__ import annotations

from io import BytesIO

from PIL import Image

from pano_namer.services import media
from pano_namer.services.media import (
    ensure_thumbnail,
    ensure_viewer_image,
    prepare_thumbnail,
)


def test_decompression_bomb_guard_is_lifted():
    # Stitched M4E panos are ~104M pixels; Pillow's default ~89.5M cap must
    # not apply once the media service is imported (see GitHub issue #7).
    assert media.Image.MAX_IMAGE_PIXELS is None


def test_thumbnail_for_pano_sized_image(tmp_path):
    # A 2:1 pano aspect at reduced scale still exercises the thumbnail path.
    source = tmp_path / "pano.jpg"
    Image.new("RGB", (1440, 720), color=(30, 60, 90)).save(source, "JPEG")
    thumb_path, width, height = ensure_thumbnail(source, tmp_path / "cache", 1)
    assert thumb_path.exists()
    assert (width, height) == (320, 160)


def test_prepare_thumbnail_returns_jpeg_bytes(tmp_path):
    source = tmp_path / "pano.jpg"
    Image.new("RGB", (1440, 720), color=(30, 60, 90)).save(source, "JPEG")

    data, width, height = prepare_thumbnail(source)

    assert (width, height) == (320, 160)
    with Image.open(BytesIO(data)) as image:
        assert image.format == "JPEG"
        assert image.size == (320, 160)


def test_viewer_image_serves_small_pano_from_source(tmp_path):
    # A pano already within the cap is served straight from disk (no copy).
    source = tmp_path / "small.jpg"
    Image.new("RGB", (4096, 2048), color=(10, 20, 30)).save(source, "JPEG")
    result = ensure_viewer_image(source, tmp_path / "cache", 1)
    assert result == source


def test_viewer_image_downscales_oversized_pano(tmp_path):
    # An M4E-sized pano is downscaled once into the cache, keeping 2:1.
    source = tmp_path / "big.jpg"
    Image.new("RGB", (14400, 7200), color=(10, 20, 30)).save(source, "JPEG")
    result = ensure_viewer_image(source, tmp_path / "cache", 7)
    assert result != source
    with Image.open(result) as image:
        assert image.width == 8192
        assert image.height == 4096
    # Second call reuses the cache file (same path, not regenerated).
    again = ensure_viewer_image(source, tmp_path / "cache", 7)
    assert again == result
