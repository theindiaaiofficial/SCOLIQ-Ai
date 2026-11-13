from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError


class InvalidFaceImage(ValueError):
    pass


def validate_image_bytes(
    content: bytes,
    *,
    max_bytes: int,
    max_width: int,
    max_height: int,
) -> tuple[str, int, int]:
    if not content:
        raise InvalidFaceImage("Image upload is empty")
    if len(content) > max_bytes:
        raise InvalidFaceImage("Image exceeds the configured upload size limit")
    content_type = None
    width = height = 0
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise InvalidFaceImage("Only JPEG, PNG, and WebP images are accepted")
            width, height = image.size
            content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[image.format]
            if width < 160 or height < 160:
                raise InvalidFaceImage("Image dimensions are too small")
            if width > max_width or height > max_height:
                raise InvalidFaceImage("Image dimensions exceed the configured limit")
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if isinstance(exc, InvalidFaceImage):
            raise
        raise InvalidFaceImage("Upload is not a valid supported image") from exc
    return content_type, width, height
