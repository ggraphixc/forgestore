"""Add VendorPromotion table for vendor discount/coupon engine."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "forgestore.db")


def migrate():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendor_promotion (
            id TEXT PRIMARY KEY,
            retailer_id TEXT REFERENCES retailer(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            description TEXT,
            discount_type TEXT NOT NULL DEFAULT 'percentage',
            discount_value REAL NOT NULL DEFAULT 0,
            promo_code TEXT UNIQUE,
            min_purchase REAL NOT NULL DEFAULT 0,
            usage_limit INTEGER NOT NULL DEFAULT 0,
            usage_count INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print("Migration 015: vendor_promotion table created.")


if __name__ == "__main__":
    migrate()
