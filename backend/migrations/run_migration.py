"""
Migration runner — applies pending migrations to the database.

Usage:
    python -m migrations.run_migration         # Run all pending
    python -m migrations.run_migration 001     # Run specific migration
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MIGRATIONS = {
    "001": "migrations.001_add_retailer_bank_fields",
    "002": "migrations.002_extend_ad_campaign",
    "003": "migrations.003_add_order_earning_promo_ad",
    "004": "migrations.004_add_ad_campaign_columns",
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


def run_all():
    """Run all migrations in order."""
    for mid in sorted(MIGRATIONS.keys()):
        print(f"\n--- Running migration {mid} ---")
        run_migration(mid)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_migration(sys.argv[1])
    else:
        run_all()
