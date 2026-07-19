"""
Database engine and session management.

Engine and SessionLocal are lazily initialized on first access to prevent
import-time crashes (e.g. when the database isn't reachable yet or when
environment variables aren't loaded).

The module-level __getattr__ (PEP 562) provides backward compatibility for
code that does ``from app.database import engine, SessionLocal``.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase  # type: ignore[attr-defined]  # sqlalchemy2-stubs doesn't re-export DeclarativeBase
from app.config import get_settings

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    __allow_unmapped__ = True


def _normalize_url(url: str) -> str:
    """Replace deprecated 'postgres://' with 'postgresql://' (SQLAlchemy 2.0+)."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _initialize_database():
    """Create the engine and session factory on first access."""
    global _engine, _SessionLocal

    settings = get_settings()
    url = _normalize_url(settings.database_url)

    _engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if "sqlite" in url else {},
    )

    # Enable foreign keys for SQLite
    if "sqlite" in url:
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def __getattr__(name):
    """Lazy accessor for module-level ``engine`` and ``SessionLocal`` (PEP 562)."""
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_session_local()
    raise AttributeError(f"module 'app.database' has no attribute {name!r}")


def get_engine():
    """Return the (lazily created) SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _initialize_database()
    return _engine


def get_session_local():
    """Return the (lazily created) sessionmaker."""
    global _SessionLocal
    if _SessionLocal is None:
        _initialize_database()
    return _SessionLocal


def get_db():
    """FastAPI dependency — yields a database session for the request."""
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables."""
    from app.models import (  # noqa: F401 — import to register models
        # Existing models
        AdminUser,
        Category,
        Product,
        User,
        Order,
        OrderItem,
        Review,
        Retailer,
        Settings,
        SettingsCategory,
        SettingsHistory,
        AdminAuditLog,
        PasswordResetToken,
        AdminNotification,
        WishlistItem,
        NewsletterSubscriber,
        BroadcastCampaign,
        BroadcastEvent,
        BroadcastTemplate,
        # System 1: Real-time Order Tracking
        Shipment,
        ShipmentEvent,
        DeliveryAgent,
        DeliveryLocationLog,
        # System 2: Advanced Vendor Dashboard
        VendorAnalytics,
        VendorPayout,
        VendorActivityLog,
        VendorPerformanceCache,
        # System 3: AI Shopping Assistant
        AIConversation,
        AIMessage,
        UserPreferenceVector,
        RecommendationCache,
        # System 4: Affiliate & Referral
        Affiliate,
        AffiliateCommission,
        ReferralEvent,
        AffiliatePayout,
        # System 5: Multi-Payment & Wallet
        Wallet,
        WalletTransaction,
        PaymentProvider,
        PaymentLog,
        EscrowTransaction,
        PaymentSplit,
        # System 6: Advanced Cart
        PersistentCart,
        CartActivity,
        AbandonedCart,
        CartRecommendation,
        # System 7: AI-Powered Smart Search
        SearchHistory,
        SearchTrend,
        SearchEmbedding,
        SearchClickAnalytics,
        # System 8: Modern Product Review
        ReviewMedia,
        ReviewReaction,
        ReviewSentiment,
        ReviewModeration,
        # System 9: Notification Infrastructure
        NotificationQueue,
        PushSubscription,
        UserNotificationPreferences,
        NotificationDeliveryLog,
        # System 10: Enterprise Commerce Intelligence
        AnalyticsSnapshot,
        CustomerLifetimeValue,
        FraudDetectionEvent,
        PredictiveForecast,
        # System 11: Advertising Campaigns
        AdCampaign,
        # Chat Moderation
        ProductChatMessage,
        ChatModeration,
        # System 12: Three-Tier Affiliate Engine
        VendorWallet,
        VendorWalletTransaction,
        ProductAffiliateToken,
        AffiliateApplication,
        VendorApplication,
        # System 16: Automated Commissions & Settlement
        VendorSettlement,
        # System 17: Idempotent Webhook Log
        WebhookPayloadLog,
        # System 18: Vendor Notification Pipeline
        VendorNotification,
        # System 19: Multi-Tenant WebSocket Chat
        ChatMessage,
        # System 20: Order Disputes & Escrow
        OrderDispute,
        # System 21: Reverse Logistics
        ReturnRequest,
        ReturnEvent,
        # System 22: Daily Analytics Materialization
        DailyMarketplaceSnapshot,
        DailyVendorSnapshot,
        # Additional models
        CartItem,
        OrderEarning,
        PromoAd,
        VendorFulfillment,
        PayoutRequest,
        PointRedemption,
        SupportTicket,
        SupportMessage,
        PickupPoint,
        PickupInventory,
        BulkOrder,
        # Product Moderation
        ProductFlag,
        ProductModerationLog,
    )
    Base.metadata.create_all(bind=get_engine())
    _apply_pending_migrations()


def _apply_pending_migrations():
    """Apply pending migrations that create_all() can't handle (ALTER TABLE, new tables)."""
    from sqlalchemy import text, inspect
    engine = get_engine()
    with engine.connect() as conn:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        # 014: Product moderation columns + tables
        if 'product' in existing_tables:
            product_cols = {c['name'] for c in inspector.get_columns('product')}
            if 'status' not in product_cols:
                conn.execute(text("ALTER TABLE product ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'APPROVED'"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_product_status ON product(status)"))
            if 'ai_confidence_score' not in product_cols:
                conn.execute(text("ALTER TABLE product ADD COLUMN ai_confidence_score FLOAT"))
            if 'ai_moderation_result' not in product_cols:
                conn.execute(text("ALTER TABLE product ADD COLUMN ai_moderation_result JSON"))
            if 'moderated_by' not in product_cols:
                conn.execute(text("ALTER TABLE product ADD COLUMN moderated_by VARCHAR"))
            if 'moderated_at' not in product_cols:
                conn.execute(text("ALTER TABLE product ADD COLUMN moderated_at TIMESTAMP"))
            if 'moderation_note' not in product_cols:
                conn.execute(text("ALTER TABLE product ADD COLUMN moderation_note TEXT"))

        if 'product_flag' not in existing_tables:
            conn.execute(text("""
                CREATE TABLE product_flag (
                    id VARCHAR PRIMARY KEY,
                    product_id VARCHAR NOT NULL REFERENCES product(id) ON DELETE CASCADE,
                    reported_by VARCHAR REFERENCES "user"(id) ON DELETE SET NULL,
                    reason VARCHAR(100) NOT NULL,
                    description TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    reviewed_by VARCHAR REFERENCES admin_user(id) ON DELETE SET NULL,
                    reviewed_at TIMESTAMP,
                    admin_note TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_product_flag_status ON product_flag(status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_product_flag_product_id ON product_flag(product_id)"))

        if 'product_moderation_log' not in existing_tables:
            conn.execute(text("""
                CREATE TABLE product_moderation_log (
                    id VARCHAR PRIMARY KEY,
                    product_id VARCHAR NOT NULL REFERENCES product(id) ON DELETE CASCADE,
                    action VARCHAR(50) NOT NULL,
                    ai_score FLOAT,
                    ai_reasoning TEXT,
                    performed_by VARCHAR REFERENCES admin_user(id) ON DELETE SET NULL,
                    note TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))

        # 015: VendorPromotion table
        if 'vendor_promotion' not in existing_tables:
            conn.execute(text("""
                CREATE TABLE vendor_promotion (
                    id VARCHAR PRIMARY KEY,
                    retailer_id VARCHAR REFERENCES retailer(id) ON DELETE SET NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    discount_type VARCHAR(20) NOT NULL DEFAULT 'percentage',
                    discount_value FLOAT NOT NULL DEFAULT 0,
                    promo_code VARCHAR(50) UNIQUE,
                    min_purchase FLOAT NOT NULL DEFAULT 0,
                    usage_limit INTEGER NOT NULL DEFAULT 0,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    start_date TIMESTAMP,
                    end_date TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))

        conn.commit()
