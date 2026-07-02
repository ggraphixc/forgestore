"""
Image compression utility.

Compresses uploaded images to a target size range (50-200KB) by
iteratively reducing JPEG quality and, if needed, resizing dimensions.

All images are saved as JPEG (transparent PNGs get a white background).
"""

import io
import logging
from PIL import Image

logger = logging.getLogger("forgestore.compressor")

TARGET_MAX_KB = 200
TARGET_MIN_KB = 50
START_QUALITY = 85
MIN_QUALITY = 10
QUALITY_STEP = 5
RESIZE_FACTOR = 0.75  # reduce dimensions by 25% each resize pass
MAX_DIMENSION = 2048  # cap longest side


def compress_image(raw_bytes: bytes) -> tuple[bytes, str]:
    """Compress *raw_bytes* to the target size range.

    Returns ``(compressed_bytes, file_extension)`` where extension is
    always ``"jpg"`` since the output is JPEG.

    If the image is already under TARGET_MAX_KB it is returned unchanged
    (unless it's PNG/WebP with alpha, in which case it's converted to JPEG).
    """
    if len(raw_bytes) <= TARGET_MAX_KB * 1024:
        try:
            img = Image.open(io.BytesIO(raw_bytes))
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=START_QUALITY)
                return buf.getvalue(), "jpg"
        except Exception:
            pass
        # Already small and no alpha — keep as-is
        return raw_bytes, _guess_ext(raw_bytes)

    img = Image.open(io.BytesIO(raw_bytes))

    # Strip alpha
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "RGBA":
            background.paste(img, mask=img.split()[3])
        else:
            background.paste(img)
        img = background
    elif img.mode == "P":
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Cap dimensions
    if max(img.size) > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    # Iterative quality reduction
    quality = START_QUALITY
    best_buf = None

    while quality >= MIN_QUALITY:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        size_kb = buf.tell() / 1024

        if size_kb <= TARGET_MAX_KB:
            best_buf = buf
            break

        best_buf = buf
        quality -= QUALITY_STEP

    # If still too large, resize and try again
    if best_buf is None or best_buf.tell() / 1024 > TARGET_MAX_KB:
        current_size = max(img.size)
        while current_size > 100:
            new_size = tuple(int(s * RESIZE_FACTOR) for s in img.size)
            resized = img.resize(new_size, Image.LANCZOS)
            current_size = max(new_size)

            quality = START_QUALITY
            while quality >= MIN_QUALITY:
                buf = io.BytesIO()
                resized.save(buf, format="JPEG", quality=quality, optimize=True)
                if buf.tell() / 1024 <= TARGET_MAX_KB:
                    best_buf = buf
                    break
                best_buf = buf
                quality -= QUALITY_STEP

            if best_buf and best_buf.tell() / 1024 <= TARGET_MAX_KB:
                break
            img = resized

    result = best_buf.getvalue() if best_buf else raw_bytes
    final_kb = len(result) / 1024
    logger.info(
        "Compressed image: %.1fKB -> %.1fKB (quality=%d)",
        len(raw_bytes) / 1024,
        final_kb,
        quality,
    )
    return result, "jpg"


def _guess_ext(raw_bytes: bytes) -> str:
    """Guess file extension from magic bytes."""
    if raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw_bytes[:3] == b"GIF":
        return "gif"
    if raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "webp"
    return "jpg"
