from __future__ import annotations

from io import BytesIO

from PIL import Image

from pano_namer.services import media
from pano_namer.services.media import ensure_thumbnail, prepare_thumbnail


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
