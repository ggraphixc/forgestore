"""
Migration 002: Extend AdCampaign for SYSTEM_PROMO support

- Add SYSTEM_PROMO to ad_type enum
- Make retailer_id nullable (for standalone promos)
- Make banner_url required (NOT NULL)
- Add target_url column for custom redirect URLs
- Make payment_reference nullable (SYSTEM_PROMO is free)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.database import get_engine, Base
from app.config import get_settings

MIGRATION_NAME = "002_extend_ad_campaign"


def upgrade(force_sqlite: bool = False):
    """Apply migration: extend ad_campaign table for SYSTEM_PROMO support."""
    engine = get_engine()
    settings = get_settings()

    if force_sqlite or "sqlite" in settings.database_url:
        _upgrade_sqlite(engine)
    else:
        _upgrade_postgres(engine)

    print(f"[{MIGRATION_NAME}] Upgrade complete.")


def _upgrade_postgres(engine):
    """PostgreSQL: ALTER TABLE for ad_campaign."""
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE ad_campaign
              DROP CONSTRAINT IF EXISTS ad_campaign_ad_type_check,
              ADD COLUMN IF NOT EXISTS target_url VARCHAR(500),
              ALTER COLUMN retailer_id DROP NOT NULL,
              ALTER COLUMN banner_url SET NOT NULL,
              ALTER COLUMN payment_reference DROP NOT NULL
        """))
        conn.execute(text("""
            ALTER TABLE ad_campaign
              ADD CONSTRAINT ad_campaign_ad_type_check
              CHECK (ad_type IN ('PRODUCT', 'SHOP', 'SYSTEM_PROMO'))
        """))
        conn.commit()


def _upgrade_sqlite(engine):
    """SQLite: Handle table alterations."""
    with engine.connect() as conn:
        # Check if ad_campaign table exists
        if "ad_campaign" in [row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )]:
            # SQLite doesn't support dropping constraints directly, recreate table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ad_campaign_new (
                    id VARCHAR PRIMARY KEY,
                    retailer_id VARCHAR REFERENCES retailer(id) ON DELETE CASCADE,
                    product_id VARCHAR REFERENCES product(id) ON DELETE SET NULL,
                    ad_type VARCHAR(20) NOT NULL DEFAULT 'SHOP',
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    banner_url VARCHAR NOT NULL,
                    target_url VARCHAR(500),
                    start_date TIMESTAMP,
                    end_date TIMESTAMP,
                    payment_reference VARCHAR(255) UNIQUE,
                    clicks INTEGER NOT NULL DEFAULT 0,
                    impressions INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            # Migrate data
            conn.execute(text("""
                INSERT INTO ad_campaign_new SELECT 
                    id, retailer_id, product_id, ad_type, status,
                    COALESCE(banner_url, '/static/img/placeholder.svg') as banner_url,
                    NULL as target_url,
                    start_date, end_date, payment_reference, clicks, impressions, created_at, updated_at
                FROM ad_campaign
            """))
            conn.execute(text("DROP TABLE ad_campaign"))
            conn.execute(text("ALTER TABLE ad_campaign_new RENAME TO ad_campaign"))
            conn.commit()
        else:
            print("  WARNING: 'ad_campaign' table not found — run migration 001 first")


if __name__ == "__main__":
    import sys
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