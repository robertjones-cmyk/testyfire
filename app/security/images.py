"""Image intake safety.

Bytes that arrive from a camera are untrusted. Before anything is stored we:

1. verify the magic bytes really are JPEG or PNG;
2. decode with Pillow under a pixel cap (decompression-bomb guard);
3. re-encode to JPEG, which drops EXIF/metadata and any trailing payload
   smuggled after the image data.
"""
from __future__ import annotations

import io

from PIL import Image

# ~40 MP. A 1920x1080 snapshot is 2 MP, so this is generous but bounded.
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class UnsafeImage(Exception):
    """Raised when bytes are not a usable, safe image."""


def sniff_image_type(data: bytes) -> str:
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    if data.startswith(PNG_MAGIC):
        return "png"
    raise UnsafeImage("not a JPEG or PNG (magic bytes did not match)")


def normalise_to_jpeg(data: bytes, *, quality: int = 85, max_side: int = 2560) -> tuple[bytes, tuple[int, int]]:
    """Validate, decode and re-encode ``data`` as a clean JPEG.

    Returns ``(jpeg_bytes, (width, height))``. Raises :class:`UnsafeImage`.
    """
    sniff_image_type(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()  # structural check; consumes the file object
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > MAX_PIXELS:
                raise UnsafeImage(f"image too large: {img.width}x{img.height}")
            img = img.convert("RGB")
            if max(img.size) > max_side:
                ratio = max_side / max(img.size)
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
            size = img.size
            out = io.BytesIO()
            # No exif= argument -> metadata is not carried over.
            img.save(out, format="JPEG", quality=quality, optimize=True)
    except UnsafeImage:
        raise
    except Exception as exc:  # Pillow raises a wide range of errors on bad input
        raise UnsafeImage(f"could not decode image: {exc}") from exc
    return out.getvalue(), size
