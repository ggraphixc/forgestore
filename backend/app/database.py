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
    )
    Base.metadata.create_all(bind=get_engine())
