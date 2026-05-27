import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON, Enum as SAEnum, ForeignKey
)
from sqlalchemy.orm import relationship, foreign
from app.database import Base
import enum


# --- Enums ---
class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AdminRole(str, enum.Enum):
    DIR_ADMIN = "DIR_ADMIN"
    MANAGEMENT = "MANAGEMENT"
    TECH_ADMIN = "TECH_ADMIN"
    RETAILER = "RETAILER"
    LOGISTICS = "LOGISTICS"


def _uuid():
    return str(uuid.uuid4())


# --- Tables ---
class Retailer(Base):
    __tablename__ = "retailer"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    bio = Column(Text, nullable=True)
    logo_url = Column(String, nullable=True)
    banner_url = Column(String, nullable=True)
    location = Column(String(255), nullable=True)
    primary_color = Column(String(20), default="zinc")
    status = Column(String(20), default="ACTIVE")
    rating = Column(Float, nullable=False, default=0.0)
    review_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    products = relationship("Product", back_populates="retailer")


class Category(Base):
    __tablename__ = "category"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False, unique=True)
    slug = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    image = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "product"

    id = Column(String, primary_key=True, default=_uuid)
    slug = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    brand = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    discount_price = Column(Float, nullable=True)
    images = Column(JSON, nullable=True)
    category_id = Column(String, ForeignKey("category.id", ondelete="SET NULL"), nullable=True)
    retailer_id = Column(String, ForeignKey("retailer.id", ondelete="SET NULL"), nullable=True)
    sub_category = Column(String(255), nullable=True)
    inventory = Column(Integer, nullable=False, default=0)
    vendor_id = Column(String, nullable=True)
    specifications = Column(JSON, nullable=True)
    rating = Column(Float, nullable=False, default=0.0)
    review_count = Column(Integer, nullable=False, default=0)
    is_new_arrival = Column(Boolean, nullable=False, default=False)
    is_flagship = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", back_populates="products")
    retailer = relationship("Retailer", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")
    reviews = relationship("Review", back_populates="product")


class User(Base):
    __tablename__ = "user"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    orders = relationship("Order", back_populates="customer")
    reviews = relationship("Review", back_populates="user")


class Order(Base):
    __tablename__ = "order"

    id = Column(String, primary_key=True, default=_uuid)
    order_number = Column(String(255), nullable=False, unique=True)
    status = Column(SAEnum(OrderStatus), nullable=False, default=OrderStatus.PENDING)
    total_amount = Column(Float, nullable=False)
    shipping_address = Column(JSON, nullable=False)
    customer_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_item"

    id = Column(String, primary_key=True, default=_uuid)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    product_id = Column(String, ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    order_id = Column(String, ForeignKey("order.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="order_items")
    order = relationship("Order", back_populates="items")


class Review(Base):
    __tablename__ = "review"

    id = Column(String, primary_key=True, default=_uuid)
    product_id = Column(String, ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    author = Column(String(255), nullable=False)
    rating = Column(Integer, nullable=False, default=0)
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=True)
    helpful = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="reviews")
    user = relationship("User", back_populates="reviews")


class AdminUser(Base):
    __tablename__ = "admin_user"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String(255), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    role = Column(SAEnum(AdminRole), nullable=False, default=AdminRole.LOGISTICS)
    vendor_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WishlistItem(Base):
    __tablename__ = "wishlist_item"

    id = Column(String, primary_key=True, default=_uuid)
    token = Column(String(255), nullable=False, index=True)
    product_id = Column(String, ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    product = relationship("Product")


class CartItem(Base):
    __tablename__ = "cart_item"

    id = Column(String, primary_key=True, default=_uuid)
    cart_token = Column(String(255), nullable=False, index=True)
    product_id = Column(String, ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    product = relationship("Product")


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id = Column(String, primary_key=True, default=_uuid)
    admin_id = Column(String, ForeignKey("admin_user.id", ondelete="SET NULL"), nullable=True)
    admin_email = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_token"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(255), nullable=False, unique=True, index=True)
    used = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AdminNotification(Base):
    __tablename__ = "admin_notification"

    id = Column(String, primary_key=True, default=_uuid)
    type = Column(String(50), nullable=False, default="info", index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)
    link = Column(String(500), nullable=True)
    read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SettingsCategory(str, enum.Enum):
    GLOBAL = "global"
    DESIGN = "design"
    TECHNICAL = "technical"
    OPTIONAL = "optional"
    DEVELOPER = "developer"
    LOGISTICS = "logistics"
    OTHER = "other"


class NewsletterSubscriber(Base):
    __tablename__ = "newsletter_subscriber"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String(255), nullable=False, unique=True)
    confirmed = Column(Boolean, nullable=False, default=False)
    confirm_token = Column(String(255), nullable=True)
    confirm_expires_at = Column(DateTime, nullable=True)
    unsubscribe_token = Column(String(255), nullable=True)
    tags = Column(JSON, nullable=True, default=list)
    preferences = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BroadcastCampaign(Base):
    __tablename__ = "broadcast_campaign"

    id = Column(String, primary_key=True, default=_uuid)
    subject = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    tag_filter = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="scheduled")  # scheduled, sending, sent, partial, failed
    scheduled_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    total_recipients = Column(Integer, nullable=False, default=0)
    sent_count = Column(Integer, nullable=False, default=0)
    opened_count = Column(Integer, nullable=False, default=0)
    clicked_count = Column(Integer, nullable=False, default=0)
    unsubscribed_count = Column(Integer, nullable=False, default=0)
    template_id = Column(String, ForeignKey("broadcast_template.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(String, ForeignKey("admin_user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    template = relationship("BroadcastTemplate", back_populates="campaigns")


class BroadcastEvent(Base):
    __tablename__ = "broadcast_event"

    id = Column(String, primary_key=True, default=_uuid)
    campaign_id = Column(String, ForeignKey("broadcast_campaign.id", ondelete="CASCADE"), nullable=False)
    subscriber_id = Column(String, ForeignKey("newsletter_subscriber.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(20), nullable=False)  # sent, opened, clicked, unsubscribed, bounced
    extra_data = Column(JSON, nullable=True)  # e.g. {"url": "https://..."} for clicks
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    campaign = relationship("BroadcastCampaign")
    subscriber = relationship("NewsletterSubscriber")


class BroadcastTemplate(Base):
    __tablename__ = "broadcast_template"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    created_by = Column(String, ForeignKey("admin_user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaigns = relationship("BroadcastCampaign", back_populates="template")


class Settings(Base):
    __tablename__ = "settings"

    id = Column(String, primary_key=True, default=_uuid)
    key = Column(String(255), nullable=False, unique=True)
    value = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, default="other", index=True)
    setting_type = Column(String(50), nullable=False, default="text")
    label = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    options = Column(JSON, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==============================================================================
# SYSTEM 1: REAL-TIME ORDER TRACKING
# ==============================================================================


class ShipmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class Shipment(Base):
    __tablename__ = "shipment"

    id = Column(String, primary_key=True, default=_uuid)
    order_id = Column(String, ForeignKey("order.id", ondelete="CASCADE"), nullable=False)
    tracking_number = Column(String(255), nullable=False, unique=True)
    carrier = Column(String(100), nullable=True)
    status = Column(String(30), nullable=False, default="PENDING")
    estimated_delivery = Column(DateTime, nullable=True)
    actual_delivery = Column(DateTime, nullable=True)
    origin = Column(String(255), nullable=True)
    destination = Column(String(255), nullable=True)
    weight_kg = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    delivery_agent_id = Column(String, ForeignKey("delivery_agent.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("Order")
    events = relationship("ShipmentEvent", back_populates="shipment", cascade="all, delete-orphan")
    delivery_agent = relationship("DeliveryAgent", back_populates="shipments")


class ShipmentEvent(Base):
    __tablename__ = "shipment_event"

    id = Column(String, primary_key=True, default=_uuid)
    shipment_id = Column(String, ForeignKey("shipment.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(30), nullable=False)
    location = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    shipment = relationship("Shipment", back_populates="events")


class DeliveryAgent(Base):
    __tablename__ = "delivery_agent"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    vehicle_type = Column(String(50), nullable=True)
    vehicle_number = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="AVAILABLE")  # AVAILABLE, BUSY, OFFLINE
    rating = Column(Float, nullable=False, default=0.0)
    total_deliveries = Column(Integer, nullable=False, default=0)
    current_latitude = Column(Float, nullable=True)
    current_longitude = Column(Float, nullable=True)
    last_location_update = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    shipments = relationship("Shipment", back_populates="delivery_agent")
    location_logs = relationship("DeliveryLocationLog", back_populates="agent", cascade="all, delete-orphan")


class DeliveryLocationLog(Base):
    __tablename__ = "delivery_location_log"

    id = Column(String, primary_key=True, default=_uuid)
    agent_id = Column(String, ForeignKey("delivery_agent.id", ondelete="CASCADE"), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)
    shipment_id = Column(String, ForeignKey("shipment.id", ondelete="SET NULL"), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    agent = relationship("DeliveryAgent", back_populates="location_logs")
    shipment = relationship("Shipment")


# ==============================================================================
# SYSTEM 2: ADVANCED VENDOR DASHBOARD
# ==============================================================================


class VendorAnalytics(Base):
    __tablename__ = "vendor_analytics"

    id = Column(String, primary_key=True, default=_uuid)
    retailer_id = Column(String, ForeignKey("retailer.id", ondelete="CASCADE"), nullable=False)
    period = Column(String(20), nullable=False)  # daily, weekly, monthly
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    total_revenue = Column(Float, nullable=False, default=0.0)
    total_orders = Column(Integer, nullable=False, default=0)
    total_products_sold = Column(Integer, nullable=False, default=0)
    unique_customers = Column(Integer, nullable=False, default=0)
    avg_order_value = Column(Float, nullable=False, default=0.0)
    conversion_rate = Column(Float, nullable=False, default=0.0)
    page_views = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    retailer = relationship("Retailer")


class VendorPayout(Base):
    __tablename__ = "vendor_payout"

    id = Column(String, primary_key=True, default=_uuid)
    retailer_id = Column(String, ForeignKey("retailer.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, nullable=False, default=0.0)
    net_amount = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, PROCESSING, COMPLETED, FAILED
    payment_method = Column(String(50), nullable=True)
    payment_reference = Column(String(255), nullable=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    retailer = relationship("Retailer")


class VendorActivityLog(Base):
    __tablename__ = "vendor_activity_log"

    id = Column(String, primary_key=True, default=_uuid)
    retailer_id = Column(String, ForeignKey("retailer.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    retailer = relationship("Retailer")


class VendorPerformanceCache(Base):
    __tablename__ = "vendor_performance_cache"

    id = Column(String, primary_key=True, default=_uuid)
    retailer_id = Column(String, ForeignKey("retailer.id", ondelete="CASCADE"), nullable=False)
    cache_key = Column(String(255), nullable=False)
    cache_data = Column(JSON, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    retailer = relationship("Retailer")


# ==============================================================================
# SYSTEM 3: AI SHOPPING ASSISTANT
# ==============================================================================


class AIConversation(Base):
    __tablename__ = "ai_conversation"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    context = Column(JSON, nullable=True)  # Stores shopping context
    extra_data = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("AIMessage", back_populates="conversation", cascade="all, delete-orphan")
    user = relationship("User")


class AIMessage(Base):
    __tablename__ = "ai_message"

    id = Column(String, primary_key=True, default=_uuid)
    conversation_id = Column(String, ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    extra_data = Column(JSON, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    conversation = relationship("AIConversation", back_populates="messages")


class UserPreferenceVector(Base):
    __tablename__ = "user_preference_vector"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    category_affinities = Column(JSON, nullable=True)  # {category_id: score}
    price_range_prefs = Column(JSON, nullable=True)  # {min, max}
    brand_affinities = Column(JSON, nullable=True)  # {brand: score}
    viewed_products = Column(JSON, nullable=True)  # [product_ids]
    purchased_categories = Column(JSON, nullable=True)
    search_terms = Column(JSON, nullable=True)  # [{term, count, last_searched}]
    embedding = Column(Text, nullable=True)  # JSON vector
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class RecommendationCache(Base):
    __tablename__ = "recommendation_cache"

    id = Column(String, primary_key=True, default=_uuid)
    context_type = Column(String(50), nullable=False, index=True)  # product, user, category
    context_id = Column(String, nullable=False)
    recommendations = Column(JSON, nullable=False)  # [{product_id, score, reason}]
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ==============================================================================
# SYSTEM 4: AFFILIATE & REFERRAL SYSTEM
# ==============================================================================


class Affiliate(Base):
    __tablename__ = "affiliate"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=True)
    code = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    type = Column(String(20), nullable=False, default="referral")  # referral, influencer, partner
    commission_rate = Column(Float, nullable=False, default=5.0)  # Percentage
    status = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, SUSPENDED, INACTIVE
    total_earned = Column(Float, nullable=False, default=0.0)
    total_paid = Column(Float, nullable=False, default=0.0)
    total_clicks = Column(Integer, nullable=False, default=0)
    total_conversions = Column(Integer, nullable=False, default=0)
    wallet_balance = Column(Float, nullable=False, default=0.0)
    payout_method = Column(String(50), nullable=True)
    payout_details = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
    commissions = relationship("AffiliateCommission", back_populates="affiliate", cascade="all, delete-orphan")
    payouts = relationship("AffiliatePayout", back_populates="affiliate", cascade="all, delete-orphan")


class AffiliateCommission(Base):
    __tablename__ = "affiliate_commission"

    id = Column(String, primary_key=True, default=_uuid)
    affiliate_id = Column(String, ForeignKey("affiliate.id", ondelete="CASCADE"), nullable=False)
    order_id = Column(String, ForeignKey("order.id", ondelete="SET NULL"), nullable=True)
    product_id = Column(String, ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    order_amount = Column(Float, nullable=False)
    commission_rate = Column(Float, nullable=False)
    commission_amount = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, APPROVED, PAID, CANCELLED
    coupon_code = Column(String(50), nullable=True)
    referred_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    affiliate = relationship("Affiliate", back_populates="commissions")
    order = relationship("Order")
    product = relationship("Product")


class ReferralEvent(Base):
    __tablename__ = "referral_event"

    id = Column(String, primary_key=True, default=_uuid)
    affiliate_id = Column(String, ForeignKey("affiliate.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(30), nullable=False)  # click, signup, order, conversion
    referrer_code = Column(String(50), nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    affiliate = relationship("Affiliate")


class AffiliatePayout(Base):
    __tablename__ = "affiliate_payout"

    id = Column(String, primary_key=True, default=_uuid)
    affiliate_id = Column(String, ForeignKey("affiliate.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, nullable=False, default=0.0)
    net_amount = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, PROCESSING, COMPLETED, FAILED
    payment_method = Column(String(50), nullable=True)
    payment_reference = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    affiliate = relationship("Affiliate", back_populates="payouts")


# ==============================================================================
# SYSTEM 5: MULTI-PAYMENT & WALLET SYSTEM
# ==============================================================================


class Wallet(Base):
    __tablename__ = "wallet"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    balance = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default="NGN")
    status = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, FROZEN, CLOSED
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
    transactions = relationship("WalletTransaction", back_populates="wallet", cascade="all, delete-orphan", foreign_keys="WalletTransaction.wallet_id")


class WalletTransaction(Base):
    __tablename__ = "wallet_transaction"

    id = Column(String, primary_key=True, default=_uuid)
    wallet_id = Column(String, ForeignKey("wallet.id", ondelete="CASCADE"), nullable=False)
    transaction_type = Column(String(30), nullable=False)  # deposit, withdrawal, payment, refund, commission, fee
    amount = Column(Float, nullable=False)
    balance_before = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="NGN")
    reference = Column(String(255), nullable=True)
    description = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="COMPLETED")  # PENDING, COMPLETED, FAILED
    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    wallet = relationship("Wallet", back_populates="transactions", foreign_keys=[wallet_id])


class PaymentProvider(Base):
    __tablename__ = "payment_provider"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(50), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)
    config = Column(JSON, nullable=True)  # Provider-specific config
    supported_currencies = Column(JSON, nullable=True)
    fee_percentage = Column(Float, nullable=False, default=0.0)
    fee_fixed = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentLog(Base):
    __tablename__ = "payment_log"

    id = Column(String, primary_key=True, default=_uuid)
    order_id = Column(String, ForeignKey("order.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(50), nullable=False)
    transaction_reference = Column(String(255), nullable=True)
    transaction_type = Column(String(30), nullable=False)  # payment, refund, escrow
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="NGN")
    status = Column(String(20), nullable=False)  # initiated, successful, failed, refunded
    request_data = Column(JSON, nullable=True)
    response_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    order = relationship("Order")


class EscrowTransaction(Base):
    __tablename__ = "escrow_transaction"

    id = Column(String, primary_key=True, default=_uuid)
    order_id = Column(String, ForeignKey("order.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="NGN")
    status = Column(String(20), nullable=False, default="HELD")  # HELD, RELEASED, REFUNDED, DISPUTED
    payer_id = Column(String, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    payee_id = Column(String, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    release_condition = Column(String(100), nullable=True)  # delivery_confirmed, auto_release_date
    auto_release_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("Order")
    payer = relationship("User", foreign_keys=[payer_id])
    payee = relationship("User", foreign_keys=[payee_id])


class PaymentSplit(Base):
    __tablename__ = "payment_split"

    id = Column(String, primary_key=True, default=_uuid)
    order_id = Column(String, ForeignKey("order.id", ondelete="CASCADE"), nullable=False)
    recipient_id = Column(String, ForeignKey("retailer.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)
    percentage = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, PAID, FAILED
    payment_reference = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("Order")
    recipient = relationship("Retailer")


# ==============================================================================
# SYSTEM 6: ADVANCED CART INFRASTRUCTURE
# ==============================================================================


class PersistentCart(Base):
    __tablename__ = "persistent_cart"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=True)
    cart_token = Column(String(255), nullable=False, unique=True, index=True)
    items = Column(JSON, nullable=True, default=list)  # [{product_id, quantity, added_at}]
    extra_data = Column(JSON, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
    activities = relationship("CartActivity", back_populates="cart", cascade="all, delete-orphan",
        primaryjoin="PersistentCart.cart_token == foreign(CartActivity.cart_token)")
    recommendations = relationship("CartRecommendation", back_populates="cart", cascade="all, delete-orphan",
        primaryjoin="PersistentCart.cart_token == foreign(CartRecommendation.cart_token)")


class CartActivity(Base):
    __tablename__ = "cart_activity"

    id = Column(String, primary_key=True, default=_uuid)
    cart_token = Column(String(255), nullable=False, index=True)
    activity_type = Column(String(30), nullable=False)  # add, remove, update, view, abandon, recover
    product_id = Column(String, ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    quantity = Column(Integer, nullable=True)
    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    cart = relationship("PersistentCart", back_populates="activities",
        primaryjoin="foreign(CartActivity.cart_token) == PersistentCart.cart_token")
    product = relationship("Product")


class AbandonedCart(Base):
    __tablename__ = "abandoned_cart"

    id = Column(String, primary_key=True, default=_uuid)
    cart_token = Column(String(255), nullable=False, index=True)
    user_id = Column(String, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    email = Column(String(255), nullable=True)
    items = Column(JSON, nullable=False)
    total_value = Column(Float, nullable=False, default=0.0)
    reminder_sent = Column(Boolean, nullable=False, default=False)
    reminder_count = Column(Integer, nullable=False, default=0)
    last_reminder_at = Column(DateTime, nullable=True)
    recovered = Column(Boolean, nullable=False, default=False)
    recovery_order_id = Column(String, ForeignKey("order.id", ondelete="SET NULL"), nullable=True)
    recovered_at = Column(DateTime, nullable=True)
    abandoned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
    recovery_order = relationship("Order")


class CartRecommendation(Base):
    __tablename__ = "cart_recommendation"

    id = Column(String, primary_key=True, default=_uuid)
    cart_token = Column(String(255), nullable=False, index=True)
    product_id = Column(String, ForeignKey("product.id", ondelete="SET NULL"), nullable=False)
    reason = Column(String(255), nullable=True)  # complementary, popular, frequently_bought
    score = Column(Float, nullable=False, default=0.0)
    shown = Column(Boolean, nullable=False, default=False)
    clicked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    cart = relationship("PersistentCart", back_populates="recommendations",
        primaryjoin="foreign(CartRecommendation.cart_token) == PersistentCart.cart_token")
    product = relationship("Product")


# ==============================================================================
# SYSTEM 7: AI-POWERED SMART SEARCH
# ==============================================================================


class SearchHistory(Base):
    __tablename__ = "search_history"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String(255), nullable=True)
    query = Column(String(500), nullable=False)
    refined_query = Column(String(500), nullable=True)
    result_count = Column(Integer, nullable=False, default=0)
    clicked_product_id = Column(String, nullable=True)
    search_type = Column(String(30), nullable=False, default="text")  # text, semantic, voice
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User")


class SearchTrend(Base):
    __tablename__ = "search_trend"

    id = Column(String, primary_key=True, default=_uuid)
    query = Column(String(500), nullable=False)
    normalized_query = Column(String(500), nullable=False, index=True)
    count = Column(Integer, nullable=False, default=0)
    unique_users = Column(Integer, nullable=False, default=0)
    period = Column(String(20), nullable=False)  # daily, weekly, monthly
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SearchEmbedding(Base):
    __tablename__ = "search_embedding"

    id = Column(String, primary_key=True, default=_uuid)
    product_id = Column(String, ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    embedding = Column(Text, nullable=False)  # JSON array of floats
    model = Column(String(100), nullable=False)  # Which embedding model was used
    chunk_text = Column(Text, nullable=True)  # The text that was embedded
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    product = relationship("Product")


class SearchClickAnalytics(Base):
    __tablename__ = "search_click_analytics"

    id = Column(String, primary_key=True, default=_uuid)
    search_id = Column(String, ForeignKey("search_history.id", ondelete="SET NULL"), nullable=True)
    product_id = Column(String, ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    position = Column(Integer, nullable=True)
    clicked = Column(Boolean, nullable=False, default=True)
    dwell_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    search = relationship("SearchHistory")
    product = relationship("Product")


# ==============================================================================
# SYSTEM 8: MODERN PRODUCT REVIEW SYSTEM
# ==============================================================================


class ReviewMedia(Base):
    __tablename__ = "review_media"

    id = Column(String, primary_key=True, default=_uuid)
    review_id = Column(String, ForeignKey("review.id", ondelete="CASCADE"), nullable=False)
    media_type = Column(String(20), nullable=False)  # image, video
    url = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500), nullable=True)
    is_cover = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    review = relationship("Review")


class ReviewReaction(Base):
    __tablename__ = "review_reaction"

    id = Column(String, primary_key=True, default=_uuid)
    review_id = Column(String, ForeignKey("review.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    reaction_type = Column(String(20), nullable=False)  # helpful, funny, agree
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    review = relationship("Review")
    user = relationship("User")


class ReviewSentiment(Base):
    __tablename__ = "review_sentiment"

    id = Column(String, primary_key=True, default=_uuid)
    review_id = Column(String, ForeignKey("review.id", ondelete="CASCADE"), nullable=False, unique=True)
    sentiment = Column(String(20), nullable=False)  # positive, negative, neutral, mixed
    score = Column(Float, nullable=False, default=0.0)  # -1.0 to 1.0
    keywords = Column(JSON, nullable=True)  # Top keywords from review
    categories = Column(JSON, nullable=True)  # Detected categories
    model = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    review = relationship("Review")


class ReviewModeration(Base):
    __tablename__ = "review_moderation"

    id = Column(String, primary_key=True, default=_uuid)
    review_id = Column(String, ForeignKey("review.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, APPROVED, REJECTED, FLAGGED
    reason = Column(String(100), nullable=True)  # spam, offensive, fake, inappropriate
    ai_flags = Column(JSON, nullable=True)  # What the AI moderation found
    reviewed_by = Column(String, ForeignKey("admin_user.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    review = relationship("Review")
    reviewer = relationship("AdminUser")


# ==============================================================================
# SYSTEM 9: REAL-TIME NOTIFICATION INFRASTRUCTURE
# ==============================================================================


class NotificationQueue(Base):
    __tablename__ = "notification_queue"

    id = Column(String, primary_key=True, default=_uuid)
    recipient_type = Column(String(20), nullable=False)  # admin, customer, vendor
    recipient_id = Column(String, nullable=True)
    channel = Column(String(50), nullable=False, default="in_app")  # in_app, email, push, sms
    notification_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)
    priority = Column(Integer, nullable=False, default=0)  # 0=normal, 1=high, 2=urgent
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, SENT, FAILED
    sent_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PushSubscription(Base):
    __tablename__ = "push_subscription"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=True)
    endpoint = Column(String(500), nullable=False, unique=True)
    keys = Column(JSON, nullable=False)
    user_agent = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class UserNotificationPreferences(Base):
    __tablename__ = "user_notification_preferences"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)
    email_notifications = Column(Boolean, nullable=False, default=True)
    push_notifications = Column(Boolean, nullable=False, default=True)
    sms_notifications = Column(Boolean, nullable=False, default=False)
    order_updates = Column(Boolean, nullable=False, default=True)
    promotions = Column(Boolean, nullable=False, default=True)
    newsletter = Column(Boolean, nullable=False, default=True)
    cart_reminders = Column(Boolean, nullable=False, default=True)
    review_reminders = Column(Boolean, nullable=False, default=False)
    quiet_hours_start = Column(String(5), nullable=True)  # HH:MM
    quiet_hours_end = Column(String(5), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_delivery_log"

    id = Column(String, primary_key=True, default=_uuid)
    notification_id = Column(String, ForeignKey("notification_queue.id", ondelete="SET NULL"), nullable=True)
    channel = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)  # sent, delivered, failed, bounced
    error_message = Column(Text, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    notification = relationship("NotificationQueue")


# ==============================================================================
# SYSTEM 10: ENTERPRISE COMMERCE INTELLIGENCE
# ==============================================================================


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshot"

    id = Column(String, primary_key=True, default=_uuid)
    snapshot_type = Column(String(30), nullable=False, index=True)  # daily, weekly, monthly
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    data = Column(JSON, nullable=False)
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CustomerLifetimeValue(Base):
    __tablename__ = "customer_lifetime_value"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)
    total_spent = Column(Float, nullable=False, default=0.0)
    total_orders = Column(Integer, nullable=False, default=0)
    avg_order_value = Column(Float, nullable=False, default=0.0)
    predicted_clv = Column(Float, nullable=False, default=0.0)  # Predicted lifetime value
    recency_days = Column(Integer, nullable=True)  # Days since last order
    frequency = Column(Integer, nullable=False, default=0)  # Orders per month
    monetary_score = Column(Float, nullable=False, default=0.0)  # RFM score component
    segment = Column(String(30), nullable=True)  # champions, loyal, at_risk, etc.
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class FraudDetectionEvent(Base):
    __tablename__ = "fraud_detection_event"

    id = Column(String, primary_key=True, default=_uuid)
    event_type = Column(String(50), nullable=False)  # rapid_orders, unusual_location, multiple_accounts, etc.
    order_id = Column(String, ForeignKey("order.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(String, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    ip_address = Column(String(50), nullable=True)
    score = Column(Float, nullable=False, default=0.0)  # 0.0 (safe) to 1.0 (definitely fraud)
    indicators = Column(JSON, nullable=True)  # What triggered the detection
    action_taken = Column(String(50), nullable=True)  # flagged, blocked, reviewed, ignored
    reviewed_by = Column(String, ForeignKey("admin_user.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    order = relationship("Order")
    user = relationship("User")
    reviewer = relationship("AdminUser")


class PredictiveForecast(Base):
    __tablename__ = "predictive_forecast"

    id = Column(String, primary_key=True, default=_uuid)
    forecast_type = Column(String(30), nullable=False, index=True)  # revenue, orders, customers
    period = Column(String(20), nullable=False)  # daily, weekly, monthly
    forecast_date = Column(DateTime, nullable=False)
    predicted_value = Column(Float, nullable=False)
    lower_bound = Column(Float, nullable=True)
    upper_bound = Column(Float, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)  # 0.0 to 1.0
    model = Column(String(100), nullable=True)  # Which model generated this
    features_used = Column(JSON, nullable=True)
    actual_value = Column(Float, nullable=True)  # Filled in later when actual data is available
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
