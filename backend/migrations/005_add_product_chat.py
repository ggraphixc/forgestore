"""
Migration 005: Create product_chat_message table for live product chat.

Compatible with both SQLite and PostgreSQL. Run from project root:
    python -m migrations.005_add_product_chat

Or via the runner:
    python -m migrations.run_migration 005
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.database import get_engine
from app.config import get_settings

MIGRATION_NAME = "005_add_product_chat"


def upgrade(force_sqlite: bool = False):
    """Apply migration: create product_chat_message table."""
    engine = get_engine()
    settings = get_settings()

    if force_sqlite or "sqlite" in settings.database_url:
        _upgrade_sqlite(engine)
    else:
        _upgrade_postgres(engine)

    print(f"[{MIGRATION_NAME}] Upgrade complete.")


def _upgrade_postgres(engine):
    """PostgreSQL: CREATE TABLE IF NOT EXISTS."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS product_chat_message (
                id VARCHAR PRIMARY KEY,
                product_id VARCHAR NOT NULL REFERENCES product(id) ON DELETE CASCADE,
                user_id VARCHAR REFERENCES "user"(id) ON DELETE SET NULL,
                author_name VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_product_chat_product
            ON product_chat_message(product_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_product_chat_created
            ON product_chat_message(created_at)
        """))
        conn.commit()


def _upgrade_sqlite(engine):
    """SQLite: CREATE TABLE IF NOT EXISTS."""
    with engine.connect() as conn:
        tables = [row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )]

        if "product_chat_message" not in tables:
            conn.execute(text("""
                CREATE TABLE product_chat_message (
                    id VARCHAR PRIMARY KEY,
                    product_id VARCHAR NOT NULL REFERENCES product(id) ON DELETE CASCADE,
                    user_id VARCHAR REFERENCES "user"(id) ON DELETE SET NULL,
                    author_name VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX idx_product_chat_product ON product_chat_message(product_id)"
            ))
            conn.execute(text(
                "CREATE INDEX idx_product_chat_created ON product_chat_message(created_at)"
            ))
            print("  Created table: product_chat_message")
        else:
            print("  Skipped (exists): product_chat_message")

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
