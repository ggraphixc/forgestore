"""
Database engine and session management.

Engine and SessionLocal are lazily initialized on first access to prevent
import-time crashes (e.g. when the database isn't reachable yet or when
environment variables aren't loaded).

The module-level __getattr__ (PEP 562) provides backward compatibility for
code that does ``from app.database import engine, SessionLocal``.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

_engine = None
_SessionLocal = None
class Base(DeclarativeBase):
    pass


def _normalize_url(url: str) -> str:
    """Replace deprecated 'postgres://' with 'postgresql://' (SQLAlchemy 2.0+)."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _initialize_database():
    """Create the engine and session factory on first access."""
    global _engine, _SessionLocal

    settings = get_settings()
    url = _normalize_url(settings.database_url)

    _engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if "sqlite" in url else {},
    )

    # Enable foreign keys for SQLite
    if "sqlite" in url:
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def __getattr__(name):
    """Lazy accessor for module-level ``engine`` and ``SessionLocal`` (PEP 562)."""
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_session_local()
    raise AttributeError(f"module 'app.database' has no attribute {name!r}")


def get_engine():
    """Return the (lazily created) SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _initialize_database()
    return _engine


def get_session_local():
    """Return the (lazily created) sessionmaker."""
    global _SessionLocal
    if _SessionLocal is None:
        _initialize_database()
    return _SessionLocal


def get_db():
    """FastAPI dependency — yields a database session for the request."""
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables."""
    from app.models import (  # noqa: F401 — import to register models
        AdminUser,
        Category,
        Product,
        User,
        Order,
        OrderItem,
        Review,
        Retailer,
        Settings,
        SettingsCategory,
        AdminAuditLog,
        PasswordResetToken,
        AdminNotification,
        WishlistItem,
        NewsletterSubscriber,
        BroadcastCampaign,
        BroadcastEvent,
        BroadcastTemplate,
    )
    Base.metadata.create_all(bind=get_engine())
