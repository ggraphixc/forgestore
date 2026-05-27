"""
Shared utility functions for ForgeStore.

Provides a timezone-aware alternative to deprecated ``datetime.utcnow()``.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    Replaces deprecated ``datetime.utcnow()`` throughout the project.
    """
    return datetime.now(timezone.utc)
