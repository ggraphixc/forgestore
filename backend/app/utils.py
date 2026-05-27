"""
Shared utility functions for ForgeStore.

Provides a timezone-aware alternative to deprecated ``datetime.utcnow()``.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    Replaces deprecated ``datetime.utcnow()`` throughout the project.
    The returned value is naive (no tzinfo) so it remains compatible
    with SQLAlchemy ``DateTime`` columns, which store naive UTC.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
