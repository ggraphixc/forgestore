import sys
import os
sys.path.insert(0, 'backend')

os.environ['DATABASE_URL'] = 'postgresql://forgestore:npg_9UDHopLBZ0lX@ep-fragrant-queen-a7k49o71-pooler.ap-southeast-2.aws.neon.tech/eCommerce?sslmode=require&channel_binding=require'

from app.database import engine
from sqlalchemy import text

conn = engine.connect()

try:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS support_ticket (
            id SERIAL PRIMARY KEY,
            subject VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            category VARCHAR(50) NOT NULL DEFAULT 'OTHER',
            status VARCHAR(50) NOT NULL DEFAULT 'OPEN',
            priority VARCHAR(50) NOT NULL DEFAULT 'MEDIUM',
            created_by INTEGER,
            assigned_to INTEGER,
            retailer_id INTEGER,
            order_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            resolved_at TIMESTAMP
        )
    """))
    print("support_ticket table created")

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS support_message (
            id SERIAL PRIMARY KEY,
            ticket_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            sender_role VARCHAR(50) NOT NULL,
            message TEXT NOT NULL,
            attachment_url VARCHAR(500),
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    print("support_message table created")

    conn.commit()
    print("Migration complete!")
except Exception as e:
    print(f"Error: {e}")
    conn.rollback()
finally:
    conn.close()
