"""
Migration 004: Add new columns to ad_campaign table

Adds: ad_subtype, banner_type, admin_id, note

Compatible with both SQLite and PostgreSQL. Run from project root:
    python -m migrations.004_add_ad_campaign_columns

Or via the runner:
    python -m migrations.run_migration 004
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.database import get_engine, Base
from app.config import get_settings

MIGRATION_NAME = "004_add_ad_campaign_columns"


def upgrade(force_sqlite: bool = False):
    """Apply migration: add columns to ad_campaign table."""
    engine = get_engine()
    settings = get_settings()

    if force_sqlite or "sqlite" in settings.database_url:
        _upgrade_sqlite(engine)
    else:
        _upgrade_postgres(engine)

    print(f"[{MIGRATION_NAME}] Upgrade complete.")


def _upgrade_postgres(engine):
    """PostgreSQL: ALTER TABLE ADD COLUMN IF NOT EXISTS."""
    with engine.connect() as conn:
        columns = [
            ("ad_subtype", "VARCHAR(20)"),
            ("banner_type", "VARCHAR(20) DEFAULT 'banner'"),
            ("admin_id", "VARCHAR(36) REFERENCES admin_user(id) ON DELETE SET NULL"),
            ("note", "VARCHAR(500)"),
        ]
        for col_name, col_type in columns:
            conn.execute(
                text(f"ALTER TABLE ad_campaign ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
            )
            print(f"  Added column: {col_name}")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ad_campaign_admin
            ON ad_campaign(admin_id)
        """))
        conn.commit()


def _upgrade_sqlite(engine):
    """SQLite: Check PRAGMA table_info and add missing columns one at a time."""
    columns = [
        ("ad_subtype", "VARCHAR(20)"),
        ("banner_type", "VARCHAR(20) DEFAULT 'banner'"),
        ("admin_id", "VARCHAR(36) REFERENCES admin_user(id) ON DELETE SET NULL"),
        ("note", "VARCHAR(500)"),
    ]
    with engine.connect() as conn:
        tables = [row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )]
        if "ad_campaign" in tables:
            result = conn.execute(text("PRAGMA table_info('ad_campaign')"))
            existing = {row[1] for row in result}
            for col_name, col_type in columns:
                if col_name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE ad_campaign ADD COLUMN {col_name} {col_type}")
                    )
                    print(f"  Added column: {col_name}")
                else:
                    print(f"  Skipped (exists): {col_name}")
        else:
            print("  WARNING: 'ad_campaign' table not found — run migration 001 first")

        conn.commit()


if __name__ == "__main__":
    force_sqlite = "--sqlite" in sys.argv
    if force_sqlite:
        os.environ["DATABASE_URL"] = "sqlite:///./test_migration.db"
        print(f"[{MIGRATION_NAME}] Forcing SQLite mode (--sqlite flag detected)")
        import importlib
        import app.database
        import app.config
        importlib.reload(app.config)
        importlib.reload(app.database)
        import app.models
    upgrade(force_sqlite=force_sqlite)
