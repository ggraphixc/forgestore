"""
Migration 006: Add image_url, is_flagged, is_hidden to product_chat_message;
create chat_moderation table.

Compatible with both SQLite and PostgreSQL. Run from project root:
    python -m migrations.006_chat_moderation

Or via the runner:
    python -m migrations.run_migration 006
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.database import get_engine
from app.config import get_settings

MIGRATION_NAME = "006_chat_moderation"


def upgrade(force_sqlite: bool = False):
    """Apply migration: alter product_chat_message, create chat_moderation."""
    engine = get_engine()
    settings = get_settings()

    if force_sqlite or "sqlite" in settings.database_url:
        _upgrade_sqlite(engine)
    else:
        _upgrade_postgres(engine)

    print(f"[{MIGRATION_NAME}] Upgrade complete.")


def _upgrade_postgres(engine):
    """PostgreSQL: ALTER TABLE + CREATE TABLE."""
    # Use separate connections so each ALTER/CREATE is independent.
    # PostgreSQL enters a failed transaction state after any error,
    # and a bare `except` doesn't reset that state.
    for col, col_def in [
        ("image_url", "VARCHAR(500)"),
        ("is_flagged", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("is_hidden", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ]:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE product_chat_message ADD COLUMN {col} {col_def}"))
                conn.commit()
        except Exception:
            print(f"  Skipped (exists): product_chat_message.{col}")

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_moderation (
                id VARCHAR PRIMARY KEY,
                message_id VARCHAR NOT NULL REFERENCES product_chat_message(id) ON DELETE CASCADE,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                reason VARCHAR(100),
                notes TEXT,
                reviewed_by VARCHAR REFERENCES admin_user(id) ON DELETE SET NULL,
                reviewed_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_moderation_status
            ON chat_moderation(status)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_moderation_message
            ON chat_moderation(message_id)
        """))
        conn.commit()


def _upgrade_sqlite(engine):
    """SQLite: ALTER TABLE + CREATE TABLE."""
    with engine.connect() as conn:
        # Check existing columns on product_chat_message
        existing_cols = {row[1] for row in conn.execute(
            text("PRAGMA table_info(product_chat_message)")
        )}

        # Add new columns if missing
        if "image_url" not in existing_cols:
            conn.execute(text("ALTER TABLE product_chat_message ADD COLUMN image_url VARCHAR(500)"))
            print("  Added column: product_chat_message.image_url")
        else:
            print("  Skipped (exists): product_chat_message.image_url")

        if "is_flagged" not in existing_cols:
            conn.execute(text("ALTER TABLE product_chat_message ADD COLUMN is_flagged BOOLEAN NOT NULL DEFAULT 0"))
            print("  Added column: product_chat_message.is_flagged")
        else:
            print("  Skipped (exists): product_chat_message.is_flagged")

        if "is_hidden" not in existing_cols:
            conn.execute(text("ALTER TABLE product_chat_message ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT 0"))
            print("  Added column: product_chat_message.is_hidden")
        else:
            print("  Skipped (exists): product_chat_message.is_hidden")

        # Create chat_moderation table
        tables = {row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )}

        if "chat_moderation" not in tables:
            conn.execute(text("""
                CREATE TABLE chat_moderation (
                    id VARCHAR PRIMARY KEY,
                    message_id VARCHAR NOT NULL REFERENCES product_chat_message(id) ON DELETE CASCADE,
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    reason VARCHAR(100),
                    notes TEXT,
                    reviewed_by VARCHAR REFERENCES admin_user(id) ON DELETE SET NULL,
                    reviewed_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX idx_chat_moderation_status ON chat_moderation(status)"
            ))
            conn.execute(text(
                "CREATE INDEX idx_chat_moderation_message ON chat_moderation(message_id)"
            ))
            print("  Created table: chat_moderation")
        else:
            print("  Skipped (exists): chat_moderation")

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
    upgrade(force_sqlite=force_sqlite)
