"""
Migration 011: Add product.video_url column + bulk_order table + logistics columns/tables.

Consolidates 011-013 into a single raw-SQL migration (alembic op doesn't work
outside alembic context). Uses IF NOT EXISTS for idempotency.
"""

from app.database import get_engine
from sqlalchemy import text


def upgrade():
    engine = get_engine()
    dialect = engine.dialect.name

    def _run(label, sql):
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            print(f"[011] {label}")
        except Exception as e:
            print(f"[011] {label}: {e}")

    # ── 1. product.video_url ────────────────────────────────────
    if dialect == "postgresql":
        _run("product.video_url",
             'ALTER TABLE product ADD COLUMN IF NOT EXISTS video_url VARCHAR(500)')
    else:
        _run("product.video_url",
             'ALTER TABLE product ADD COLUMN video_url VARCHAR(500)')

    # ── 2. order.fulfillment_mode ───────────────────────────────
    if dialect == "postgresql":
        _run("order.fulfillment_mode",
             'ALTER TABLE "order" ADD COLUMN IF NOT EXISTS fulfillment_mode VARCHAR(20) NOT NULL DEFAULT \'VENDOR\'')
    else:
        _run("order.fulfillment_mode",
             'ALTER TABLE "order" ADD COLUMN fulfillment_mode VARCHAR(20) NOT NULL DEFAULT \'VENDOR\'')

    # ── 3. shipment: batch_id, proof_photo_url ──────────────────
    if dialect == "postgresql":
        _run("shipment.batch_id",
             'ALTER TABLE shipment ADD COLUMN IF NOT EXISTS batch_id VARCHAR(50)')
        _run("shipment.proof_photo_url",
             'ALTER TABLE shipment ADD COLUMN IF NOT EXISTS proof_photo_url VARCHAR(500)')
    else:
        _run("shipment.batch_id",
             'ALTER TABLE shipment ADD COLUMN batch_id VARCHAR(50)')
        _run("shipment.proof_photo_url",
             'ALTER TABLE shipment ADD COLUMN proof_photo_url VARCHAR(500)')

    # ── 4. delivery_agent performance columns ───────────────────
    if dialect == "postgresql":
        _run("delivery_agent.successful_deliveries",
             'ALTER TABLE delivery_agent ADD COLUMN IF NOT EXISTS successful_deliveries INTEGER NOT NULL DEFAULT 0')
        _run("delivery_agent.avg_delivery_hours",
             'ALTER TABLE delivery_agent ADD COLUMN IF NOT EXISTS avg_delivery_hours DOUBLE PRECISION NOT NULL DEFAULT 0.0')
        _run("delivery_agent.performance_score",
             'ALTER TABLE delivery_agent ADD COLUMN IF NOT EXISTS performance_score DOUBLE PRECISION NOT NULL DEFAULT 0.0')
    else:
        _run("delivery_agent.successful_deliveries",
             'ALTER TABLE delivery_agent ADD COLUMN successful_deliveries INTEGER NOT NULL DEFAULT 0')
        _run("delivery_agent.avg_delivery_hours",
             'ALTER TABLE delivery_agent ADD COLUMN avg_delivery_hours FLOAT NOT NULL DEFAULT 0.0')
        _run("delivery_agent.performance_score",
             'ALTER TABLE delivery_agent ADD COLUMN performance_score FLOAT NOT NULL DEFAULT 0.0')

    # ── 5. pickup_point table ───────────────────────────────────
    if dialect == "postgresql":
        _run("pickup_point table", """
            CREATE TABLE IF NOT EXISTS pickup_point (
                id VARCHAR PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                address VARCHAR(500) NOT NULL,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                phone VARCHAR(50),
                operating_hours VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
    else:
        _run("pickup_point table", """
            CREATE TABLE IF NOT EXISTS pickup_point (
                id VARCHAR PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                address VARCHAR(500) NOT NULL,
                latitude FLOAT,
                longitude FLOAT,
                phone VARCHAR(50),
                operating_hours VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ── 6. pickup_inventory table ───────────────────────────────
    if dialect == "postgresql":
        _run("pickup_inventory table", """
            CREATE TABLE IF NOT EXISTS pickup_inventory (
                id VARCHAR PRIMARY KEY,
                pickup_point_id VARCHAR REFERENCES pickup_point(id) ON DELETE CASCADE NOT NULL,
                product_id VARCHAR REFERENCES product(id) ON DELETE CASCADE NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                reserved INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
    else:
        _run("pickup_inventory table", """
            CREATE TABLE IF NOT EXISTS pickup_inventory (
                id VARCHAR PRIMARY KEY,
                pickup_point_id VARCHAR REFERENCES pickup_point(id) ON DELETE CASCADE NOT NULL,
                product_id VARCHAR REFERENCES product(id) ON DELETE CASCADE NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                reserved INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ── 7. return_request table ─────────────────────────────────
    if dialect == "postgresql":
        _run("return_request table", """
            CREATE TABLE IF NOT EXISTS return_request (
                id VARCHAR PRIMARY KEY,
                return_number VARCHAR(50) UNIQUE NOT NULL,
                order_id VARCHAR REFERENCES "order"(id) ON DELETE CASCADE NOT NULL,
                shipment_id VARCHAR REFERENCES shipment(id) ON DELETE SET NULL,
                customer_id VARCHAR REFERENCES "user"(id) ON DELETE CASCADE NOT NULL,
                retailer_id VARCHAR REFERENCES retailer(id) ON DELETE SET NULL,
                reason VARCHAR(50) NOT NULL,
                description TEXT,
                status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                return_tracking VARCHAR(100),
                return_carrier VARCHAR(50),
                return_fee DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                refund_amount DOUBLE PRECISION,
                pickup_address TEXT,
                delivery_address TEXT,
                pickup_date TIMESTAMP,
                received_date TIMESTAMP,
                resolved_by VARCHAR REFERENCES admin_user(id) ON DELETE SET NULL,
                resolution_notes TEXT,
                evidence_urls JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
    else:
        _run("return_request table", """
            CREATE TABLE IF NOT EXISTS return_request (
                id VARCHAR PRIMARY KEY,
                return_number VARCHAR(50) UNIQUE NOT NULL,
                order_id VARCHAR REFERENCES "order"(id) ON DELETE CASCADE NOT NULL,
                shipment_id VARCHAR REFERENCES shipment(id) ON DELETE SET NULL,
                customer_id VARCHAR REFERENCES "user"(id) ON DELETE CASCADE NOT NULL,
                retailer_id VARCHAR REFERENCES retailer(id) ON DELETE SET NULL,
                reason VARCHAR(50) NOT NULL,
                description TEXT,
                status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                return_tracking VARCHAR(100),
                return_carrier VARCHAR(50),
                return_fee FLOAT NOT NULL DEFAULT 0.0,
                refund_amount FLOAT,
                pickup_address TEXT,
                delivery_address TEXT,
                pickup_date TIMESTAMP,
                received_date TIMESTAMP,
                resolved_by VARCHAR REFERENCES admin_user(id) ON DELETE SET NULL,
                resolution_notes TEXT,
                evidence_urls TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ── 8. return_event table ───────────────────────────────────
    if dialect == "postgresql":
        _run("return_event table", """
            CREATE TABLE IF NOT EXISTS return_event (
                id VARCHAR PRIMARY KEY,
                return_id VARCHAR REFERENCES return_request(id) ON DELETE CASCADE NOT NULL,
                status VARCHAR(30) NOT NULL,
                description TEXT,
                created_by VARCHAR,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
    else:
        _run("return_event table", """
            CREATE TABLE IF NOT EXISTS return_event (
                id VARCHAR PRIMARY KEY,
                return_id VARCHAR REFERENCES return_request(id) ON DELETE CASCADE NOT NULL,
                status VARCHAR(30) NOT NULL,
                description TEXT,
                created_by VARCHAR,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ── 9. bulk_order table ─────────────────────────────────────
    if dialect == "postgresql":
        _run("bulk_order table", """
            CREATE TABLE IF NOT EXISTS bulk_order (
                id VARCHAR PRIMARY KEY,
                customer_id VARCHAR REFERENCES "user"(id) ON DELETE SET NULL,
                product_id VARCHAR REFERENCES product(id) ON DELETE CASCADE NOT NULL,
                retailer_id VARCHAR REFERENCES retailer(id) ON DELETE SET NULL,
                quantity INTEGER NOT NULL,
                unit_price DOUBLE PRECISION,
                total_price DOUBLE PRECISION,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                customer_name VARCHAR(255),
                customer_email VARCHAR(255),
                customer_phone VARCHAR(50),
                notes TEXT,
                vendor_notes TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
    else:
        _run("bulk_order table", """
            CREATE TABLE IF NOT EXISTS bulk_order (
                id VARCHAR PRIMARY KEY,
                customer_id VARCHAR REFERENCES user(id) ON DELETE SET NULL,
                product_id VARCHAR REFERENCES product(id) ON DELETE CASCADE NOT NULL,
                retailer_id VARCHAR REFERENCES retailer(id) ON DELETE SET NULL,
                quantity INTEGER NOT NULL,
                unit_price FLOAT,
                total_price FLOAT,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                customer_name VARCHAR(255),
                customer_email VARCHAR(255),
                customer_phone VARCHAR(50),
                notes TEXT,
                vendor_notes TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ── Indexes ─────────────────────────────────────────────────
    if dialect == "postgresql":
        _run("idx_pickup_inventory_pickup_point",
             "CREATE INDEX IF NOT EXISTS idx_pickup_inventory_pickup_point ON pickup_inventory(pickup_point_id)")
        _run("idx_pickup_inventory_product",
             "CREATE INDEX IF NOT EXISTS idx_pickup_inventory_product ON pickup_inventory(product_id)")
        _run("idx_return_request_order",
             "CREATE INDEX IF NOT EXISTS idx_return_request_order ON return_request(order_id)")
        _run("idx_return_request_customer",
             "CREATE INDEX IF NOT EXISTS idx_return_request_customer ON return_request(customer_id)")
        _run("idx_return_request_status",
             "CREATE INDEX IF NOT EXISTS idx_return_request_status ON return_request(status)")
        _run("idx_return_event_return",
             "CREATE INDEX IF NOT EXISTS idx_return_event_return ON return_event(return_id)")


if __name__ == "__main__":
    upgrade()
