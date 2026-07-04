"""
Migration 008: Add support ticket system tables.
Works with both SQLite and PostgreSQL.
"""


def upgrade():
    from app.database import get_engine
    from sqlalchemy import text

    engine = get_engine()
    dialect = engine.dialect.name

    def _run(label, sql):
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            print(f"[008] {label}")
        except Exception as e:
            print(f"[008] {label}: {e}")

    if dialect == "postgresql":
        _run("Created support_ticket table", """
            CREATE TABLE IF NOT EXISTS support_ticket (
                id VARCHAR PRIMARY KEY,
                subject VARCHAR(255) NOT NULL,
                description TEXT NOT NULL,
                category VARCHAR(50) NOT NULL DEFAULT 'OTHER',
                status VARCHAR(30) NOT NULL DEFAULT 'OPEN',
                priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
                created_by VARCHAR REFERENCES "user"(id) ON DELETE CASCADE,
                assigned_to VARCHAR REFERENCES admin_user(id) ON DELETE SET NULL,
                retailer_id VARCHAR REFERENCES retailer(id) ON DELETE SET NULL,
                order_id VARCHAR REFERENCES "order"(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                resolved_at TIMESTAMP
            )
        """)
        _run("Created support_message table", """
            CREATE TABLE IF NOT EXISTS support_message (
                id VARCHAR PRIMARY KEY,
                ticket_id VARCHAR REFERENCES support_ticket(id) ON DELETE CASCADE,
                sender_id VARCHAR REFERENCES "user"(id) ON DELETE CASCADE,
                sender_role VARCHAR(20) NOT NULL,
                message TEXT NOT NULL,
                attachment_url VARCHAR(500),
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        _run("Created idx_support_ticket_created_by", "CREATE INDEX IF NOT EXISTS idx_support_ticket_created_by ON support_ticket(created_by)")
        _run("Created idx_support_ticket_status", "CREATE INDEX IF NOT EXISTS idx_support_ticket_status ON support_ticket(status)")
        _run("Created idx_support_ticket_assigned_to", "CREATE INDEX IF NOT EXISTS idx_support_ticket_assigned_to ON support_ticket(assigned_to)")
        _run("Created idx_support_message_ticket_id", "CREATE INDEX IF NOT EXISTS idx_support_message_ticket_id ON support_message(ticket_id)")
    else:
        _run("Created support_ticket table", """
            CREATE TABLE IF NOT EXISTS support_ticket (
                id VARCHAR PRIMARY KEY,
                subject VARCHAR(255) NOT NULL,
                description TEXT NOT NULL,
                category VARCHAR(50) NOT NULL DEFAULT 'OTHER',
                status VARCHAR(30) NOT NULL DEFAULT 'OPEN',
                priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
                created_by VARCHAR REFERENCES user(id) ON DELETE CASCADE,
                assigned_to VARCHAR REFERENCES admin_user(id) ON DELETE SET NULL,
                retailer_id VARCHAR REFERENCES retailer(id) ON DELETE SET NULL,
                order_id VARCHAR REFERENCES "order"(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP
            )
        """)
        _run("Created support_message table", """
            CREATE TABLE IF NOT EXISTS support_message (
                id VARCHAR PRIMARY KEY,
                ticket_id VARCHAR REFERENCES support_ticket(id) ON DELETE CASCADE,
                sender_id VARCHAR REFERENCES user(id) ON DELETE CASCADE,
                sender_role VARCHAR(20) NOT NULL,
                message TEXT NOT NULL,
                attachment_url VARCHAR(500),
                is_read BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


if __name__ == "__main__":
    upgrade()
