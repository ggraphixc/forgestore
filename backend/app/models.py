import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON, Enum as SAEnum, ForeignKey
)
from sqlalchemy.orm import relationship
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
