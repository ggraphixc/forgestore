"""
Migration 001: Add Retailer Bank Fields & AdCampaign Table

Compatible with both SQLite and PostgreSQL. Run from project root:
    python -m migrations.001_add_retailer_bank_fields

Or via the runner:
    python -m migrations.run_migration 001
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.database import get_engine, Base
from app.config import get_settings

MIGRATION_NAME = "001_add_retailer_bank_fields"


def upgrade(force_sqlite: bool = False):
    """Apply migration: add columns to retailer, create ad_campaign table.

    Args:
        force_sqlite: If True, use SQLite-compatible path regardless of DATABASE_URL.
                      Useful for testing the migration locally.
    """
    engine = get_engine()
    settings = get_settings()

    if force_sqlite or "sqlite" in settings.database_url:
        _upgrade_sqlite(engine)
    else:
        _upgrade_postgres(engine)

    print(f"[{MIGRATION_NAME}] Upgrade complete.")


def _upgrade_postgres(engine):
    """PostgreSQL: ALTER TABLE + CREATE TABLE via raw SQL wrapped in text()."""
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE retailer
              ADD COLUMN IF NOT EXISTS bank_name VARCHAR(255),
              ADD COLUMN IF NOT EXISTS account_number VARCHAR(50),
              ADD COLUMN IF NOT EXISTS bank_code VARCHAR(20),
              ADD COLUMN IF NOT EXISTS account_name VARCHAR(255),
              ADD COLUMN IF NOT EXISTS paystack_subaccount_code VARCHAR(100),
              ADD COLUMN IF NOT EXISTS flutterwave_subaccount_id VARCHAR(100),
              ADD COLUMN IF NOT EXISTS commission_rate FLOAT NOT NULL DEFAULT 10.0
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ad_campaign (
                id VARCHAR PRIMARY KEY,
                retailer_id VARCHAR NOT NULL REFERENCES retailer(id) ON DELETE CASCADE,
                product_id VARCHAR REFERENCES product(id) ON DELETE SET NULL,
                ad_type VARCHAR(20) NOT NULL DEFAULT 'SHOP',
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                banner_url VARCHAR,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                payment_reference VARCHAR(255) NOT NULL UNIQUE,
                clicks INTEGER NOT NULL DEFAULT 0,
                impressions INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ad_campaign_retailer
            ON ad_campaign(retailer_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ad_campaign_status
            ON ad_campaign(status)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ad_campaign_payment_ref
            ON ad_campaign(payment_reference)
        """))
        conn.commit()


def _upgrade_sqlite(engine):
    """SQLite: add columns individually + create ad_campaign table.
    SQLite doesn't support ADD COLUMN IF NOT EXISTS or multi-column ALTER TABLE,
    so we check PRAGMA table_info first and add only missing columns one at a time.
    """
    columns = [
        ("bank_name", "VARCHAR(255)"),
        ("account_number", "VARCHAR(50)"),
        ("bank_code", "VARCHAR(20)"),
        ("account_name", "VARCHAR(255)"),
        ("paystack_subaccount_code", "VARCHAR(100)"),
        ("flutterwave_subaccount_id", "VARCHAR(100)"),
        ("commission_rate", "FLOAT NOT NULL DEFAULT 10.0"),
    ]
    with engine.connect() as conn:
        # Check if retailer table exists
        tables = [row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )]
        if "retailer" in tables:
            result = conn.execute(text("PRAGMA table_info('retailer')"))
            existing = {row[1] for row in result}
            for col_name, col_type in columns:
                if col_name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE retailer ADD COLUMN {col_name} {col_type}")
                    )
                    print(f"  Added column: {col_name}")
                else:
                    print(f"  Skipped (exists): {col_name}")
        else:
            print("  WARNING: 'retailer' table not found — creating all tables...")
            from app.models import Retailer  # ensure model is registered
            Base.metadata.create_all(engine, checkfirst=True)
            print("  Tables created.")

        # If retailer doesn't exist (test db), create it with raw SQL first
        if "retailer" not in tables:
            # Create minimal retailer table for ALTER TABLE testing
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS retailer (
                    id VARCHAR PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) NOT NULL UNIQUE,
                    bio TEXT,
                    logo_url VARCHAR,
                    banner_url VARCHAR,
                    location VARCHAR(255),
                    primary_color VARCHAR(20) DEFAULT 'zinc',
                    status VARCHAR(20) DEFAULT 'ACTIVE',
                    rating FLOAT NOT NULL DEFAULT 0.0,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("  Created table: retailer (minimal for migration test)")
            # Re-check column additions now that retailer exists
            result = conn.execute(text("PRAGMA table_info('retailer')"))
            existing = {row[1] for row in result}
            for col_name, col_type in columns:
                if col_name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE retailer ADD COLUMN {col_name} {col_type}")
                    )
                    print(f"  Added column: {col_name}")
                else:
                    print(f"  Skipped (exists): {col_name}")

        # Create ad_campaign table if not exists
        if "ad_campaign" not in tables:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ad_campaign (
                    id VARCHAR PRIMARY KEY,
                    retailer_id VARCHAR NOT NULL REFERENCES retailer(id) ON DELETE CASCADE,
                    product_id VARCHAR REFERENCES product(id) ON DELETE SET NULL,
                    ad_type VARCHAR(20) NOT NULL DEFAULT 'SHOP',
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    banner_url VARCHAR,
                    start_date TIMESTAMP,
                    end_date TIMESTAMP,
                    payment_reference VARCHAR(255) NOT NULL UNIQUE,
                    clicks INTEGER NOT NULL DEFAULT 0,
                    impressions INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("  Created table: ad_campaign")
        else:
            print("  Skipped (exists): ad_campaign")

        conn.commit()


if __name__ == "__main__":
    import sys
    force_sqlite = "--sqlite" in sys.argv
    if force_sqlite:
        os.environ["DATABASE_URL"] = "sqlite:///./test_migration.db"
        print(f"[{MIGRATION_NAME}] Forcing SQLite mode (--sqlite flag detected)")
        # Reimport with forced SQLite URL
        import importlib
        import app.database
        import app.config
        importlib.reload(app.config)
        importlib.reload(app.database)
        # Import all models so Base.metadata.create_all() picks them up
        import app.models  # noqa: F401
    upgrade(force_sqlite=force_sqlite)
