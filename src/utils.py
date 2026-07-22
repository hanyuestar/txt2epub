"""Image conversion helpers."""

import io
import pathlib

from PIL import Image, ImageOps


def convert_image_to_jpeg(image_path: pathlib.Path) -> bytes:
    """Converts any image format to JPEG and returns it as binary data."""
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image_buffer = io.BytesIO()
        image.save(image_buffer, format="JPEG", quality=90)
        return image_buffer.getvalue()
