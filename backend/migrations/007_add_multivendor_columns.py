"""
Migration 007: Add new multi-vendor columns and tables.
Works with both SQLite and PostgreSQL.
"""
import os


def upgrade():
    """Add new columns to existing tables. Uses raw SQL for cross-database compat."""
    from app.database import get_engine
    from sqlalchemy import text

    engine = get_engine()
    dialect = engine.dialect.name

    # Use separate connections so each ALTER/CREATE is independent.
    # PostgreSQL enters a failed transaction state after any error,
    # and a bare `except` doesn't reset that state.

    def _run(label, sql):
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            print(f"[007] {label}")
        except Exception as e:
            print(f"[007] {label}: {e}")

    # Retailer: invited_by_retailer_id
    if dialect == "sqlite":
        _run("Added retailer.invited_by_retailer_id",
             "ALTER TABLE retailer ADD COLUMN invited_by_retailer_id VARCHAR")
    else:
        _run("Added retailer.invited_by_retailer_id",
             "ALTER TABLE retailer ADD COLUMN IF NOT EXISTS invited_by_retailer_id VARCHAR")

    # User: attribute_points (quote table name — 'user' is reserved in PostgreSQL)
    if dialect == "sqlite":
        _run('Added user.attribute_points',
             'ALTER TABLE "user" ADD COLUMN attribute_points INTEGER DEFAULT 0')
    else:
        _run('Added user.attribute_points',
             'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS attribute_points INTEGER DEFAULT 0')

    # User: referred_by_retailer_id
    if dialect == "sqlite":
        _run("Added user.referred_by_retailer_id",
             'ALTER TABLE "user" ADD COLUMN referred_by_retailer_id VARCHAR')
    else:
        _run("Added user.referred_by_retailer_id",
             'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS referred_by_retailer_id VARCHAR')

    # VendorWallet: locked_escrow_balance
    if dialect == "sqlite":
        _run("Added vendor_wallet.locked_escrow_balance",
             "ALTER TABLE vendor_wallet ADD COLUMN locked_escrow_balance FLOAT DEFAULT 0.0")
    else:
        _run("Added vendor_wallet.locked_escrow_balance",
             "ALTER TABLE vendor_wallet ADD COLUMN IF NOT EXISTS locked_escrow_balance DOUBLE PRECISION DEFAULT 0.0")

    # Create new tables if they don't exist
    from app.models import (
        VendorFulfillment, PayoutRequest, PointRedemption,
        VendorSettlement, WebhookPayloadLog, VendorNotification,
    )
    # Only create the new tables (not all tables)
    new_tables = [
        VendorFulfillment.__table__,
        PayoutRequest.__table__,
        PointRedemption.__table__,
        VendorSettlement.__table__,
        WebhookPayloadLog.__table__,
        VendorNotification.__table__,
    ]
    for table in new_tables:
        try:
            table.create(bind=engine, checkfirst=True)
            print(f"[007] Table {table.name} ensured")
        except Exception as e:
            print(f"[007] Table {table.name}: {e}")


if __name__ == "__main__":
    upgrade()
