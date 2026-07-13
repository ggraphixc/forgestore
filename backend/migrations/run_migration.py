"""
Migration runner — applies pending migrations to the database.

Usage:
    python -m migrations.run_migration         # Run all pending
    python -m migrations.run_migration 001     # Run specific migration
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text

MIGRATIONS = {
    "001": "migrations.001_add_retailer_bank_fields",
    "002": "migrations.002_extend_ad_campaign",
    "003": "migrations.003_add_order_earning_promo_ad",
    "004": "migrations.004_add_ad_campaign_columns",
    "005": "migrations.005_add_product_chat",
    "006": "migrations.006_chat_moderation",
    "007": "migrations.007_add_multivendor_columns",
    "008": "migrations.008_add_support_tables",
    "009": "migrations.009_add_ai_chat_tables",
    "010": "migrations.010_add_product_views_sold",
    "011": "migrations.011_add_product_video_url",
}


def run_migration(migration_id: str):
    """Import and run a single migration's upgrade()."""
    module_path = MIGRATIONS.get(migration_id)
    if not module_path:
        print(f"Unknown migration: {migration_id}")
        print(f"Available: {', '.join(sorted(MIGRATIONS.keys()))}")
        sys.exit(1)

    import importlib
    mod = importlib.import_module(module_path)
    mod.upgrade()
    print(f"Migration {migration_id} applied successfully.")


def run_pending_migrations(print_func=print):
    """Run all pending migrations in order.

    Safe to call from app startup (e.g., main.py on_startup).
    Skips with a warning if migrations directory can't be imported.
    Uses print_func for output so callers can pass logger.info.
    """
    for mid in sorted(MIGRATIONS.keys()):
        try:
            run_migration(mid)
        except Exception as e:
            print_func(f"Migration {mid} skipped (already applied or failed): {e}")


def run_all():
    """Run all migrations in order.

    Each migration gets a fresh connection so a failed migration
    doesn't poison subsequent ones.
    """
    from app.database import get_engine
    engine = get_engine()

    for mid in sorted(MIGRATIONS.keys()):
        print(f"\n--- Running migration {mid} ---")
        try:
            # Reset any broken transaction state before each migration
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
        except Exception:
            pass
        run_migration(mid)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_migration(sys.argv[1])
    else:
        run_all()
