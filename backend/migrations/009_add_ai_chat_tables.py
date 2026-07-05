"""
Migration 009: Create AI chat tables (ai_conversation, ai_message,
user_preference_vector, recommendation_cache).

Run from project root:
    python -m migrations.009_add_ai_chat_tables
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.database import get_engine
from app.config import get_settings

MIGRATION_NAME = "009_add_ai_chat_tables"


def upgrade(force_sqlite: bool = False):
    engine = get_engine()
    settings = get_settings()

    if force_sqlite or "sqlite" in settings.database_url:
        _upgrade_sqlite(engine)
    else:
        _upgrade_postgres(engine)

    print(f"[{MIGRATION_NAME}] Upgrade complete.")


def _upgrade_postgres(engine):
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_conversation (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR REFERENCES "user"(id) ON DELETE SET NULL,
                session_id VARCHAR(255) NOT NULL,
                title VARCHAR(255),
                context JSONB,
                extra_data JSONB,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ai_conv_session
            ON ai_conversation(session_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ai_conv_user
            ON ai_conversation(user_id)
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_message (
                id VARCHAR PRIMARY KEY,
                conversation_id VARCHAR NOT NULL REFERENCES ai_conversation(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                extra_data JSONB,
                tokens_used INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ai_msg_conv
            ON ai_message(conversation_id)
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_preference_vector (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                category_affinities JSONB,
                price_range_prefs JSONB,
                brand_affinities JSONB,
                viewed_products JSONB,
                purchased_categories JSONB,
                search_terms JSONB,
                embedding TEXT,
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_pref_vec_user
            ON user_preference_vector(user_id)
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS recommendation_cache (
                id VARCHAR PRIMARY KEY,
                context_type VARCHAR(50) NOT NULL,
                context_id VARCHAR NOT NULL,
                recommendations JSONB NOT NULL,
                expires_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_rec_cache_type
            ON recommendation_cache(context_type)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_rec_cache_ctx
            ON recommendation_cache(context_id)
        """))

        conn.commit()


def _upgrade_sqlite(engine):
    with engine.connect() as conn:
        tables = [row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )]

        if "ai_conversation" not in tables:
            conn.execute(text("""
                CREATE TABLE ai_conversation (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR REFERENCES "user"(id) ON DELETE SET NULL,
                    session_id VARCHAR(255) NOT NULL,
                    title VARCHAR(255),
                    context TEXT,
                    extra_data TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX idx_ai_conv_session ON ai_conversation(session_id)"))
            conn.execute(text("CREATE INDEX idx_ai_conv_user ON ai_conversation(user_id)"))
            print("  Created table: ai_conversation")
        else:
            print("  Skipped (exists): ai_conversation")

        if "ai_message" not in tables:
            conn.execute(text("""
                CREATE TABLE ai_message (
                    id VARCHAR PRIMARY KEY,
                    conversation_id VARCHAR NOT NULL REFERENCES ai_conversation(id) ON DELETE CASCADE,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    extra_data TEXT,
                    tokens_used INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX idx_ai_msg_conv ON ai_message(conversation_id)"))
            print("  Created table: ai_message")
        else:
            print("  Skipped (exists): ai_message")

        if "user_preference_vector" not in tables:
            conn.execute(text("""
                CREATE TABLE user_preference_vector (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                    category_affinities TEXT,
                    price_range_prefs TEXT,
                    brand_affinities TEXT,
                    viewed_products TEXT,
                    purchased_categories TEXT,
                    search_terms TEXT,
                    embedding TEXT,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX idx_pref_vec_user ON user_preference_vector(user_id)"))
            print("  Created table: user_preference_vector")
        else:
            print("  Skipped (exists): user_preference_vector")

        if "recommendation_cache" not in tables:
            conn.execute(text("""
                CREATE TABLE recommendation_cache (
                    id VARCHAR PRIMARY KEY,
                    context_type VARCHAR(50) NOT NULL,
                    context_id VARCHAR NOT NULL,
                    recommendations TEXT NOT NULL,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX idx_rec_cache_type ON recommendation_cache(context_type)"))
            conn.execute(text("CREATE INDEX idx_rec_cache_ctx ON recommendation_cache(context_id)"))
            print("  Created table: recommendation_cache")
        else:
            print("  Skipped (exists): recommendation_cache")

        conn.commit()


if __name__ == "__main__":
    force_sqlite = "--sqlite" in sys.argv
    if force_sqlite:
        os.environ["DATABASE_URL"] = "sqlite:///./test_migration.db"
        print(f"[{MIGRATION_NAME}] Forcing SQLite mode")
        import importlib
        import app.database
        import app.config
        importlib.reload(app.config)
        importlib.reload(app.database)
    upgrade(force_sqlite=force_sqlite)
