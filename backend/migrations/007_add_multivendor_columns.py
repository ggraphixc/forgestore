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

    with engine.connect() as conn:
        # Retailer: invited_by_retailer_id
        try:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE retailer ADD COLUMN invited_by_retailer_id VARCHAR"))
            else:
                conn.execute(text("ALTER TABLE retailer ADD COLUMN IF NOT EXISTS invited_by_retailer_id VARCHAR"))
            conn.commit()
            print("[007] Added retailer.invited_by_retailer_id")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("[007] retailer.invited_by_retailer_id exists")
            else:
                print(f"[007] retailer.invited_by_retailer_id: {e}")

        # User: attribute_points (quote table name — 'user' is reserved in PostgreSQL)
        try:
            if dialect == "sqlite":
                conn.execute(text('ALTER TABLE "user" ADD COLUMN attribute_points INTEGER DEFAULT 0'))
            else:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS attribute_points INTEGER DEFAULT 0'))
            conn.commit()
            print("[007] Added user.attribute_points")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("[007] user.attribute_points exists")
            else:
                print(f"[007] user.attribute_points: {e}")

        # User: referred_by_retailer_id
        try:
            if dialect == "sqlite":
                conn.execute(text('ALTER TABLE "user" ADD COLUMN referred_by_retailer_id VARCHAR'))
            else:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS referred_by_retailer_id VARCHAR'))
            conn.commit()
            print("[007] Added user.referred_by_retailer_id")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("[007] user.referred_by_retailer_id exists")
            else:
                print(f"[007] user.referred_by_retailer_id: {e}")

        # VendorWallet: locked_escrow_balance
        try:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE vendor_wallet ADD COLUMN locked_escrow_balance FLOAT DEFAULT 0.0"))
            else:
                conn.execute(text("ALTER TABLE vendor_wallet ADD COLUMN IF NOT EXISTS locked_escrow_balance DOUBLE PRECISION DEFAULT 0.0"))
            conn.commit()
            print("[007] Added vendor_wallet.locked_escrow_balance")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("[007] vendor_wallet.locked_escrow_balance exists")
            else:
                print(f"[007] vendor_wallet.locked_escrow_balance: {e}")

        # Create new tables if they don't exist
        from app.models import (
            VendorFulfillment, PayoutRequest, PointRedemption,
            VendorSettlement, WebhookPayloadLog, VendorNotification,
        )
        from app.database import Base
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
