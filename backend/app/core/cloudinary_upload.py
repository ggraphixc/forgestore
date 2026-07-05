"""Cloudinary configuration and upload helper.

Requires these env vars:
  CLOUDINARY_CLOUD_NAME
  CLOUDINARY_API_KEY
  CLOUDINARY_API_SECRET

Get free credentials at https://cloudinary.com (25GB storage free).
"""
import os
import cloudinary
import cloudinary.uploader
from app.core.image_compressor import compress_image

_configured = False


def _ensure_configured():
    global _configured
    if _configured:
        return
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    api_key = os.getenv("CLOUDINARY_API_KEY", "")
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "")
    if cloud_name and api_key and api_secret:
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )
        _configured = True


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
        return result.get("secure_url")
    except Exception:
        return None
