"""Cloudinary configuration and upload helper.

Requires ONE of:
  CLOUDINARY_URL=cloudinary://key:secret@cloud  (preferred)
  CLOUDINARY_CLOUD_NAME + CLOUDINARY_API_KEY + CLOUDINARY_API_SECRET

Get free credentials at https://cloudinary.com (25GB storage free).
"""
import os
import logging
import cloudinary
import cloudinary.uploader
from app.core.image_compressor import compress_image

logger = logging.getLogger("forgestore.cloudinary")
_configured = False


def _ensure_configured():
    global _configured
    if _configured:
        return

    # Try admin settings first, then CLOUDINARY_URL env var (standard format from Cloudinary dashboard)
    try:
        from app.config import get_settings
        url = get_settings().cloudinary_url
    except Exception:
        url = ""
    if not url:
        url = os.getenv("CLOUDINARY_URL", "")
    if url:
        cloudinary.config(url=url, secure=True)
        _configured = True
        logger.info("Cloudinary configured from CLOUDINARY_URL")
        return

    # Fallback to individual vars
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    if cloud_name and api_key and api_secret:
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )
        _configured = True
        logger.info("Cloudinary configured: cloud=%s", cloud_name)
    else:
        logger.warning("Cloudinary not configured: no CLOUDINARY_URL or CLOUDINARY_CLOUD_NAME/KEY/SECRET")


def is_cloudinary_configured() -> bool:
    _ensure_configured()
    return _configured


def upload_to_cloudinary(file_bytes: bytes, folder: str = "forgestore") -> str | None:
    """Upload compressed image to Cloudinary. Returns URL or None on failure."""
    _ensure_configured()
    if not _configured:
        return None
    try:
        compressed, ext = compress_image(file_bytes)
        result = cloudinary.uploader.upload(
            compressed,
            folder=folder,
            resource_type="image",
            format="jpg",
        )
        url = result.get("secure_url")
        logger.info("Cloudinary upload OK: %s", url)
        return url
    except Exception as e:
        logger.error("Cloudinary upload FAILED: %s", e)
        return None
