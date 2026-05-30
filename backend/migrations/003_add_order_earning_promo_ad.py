"""
Migration 003: Create OrderEarning and PromoAd Tables

Compatible with both SQLite and PostgreSQL. Run from project root:
    python -m migrations.003_add_order_earning_promo_ad

Or via the runner:
    python -m migrations.run_migration 003
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.database import get_engine, Base
from app.config import get_settings

MIGRATION_NAME = "003_add_order_earning_promo_ad"


def upgrade(force_sqlite: bool = False):
    """Apply migration: create order_earning and promo_ad tables."""
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
            CREATE TABLE IF NOT EXISTS order_earning (
                id VARCHAR PRIMARY KEY,
                order_id VARCHAR NOT NULL REFERENCES "order"(id) ON DELETE CASCADE,
                retailer_id VARCHAR NOT NULL REFERENCES retailer(id) ON DELETE CASCADE,
                product_id VARCHAR REFERENCES product(id) ON DELETE SET NULL,
                amount FLOAT NOT NULL,
                commission FLOAT NOT NULL DEFAULT 0.0,
                net_amount FLOAT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                paid_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS promo_ad (
                id VARCHAR PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                ad_subtype VARCHAR(20) NOT NULL,
                banner_type VARCHAR(20) DEFAULT 'banner',
                banner_url VARCHAR(500) NOT NULL,
                target_url VARCHAR(500),
                status VARCHAR(20) DEFAULT 'ACTIVE',
                created_by VARCHAR(36) REFERENCES admin_user(id) ON DELETE SET NULL,
                retailer_id VARCHAR(36) REFERENCES retailer(id) ON DELETE SET NULL,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                clicks INTEGER NOT NULL DEFAULT 0,
                impressions INTEGER NOT NULL DEFAULT 0,
                note VARCHAR(500),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_order_earning_order
            ON order_earning(order_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_order_earning_retailer
            ON order_earning(retailer_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_order_earning_status
            ON order_earning(status)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_promo_ad_retailer
            ON promo_ad(retailer_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_promo_ad_status
            ON promo_ad(status)
        """))
        conn.commit()


def _upgrade_sqlite(engine):
    """SQLite: CREATE TABLE IF NOT EXISTS."""
    with engine.connect() as conn:
        tables = [row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )]

        if "order_earning" not in tables:
            conn.execute(text("""
                CREATE TABLE order_earning (
                    id VARCHAR PRIMARY KEY,
                    order_id VARCHAR NOT NULL REFERENCES "order"(id) ON DELETE CASCADE,
                    retailer_id VARCHAR NOT NULL REFERENCES retailer(id) ON DELETE CASCADE,
                    product_id VARCHAR REFERENCES product(id) ON DELETE SET NULL,
                    amount REAL NOT NULL,
                    commission REAL NOT NULL DEFAULT 0.0,
                    net_amount REAL NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    paid_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX idx_order_earning_order ON order_earning(order_id)"
            ))
            conn.execute(text(
                "CREATE INDEX idx_order_earning_retailer ON order_earning(retailer_id)"
            ))
            conn.execute(text(
                "CREATE INDEX idx_order_earning_status ON order_earning(status)"
            ))
            print("  Created table: order_earning")
        else:
            print("  Skipped (exists): order_earning")

        if "promo_ad" not in tables:
            conn.execute(text("""
                CREATE TABLE promo_ad (
                    id VARCHAR PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    ad_subtype VARCHAR(20) NOT NULL,
                    banner_type VARCHAR(20) DEFAULT 'banner',
                    banner_url VARCHAR(500) NOT NULL,
                    target_url VARCHAR(500),
                    status VARCHAR(20) DEFAULT 'ACTIVE',
                    created_by VARCHAR(36) REFERENCES admin_user(id) ON DELETE SET NULL,
                    retailer_id VARCHAR(36) REFERENCES retailer(id) ON DELETE SET NULL,
                    start_date TIMESTAMP,
                    end_date TIMESTAMP,
                    clicks INTEGER NOT NULL DEFAULT 0,
                    impressions INTEGER NOT NULL DEFAULT 0,
                    note VARCHAR(500),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX idx_promo_ad_retailer ON promo_ad(retailer_id)"
            ))
            conn.execute(text(
                "CREATE INDEX idx_promo_ad_status ON promo_ad(status)"
            ))
            print("  Created table: promo_ad")
        else:
            print("  Skipped (exists): promo_ad")

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
