"""AI Shopping Assistant — System 3

Multimodal AI-powered shopping assistant with:
- Product catalog context injection
- Image understanding via MiMo-V2.5 multimodal
- Tool-use for product search, comparison, recommendations
- Conversation memory with context tracking
"""
import json
import logging
import re
import uuid
from datetime import datetime
from app.utils import utcnow
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.models import (
    AIConversation, AIMessage, UserPreferenceVector, RecommendationCache,
    Product, Category, User, Review, Order, OrderItem, Retailer,
    AdminUser,
)
from app.config import get_settings

logger = logging.getLogger("forgestore.ai")


class ConversationMemory:
    """Manages conversation history and context for the AI assistant."""

    MAX_HISTORY = 50

    def __init__(self, db: Session):
        self.db = db

    def get_or_create_conversation(self, session_id: str, user_id: Optional[str] = None,
                                   title: Optional[str] = None) -> AIConversation:
        """Get existing active conversation or create a new one."""
        conversation = self.db.query(AIConversation).filter(
            AIConversation.session_id == session_id,
            AIConversation.is_active == True,
        ).first()

        if not conversation:
            conversation = AIConversation(
                user_id=user_id,
                session_id=session_id,
                title=title or "Shopping Assistant Chat",
                context={},
            )
            self.db.add(conversation)
            self.db.commit()
            self.db.refresh(conversation)

        return conversation

    def add_message(self, conversation_id: str, role: str, content: str,
                    metadata: Optional[dict] = None, tokens_used: Optional[int] = None) -> AIMessage:
        """Add a message to the conversation."""
        message = AIMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata=metadata or {},
            tokens_used=tokens_used,
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def get_history(self, conversation_id: str, limit: int = 20) -> list[dict]:
        """Get conversation history formatted for LLM context."""
        messages = self.db.query(AIMessage).filter(
            AIMessage.conversation_id == conversation_id
        ).order_by(AIMessage.created_at.asc()).limit(limit).all()

        return [
            {"role": m.role, "content": m.content, "extra_data": m.extra_data}
            for m in messages
        ]

    def update_context(self, conversation_id: str, context_updates: dict):
        """Update the conversation context."""
        conversation = self.db.query(AIConversation).filter(
            AIConversation.id == conversation_id
        ).first()
        if conversation:
            current = conversation.context or {}
            current.update(context_updates)
            conversation.context = current
            self.db.commit()

    def get_context(self, conversation_id: str) -> dict:
        """Get the conversation context."""
        conversation = self.db.query(AIConversation).filter(
            AIConversation.id == conversation_id
        ).first()
        return conversation.context or {} if conversation else {}


class AIChatService:
    """AI-powered conversational shopping assistant with multimodal support."""

    def __init__(self, db: Session):
        self.db = db
        self.memory = ConversationMemory(db)
        self.settings = get_settings()

    def _get_catalog_context(self) -> str:
        """Build product catalog context for the AI."""
        try:
            products = self.db.query(Product).filter(
                Product.inventory > 0
            ).order_by(Product.rating.desc(), Product.review_count.desc()).limit(30).all()

            categories = self.db.query(Category).limit(20).all()

            catalog = {
                "categories": [{"name": c.name, "slug": c.slug} for c in categories],
                "top_products": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "brand": p.brand or "",
                        "category": p.category.name if p.category else "",
                        "price": p.price,
                        "discount_price": p.discount_price,
                        "rating": p.rating,
                        "review_count": p.review_count,
                        "in_stock": p.inventory > 0,
                        "description": (p.description or "")[:120],
                    }
                    for p in products
                ],
            }
            return json.dumps(catalog, default=str)
        except Exception as e:
            logger.error(f"Catalog context error: {e}")
            return json.dumps({"categories": [], "top_products": []})

    def _get_user_context(self, user_id: Optional[str]) -> str:
        """Build user-specific context (preferences, order history)."""
        if not user_id:
            return json.dumps({"user": "anonymous", "preferences": {}, "recent_orders": []})

        try:
            user = self.db.query(User).filter(User.id == user_id).first()
            preferences = {}
            recent_orders = []

            try:
                pref_vector = self.db.query(UserPreferenceVector).filter(
                    UserPreferenceVector.user_id == user_id
                ).first()
                if pref_vector:
                    preferences = {
                        "category_affinities": pref_vector.category_affinities or {},
                        "price_range_prefs": pref_vector.price_range_prefs or {},
                    }
            except Exception as e:
                logger.warning(f"Preference vector query failed (non-fatal): {e}")

            # Get recent order history for context
            orders = self.db.query(Order).filter(
                Order.customer_id == user_id
            ).order_by(Order.created_at.desc()).limit(5).all()

            for o in orders:
                items = self.db.query(OrderItem).filter(OrderItem.order_id == o.id).all()
                recent_orders.append({
                    "order_number": o.order_number,
                    "total": o.total_amount,
                    "items": [
                        {"name": i.product.name if i.product else "Unknown", "quantity": i.quantity}
                        for i in items
                    ],
                })

            return json.dumps({
                "user": {"name": user.name, "email": user.email} if user else {"user_id": user_id},
                "preferences": preferences,
                "recent_orders": recent_orders,
            }, default=str)
        except Exception as e:
            logger.warning(f"User context error (non-fatal): {e}")
            return json.dumps({"user": "anonymous", "preferences": {}, "recent_orders": []})

    def _get_admin_context(self) -> str:
        """Build admin-specific context with full portal data."""
        from app.utils import utcnow
        from datetime import timedelta

        try:
            now = utcnow()
            thirty_days_ago = now - timedelta(days=30)
            seven_days_ago = now - timedelta(days=7)

            # ── Revenue & Orders ──
            total_revenue = self.db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
                Order.status.in_(["DELIVERED", "PAID"]),
                Order.created_at >= thirty_days_ago,
            ).scalar()

            total_orders = self.db.query(func.count(Order.id)).filter(
                Order.created_at >= thirty_days_ago
            ).scalar()
            pending_orders = self.db.query(func.count(Order.id)).filter(
                Order.status.in_(["PENDING", "PROCESSING"])
            ).scalar()
            cancelled_orders = self.db.query(func.count(Order.id)).filter(
                Order.status == "CANCELLED"
            ).scalar()
            shipped_orders = self.db.query(func.count(Order.id)).filter(
                Order.status == "SHIPPED"
            ).scalar()
            delivered_orders = self.db.query(func.count(Order.id)).filter(
                Order.status == "DELIVERED"
            ).scalar()
            today_orders = self.db.query(func.count(Order.id)).filter(
                Order.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)
            ).scalar()

            # ── Products ──
            total_products = self.db.query(func.count(Product.id)).scalar()
            low_stock = self.db.query(func.count(Product.id)).filter(
                Product.inventory > 0, Product.inventory < 10
            ).scalar()
            out_of_stock = self.db.query(func.count(Product.id)).filter(
                Product.inventory == 0
            ).scalar()
            total_inventory = self.db.query(func.coalesce(func.sum(Product.inventory), 0)).scalar()
            total_views = self.db.query(func.coalesce(func.sum(Product.views_count), 0)).scalar()
            total_sold = self.db.query(func.coalesce(func.sum(Product.sold_count), 0)).scalar()

            # ── Vendors / Retailers ──
            total_vendors = self.db.query(func.count(Retailer.id)).scalar()
            active_vendors = self.db.query(func.count(Retailer.id)).filter(
                Retailer.status == "APPROVED"
            ).scalar()
            pending_vendors = self.db.query(func.count(Retailer.id)).filter(
                Retailer.status == "PENDING"
            ).scalar()

            # ── Customers ──
            total_customers = self.db.query(func.count(User.id)).scalar()
            new_customers_30d = self.db.query(func.count(User.id)).filter(
                User.created_at >= thirty_days_ago
            ).scalar()
            new_customers_today = self.db.query(func.count(User.id)).filter(
                User.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)
            ).scalar()

            # ── Newsletter Subscribers ──
            try:
                from app.models import NewsletterSubscriber
                total_subscribers = self.db.query(func.count(NewsletterSubscriber.id)).scalar()
                active_subscribers = self.db.query(func.count(NewsletterSubscriber.id)).filter(
                    NewsletterSubscriber.status == "ACTIVE"
                ).scalar()
                new_subscribers_30d = self.db.query(func.count(NewsletterSubscriber.id)).filter(
                    NewsletterSubscriber.created_at >= thirty_days_ago
                ).scalar()
                new_subscribers_today = self.db.query(func.count(NewsletterSubscriber.id)).filter(
                    NewsletterSubscriber.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)
                ).scalar()
            except Exception:
                total_subscribers = active_subscribers = new_subscribers_30d = new_subscribers_today = 0

            # ── Shipments / Logistics ──
            try:
                from app.models import Shipment, DeliveryAgent
                total_shipments = self.db.query(func.count(Shipment.id)).scalar()
                pending_shipments = self.db.query(func.count(Shipment.id)).filter(
                    Shipment.status == "PENDING"
                ).scalar()
                in_transit_shipments = self.db.query(func.count(Shipment.id)).filter(
                    Shipment.status == "IN_TRANSIT"
                ).scalar()
                delivered_shipments = self.db.query(func.count(Shipment.id)).filter(
                    Shipment.status == "DELIVERED"
                ).scalar()
                total_drivers = self.db.query(func.count(DeliveryAgent.id)).scalar()
                active_drivers = self.db.query(func.count(DeliveryAgent.id)).filter(
                    DeliveryAgent.is_available == True
                ).scalar()
            except Exception:
                total_shipments = pending_shipments = in_transit_shipments = delivered_shipments = 0
                total_drivers = active_drivers = 0

            # ── Ad Campaigns ──
            try:
                from app.models import AdCampaign, PromoAd
                total_ad_campaigns = self.db.query(func.count(AdCampaign.id)).scalar()
                active_ad_campaigns = self.db.query(func.count(AdCampaign.id)).filter(
                    AdCampaign.status == "ACTIVE"
                ).scalar()
                total_promo_ads = self.db.query(func.count(PromoAd.id)).scalar()
            except Exception:
                total_ad_campaigns = active_ad_campaigns = total_promo_ads = 0

            # ── Support Tickets ──
            try:
                from app.models import SupportTicket
                total_tickets = self.db.query(func.count(SupportTicket.id)).scalar()
                open_tickets = self.db.query(func.count(SupportTicket.id)).filter(
                    SupportTicket.status.in_(["OPEN", "IN_PROGRESS"])
                ).scalar()
                resolved_tickets = self.db.query(func.count(SupportTicket.id)).filter(
                    SupportTicket.status == "RESOLVED"
                ).scalar()
            except Exception:
                total_tickets = open_tickets = resolved_tickets = 0

            # ── Reviews ──
            try:
                from app.models import Review
                total_reviews = self.db.query(func.count(Review.id)).scalar()
                avg_rating = self.db.query(func.avg(Review.rating)).scalar()
            except Exception:
                total_reviews = 0
                avg_rating = 0

            # ── Categories ──
            try:
                from app.models import Category
                total_categories = self.db.query(func.count(Category.id)).scalar()
            except Exception:
                total_categories = 0

            return json.dumps({
                "period": "last_30_days",
                "revenue": {"total": float(total_revenue or 0), "currency": "NGN"},
                "orders": {
                    "total_30d": total_orders or 0,
                    "today": today_orders or 0,
                    "pending": pending_orders or 0,
                    "shipped": shipped_orders or 0,
                    "delivered": delivered_orders or 0,
                    "cancelled": cancelled_orders or 0,
                },
                "products": {
                    "total": total_products or 0,
                    "low_stock": low_stock or 0,
                    "out_of_stock": out_of_stock or 0,
                    "total_inventory": total_inventory or 0,
                    "total_views": total_views or 0,
                    "total_sold": total_sold or 0,
                },
                "vendors": {
                    "total": total_vendors or 0,
                    "active": active_vendors or 0,
                    "pending": pending_vendors or 0,
                },
                "customers": {
                    "total": total_customers or 0,
                    "new_30d": new_customers_30d or 0,
                    "new_today": new_customers_today or 0,
                },
                "newsletter": {
                    "total_subscribers": total_subscribers or 0,
                    "active": active_subscribers or 0,
                    "new_30d": new_subscribers_30d or 0,
                    "new_today": new_subscribers_today or 0,
                },
                "logistics": {
                    "total_shipments": total_shipments or 0,
                    "pending": pending_shipments or 0,
                    "in_transit": in_transit_shipments or 0,
                    "delivered": delivered_shipments or 0,
                    "total_drivers": total_drivers or 0,
                    "active_drivers": active_drivers or 0,
                },
                "ads": {
                    "total_campaigns": total_ad_campaigns or 0,
                    "active_campaigns": active_ad_campaigns or 0,
                    "total_promo_ads": total_promo_ads or 0,
                },
                "support": {
                    "total_tickets": total_tickets or 0,
                    "open": open_tickets or 0,
                    "resolved": resolved_tickets or 0,
                },
                "reviews": {
                    "total": total_reviews or 0,
                    "average_rating": round(float(avg_rating or 0), 1),
                },
                "categories": total_categories or 0,
            }, default=str)
        except Exception as e:
            logger.error(f"Admin context error: {e}")
            return json.dumps({"error": "Could not load admin context", "period": "last_30_days"})

    def _get_vendor_context(self, vendor_id: str) -> str:
        """Build vendor-specific context with their own products, orders, earnings."""
        from datetime import timedelta

        try:
            now = utcnow()
            thirty_days_ago = now - timedelta(days=30)

            retailer = self.db.query(Retailer).filter(Retailer.id == vendor_id).first()
            retailer_name = retailer.business_name if retailer else "Unknown"

            # My products
            my_products = self.db.query(Product).filter(Product.vendor_id == vendor_id).all()
            total_products = len(my_products)
            active_products = sum(1 for p in my_products if p.inventory > 0)
            low_stock = sum(1 for p in my_products if 0 < p.inventory < 10)
            out_of_stock = sum(1 for p in my_products if p.inventory == 0)
            total_inventory = sum(p.inventory for p in my_products)
            total_views = sum(p.views_count or 0 for p in my_products)
            total_sold = sum(p.sold_count or 0 for p in my_products)

            # My orders (orders containing this vendor's products)
            product_ids = [p.id for p in my_products]
            if product_ids:
                my_order_items = self.db.query(OrderItem).filter(
                    OrderItem.product_id.in_(product_ids)
                ).all()
                order_ids = list(set(oi.order_id for oi in my_order_items))
                my_orders = self.db.query(Order).filter(Order.id.in_(order_ids)).all() if order_ids else []
            else:
                my_orders = []
                my_order_items = []

            total_orders = len(my_orders)
            pending_orders = sum(1 for o in my_orders if o.status in ["PENDING", "PROCESSING"])
            delivered_orders = sum(1 for o in my_orders if o.status == "DELIVERED")
            cancelled_orders = sum(1 for o in my_orders if o.status == "CANCELLED")

            # Revenue
            revenue_30d = sum(
                float(o.total_amount or 0) for o in my_orders
                if o.status in ["DELIVERED", "PAID"] and o.created_at and o.created_at >= thirty_days_ago
            )

            # Reviews on my products
            if product_ids:
                my_reviews = self.db.query(Review).filter(Review.product_id.in_(product_ids)).all()
            else:
                my_reviews = []
            avg_rating = sum(r.rating for r in my_reviews) / len(my_reviews) if my_reviews else 0

            # Ad campaigns
            try:
                from app.models import AdCampaign
                my_ads = self.db.query(AdCampaign).filter(AdCampaign.vendor_id == vendor_id).all()
                active_ads = sum(1 for a in my_ads if a.status == "ACTIVE")
            except Exception:
                my_ads = []
                active_ads = 0

            return json.dumps({
                "vendor": {"name": retailer_name, "id": vendor_id},
                "products": {
                    "total": total_products,
                    "active": active_products,
                    "low_stock": low_stock,
                    "out_of_stock": out_of_stock,
                    "total_inventory": total_inventory,
                    "total_views": total_views,
                    "total_sold": total_sold,
                },
                "orders": {
                    "total": total_orders,
                    "pending": pending_orders,
                    "delivered": delivered_orders,
                    "cancelled": cancelled_orders,
                },
                "revenue_30d": revenue_30d,
                "reviews": {
                    "total": len(my_reviews),
                    "average_rating": round(avg_rating, 1),
                },
                "ads": {
                    "total": len(my_ads),
                    "active": active_ads,
                },
            }, default=str)
        except Exception as e:
            logger.error(f"Vendor context error: {e}")
            return json.dumps({"error": "Could not load vendor context"})

    def _get_logistics_context(self) -> str:
        """Build logistics-specific context with shipments, drivers, delivery status."""
        from datetime import timedelta

        try:
            now = utcnow()
            thirty_days_ago = now - timedelta(days=7)

            try:
                from app.models import Shipment, DeliveryAgent

                # Shipments
                total_shipments = self.db.query(func.count(Shipment.id)).scalar() or 0
                pending_shipments = self.db.query(func.count(Shipment.id)).filter(
                    Shipment.status == "PENDING"
                ).scalar() or 0
                in_transit = self.db.query(func.count(Shipment.id)).filter(
                    Shipment.status == "IN_TRANSIT"
                ).scalar() or 0
                delivered_shipments = self.db.query(func.count(Shipment.id)).filter(
                    Shipment.status == "DELIVERED"
                ).scalar() or 0
                failed_shipments = self.db.query(func.count(Shipment.id)).filter(
                    Shipment.status == "FAILED"
                ).scalar() or 0

                # Drivers
                total_drivers = self.db.query(func.count(DeliveryAgent.id)).scalar() or 0
                active_drivers = self.db.query(func.count(DeliveryAgent.id)).filter(
                    DeliveryAgent.is_available == True
                ).scalar() or 0

                # Recent shipments (last 7 days)
                recent_shipments = self.db.query(Shipment).filter(
                    Shipment.created_at >= thirty_days_ago
                ).order_by(Shipment.created_at.desc()).limit(10).all()
                recent_list = [
                    {"tracking": s.tracking_number, "status": s.status, "order_id": s.order_id}
                    for s in recent_shipments
                ]
            except Exception:
                total_shipments = pending_shipments = in_transit = delivered_shipments = failed_shipments = 0
                total_drivers = active_drivers = 0
                recent_list = []

            return json.dumps({
                "shipments": {
                    "total": total_shipments,
                    "pending": pending_shipments,
                    "in_transit": in_transit,
                    "delivered": delivered_shipments,
                    "failed": failed_shipments,
                },
                "drivers": {
                    "total": total_drivers,
                    "active": active_drivers,
                },
                "recent_shipments": recent_list,
            }, default=str)
        except Exception as e:
            logger.error(f"Logistics context error: {e}")
            return json.dumps({"error": "Could not load logistics context"})

    def _get_management_context(self) -> str:
        """Build management context — orders, vendors, customers, ads, products."""
        from datetime import timedelta

        try:
            now = utcnow()
            thirty_days_ago = now - timedelta(days=30)

            # Revenue & Orders
            total_revenue = self.db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
                Order.status.in_(["DELIVERED", "PAID"]),
                Order.created_at >= thirty_days_ago,
            ).scalar()
            total_orders = self.db.query(func.count(Order.id)).filter(
                Order.created_at >= thirty_days_ago
            ).scalar() or 0
            pending_orders = self.db.query(func.count(Order.id)).filter(
                Order.status.in_(["PENDING", "PROCESSING"])
            ).scalar() or 0
            delivered_orders = self.db.query(func.count(Order.id)).filter(
                Order.status == "DELIVERED"
            ).scalar() or 0

            # Products
            total_products = self.db.query(func.count(Product.id)).scalar() or 0
            low_stock = self.db.query(func.count(Product.id)).filter(
                Product.inventory > 0, Product.inventory < 10
            ).scalar() or 0

            # Vendors
            total_vendors = self.db.query(func.count(Retailer.id)).scalar() or 0
            pending_vendors = self.db.query(func.count(Retailer.id)).filter(
                Retailer.status == "PENDING"
            ).scalar() or 0

            # Customers
            total_customers = self.db.query(func.count(User.id)).scalar() or 0
            new_customers_30d = self.db.query(func.count(User.id)).filter(
                User.created_at >= thirty_days_ago
            ).scalar() or 0

            # Ads
            try:
                from app.models import AdCampaign, PromoAd
                active_ads = self.db.query(func.count(AdCampaign.id)).filter(
                    AdCampaign.status == "ACTIVE"
                ).scalar() or 0
                total_promos = self.db.query(func.count(PromoAd.id)).scalar() or 0
            except Exception:
                active_ads = total_promos = 0

            return json.dumps({
                "period": "last_30_days",
                "revenue": {"total": float(total_revenue or 0), "currency": "NGN"},
                "orders": {"total_30d": total_orders, "pending": pending_orders, "delivered": delivered_orders},
                "products": {"total": total_products, "low_stock": low_stock},
                "vendors": {"total": total_vendors, "pending": pending_vendors},
                "customers": {"total": total_customers, "new_30d": new_customers_30d},
                "ads": {"active": active_ads, "promo_ads": total_promos},
            }, default=str)
        except Exception as e:
            logger.error(f"Management context error: {e}")
            return json.dumps({"error": "Could not load management context"})

    def _get_tech_context(self) -> str:
        """Build tech admin context — system health, performance, settings."""
        from datetime import timedelta

        try:
            now = utcnow()

            # System info
            try:
                import psutil
                cpu_percent = psutil.cpu_percent(interval=0.1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage("/")
                system_info = {
                    "cpu_percent": cpu_percent,
                    "memory_used_percent": memory.percent,
                    "memory_total_gb": round(memory.total / (1024**3), 1),
                    "disk_used_percent": disk.percent,
                    "disk_total_gb": round(disk.total / (1024**3), 1),
                }
            except Exception:
                system_info = {"note": "System metrics unavailable (psutil not installed)"}

            # Database stats
            try:
                total_products = self.db.query(func.count(Product.id)).scalar() or 0
                total_orders = self.db.query(func.count(Order.id)).scalar() or 0
                total_users = self.db.query(func.count(User.id)).scalar() or 0
                total_admins = self.db.query(func.count(AdminUser.id)).scalar() or 0
            except Exception:
                total_products = total_orders = total_users = total_admins = 0

            # Settings check
            try:
                from app.models import AISettings
                ai_settings = self.db.query(AISettings).first()
                ai_configured = bool(ai_settings and ai_settings.api_key)
            except Exception:
                ai_configured = False

            return json.dumps({
                "system": system_info,
                "database": {
                    "total_products": total_products,
                    "total_orders": total_orders,
                    "total_users": total_users,
                    "total_admins": total_admins,
                },
                "ai_configured": ai_configured,
            }, default=str)
        except Exception as e:
            logger.error(f"Tech context error: {e}")
            return json.dumps({"error": "Could not load tech context"})

    def _build_system_prompt(self, context: dict) -> str:
        """Build the system prompt with shopping context."""
        session_id = context.get("session_id", "")
        is_admin = session_id.startswith("admin-")
        is_vendor = session_id.startswith("vendor-")
        is_logistics = session_id.startswith("logistics-")
        is_management = session_id.startswith("management-")
        is_tech = session_id.startswith("tech-")

        catalog = self._get_catalog_context()

        # ── Dir-Admin (full access) ──
        if is_admin:
            admin_ctx = self._get_admin_context()
            return f"""You are ForgeAI Admin Assistant — an AI analytics and operations assistant for the ForgeStore admin team.

CRITICAL RULES:
- You are a TEXT-ONLY assistant. NEVER output code, XML, JSON, tool_call tags, or any markup.
- Respond ONLY in plain conversational text with simple formatting (bold, bullet points).
- You have access to real-time business data below — use it to answer admin questions.
- Be concise and data-driven. Focus on actionable insights.

Your capabilities:
- Analyze sales trends, revenue, and order patterns
- Identify issues (disputes, low stock, pending orders, open support tickets)
- Provide business insights and recommendations
- Answer questions about vendors, customers, and operations
- Summarize performance metrics
- Track newsletter subscribers and marketing campaigns
- Monitor shipments, drivers, and logistics status
- Report on ad campaigns and promo ads
- Review support tickets and customer feedback
- Check product reviews and ratings

Business Data (Last 30 Days):
{admin_ctx}

Available products (for context):
{catalog}

Guidelines:
- Lead with numbers and trends
- Flag anything that needs immediate attention
- Keep responses under 150 words unless detailed analysis is requested
- Use plain text formatting — bold key metrics, bullet point lists
- NEVER output any code, XML, JSON, or tool_call tags"""

        # ── Vendor / Retailer ──
        if is_vendor:
            vendor_id = context.get("vendor_id")
            vendor_ctx = self._get_vendor_context(vendor_id) if vendor_id else "{}"
            return f"""You are ForgeAI Vendor Assistant — an AI business assistant for vendors on ForgeStore.

CRITICAL RULES:
- You are a TEXT-ONLY assistant. NEVER output code, XML, JSON, tool_call tags, or any markup.
- Respond ONLY in plain conversational text with simple formatting (bold, bullet points).
- You have access to THIS VENDOR'S data only — products, orders, earnings, reviews.
- Be concise and actionable. Help the vendor grow their business.

Your capabilities:
- Analyze product performance (views, sales, conversion)
- Track orders and revenue trends
- Identify low stock and out-of-stock products
- Review customer feedback and ratings
- Monitor ad campaign performance
- Suggest pricing and inventory optimizations

Vendor Data:
{vendor_ctx}

Available catalog (for competitor context):
{catalog}

Guidelines:
- Focus on THIS vendor's data — never mention other vendors' data
- Flag urgent issues (low stock, pending orders, negative reviews)
- Suggest actionable improvements
- Keep responses under 120 words unless detailed analysis is requested
- NEVER output any code, XML, JSON, or tool_call tags"""

        # ── Logistics ──
        if is_logistics:
            logistics_ctx = self._get_logistics_context()
            return f"""You are ForgeAI Logistics Assistant — an AI operations assistant for the ForgeStore logistics team.

CRITICAL RULES:
- You are a TEXT-ONLY assistant. NEVER output code, XML, JSON, tool_call tags, or any markup.
- Respond ONLY in plain conversational text with simple formatting (bold, bullet points).
- You have access to shipment and driver data — use it to answer logistics questions.
- Be concise and operations-focused. Prioritize delivery efficiency.

Your capabilities:
- Track shipment status and delivery progress
- Monitor driver availability and assignments
- Identify delivery bottlenecks and delays
- Report on fulfillment metrics
- Help with route planning and scheduling

Logistics Data:
{logistics_ctx}

Guidelines:
- Lead with shipment counts and status breakdowns
- Flag delayed or failed deliveries
- Keep responses under 120 words unless detailed analysis is requested
- NEVER output any code, XML, JSON, or tool_call tags"""

        # ── Management ──
        if is_management:
            mgmt_ctx = self._get_management_context()
            return f"""You are ForgeAI Management Assistant — an AI business intelligence assistant for ForgeStore management.

CRITICAL RULES:
- You are a TEXT-ONLY assistant. NEVER output code, XML, JSON, tool_call tags, or any markup.
- Respond ONLY in plain conversational text with simple formatting (bold, bullet points).
- You have access to business metrics — revenue, orders, vendors, customers, ads.
- Be concise and strategic. Focus on business growth insights.

Your capabilities:
- Analyze revenue and order trends
- Monitor vendor performance and onboarding
- Track customer acquisition and growth
- Review ad campaign effectiveness
- Provide strategic business recommendations
- Summarize key performance indicators

Management Data (Last 30 Days):
{mgmt_ctx}

Guidelines:
- Lead with KPIs and trends
- Flag opportunities and risks
- Keep responses under 120 words unless detailed analysis is requested
- NEVER output any code, XML, JSON, or tool_call tags"""

        # ── Tech Admin ──
        if is_tech:
            tech_ctx = self._get_tech_context()
            return f"""You are ForgeAI Tech Assistant — an AI system administration assistant for ForgeStore technical team.

CRITICAL RULES:
- You are a TEXT-ONLY assistant. NEVER output code, XML, JSON, tool_call tags, or any markup.
- Respond ONLY in plain conversational text with simple formatting (bold, bullet points).
- You have access to system health, database stats, and configuration status.
- Be concise and technical. Focus on system reliability and performance.

Your capabilities:
- Monitor system health (CPU, memory, disk)
- Check database statistics and growth
- Verify AI and service configurations
- Report on system capacity and scaling needs
- Help troubleshoot technical issues

Tech Data:
{tech_ctx}

Guidelines:
- Lead with system health metrics
- Flag capacity concerns or configuration issues
- Keep responses under 120 words unless detailed analysis is requested
- NEVER output any code, XML, JSON, or tool_call tags"""

        # ── Default: Customer ──
        user_ctx = self._get_user_context(context.get("user_id"))
        return f"""You are ForgeAI, the intelligent shopping assistant for ForgeStore — a multi-vendor e-commerce marketplace.

CRITICAL RULES:
- You are a TEXT-ONLY assistant. NEVER output code, XML, JSON, tool_call tags, function calls, or any markup.
- NEVER use <tool_call>, <function=..., </function>, or similar tags. This is strictly forbidden.
- Respond ONLY in plain conversational text with simple formatting (bold, bullet points).
- The full product catalog is provided below — reference products directly from it.
- If you cannot find a product the user asks about, say so honestly and suggest alternatives from the catalog.

Your capabilities:
- Help customers find products they'll love from the catalog below
- Compare products across different vendors
- Provide personalized recommendations based on preferences and order history
- Answer questions about products, orders, shipping, and policies
- Analyze product images when customers share them (multimodal)

Available products:
{catalog}

User Context:
{user_ctx}

Guidelines:
- Be helpful, concise, and friendly
- When recommending products, include the product name, price, and a brief reason
- Ask clarifying questions to narrow down preferences
- Never make up pricing or product details — only use what's in the catalog above
- If you can't find what the user wants, suggest the closest matches from the catalog
- Keep responses under 200 words unless detailed comparison is needed
- Format product recommendations clearly with product names and prices
- When the user shares an image, analyze it and suggest relevant products
- NEVER output any code, XML, JSON, or tool_call tags — respond ONLY in natural language"""

    def chat(self, session_id: str, message: str, user_id: Optional[str] = None,
             image_url: Optional[str] = None) -> dict:
        """Process a chat message and return AI response with context."""
        conversation = None
        try:
            try:
                conversation = self.memory.get_or_create_conversation(session_id, user_id)
                self.memory.add_message(conversation.id, "user", message)
            except Exception as e:
                logger.error(f"Conversation/message creation failed: {type(e).__name__}: {e}")

            conv_id = conversation.id if conversation else None

            # Get conversation history
            try:
                history = self.memory.get_history(conv_id) if conv_id else []
            except Exception as e:
                logger.warning(f"History fetch failed (non-fatal): {e}")
                history = []

            # Build context
            try:
                context = self.memory.get_context(conv_id) if conv_id else {}
            except Exception as e:
                logger.warning(f"Context fetch failed (non-fatal): {e}")
                context = {}
            context.update({
                "user_id": user_id,
                "session_id": session_id,
                "last_query": message,
            })

            # For vendor sessions, extract vendor_id from session (format: "vendor-{vendor_id}-{timestamp}")
            if session_id.startswith("vendor-"):
                parts = session_id.split("-")
                if len(parts) >= 3:
                    context["vendor_id"] = parts[1]

            # Build system prompt
            system_prompt = self._build_system_prompt(context)

            from app.services.ai_service import _call_llm, get_ai_client, get_active_provider, get_active_model

            provider = get_active_provider()
            model = get_active_model()
            client = get_ai_client()
            logger.info(f"AI chat: provider={provider}, model={model}, client={'ok' if client else 'NONE'}")

            if not client:
                response_text = "AI provider is not configured. Please check the admin settings."
                if conv_id:
                    self.memory.add_message(conv_id, "assistant", response_text)
                return {
                    "conversation_id": conv_id,
                    "response": response_text,
                    "tokens_used": 0,
                    "suggestions": ["Check admin settings"],
                }

            # Build user prompt (with optional image)
            user_prompt = message
            images = [image_url] if image_url else None

            # Call LLM with multimodal support
            response_text = _call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,
                max_tokens=600,
                images=images,
            )

            logger.info(f"AI chat response length: {len(response_text) if response_text else 0}")

            if not response_text:
                logger.warning("LLM returned empty response, using fallback")
                response_text = "I apologize, but the AI service is temporarily unavailable. Please try again in a moment, or browse our catalog directly."

            # Strip any tool_call XML that the model might output
            response_text = re.sub(r'tool_call.*?/tool_call', '', response_text, flags=re.DOTALL)
            response_text = re.sub(r'function=.*?/function', '', response_text, flags=re.DOTALL)
            response_text = re.sub(r'parameter=.*?/parameter', '', response_text, flags=re.DOTALL)
            response_text = response_text.strip()

            if not response_text:
                response_text = "I'd be happy to help you find what you're looking for! Could you tell me more about what you need?"

            tokens = len(response_text.split()) * 2  # rough estimate

            # Store the assistant response
            if conv_id:
                self.memory.add_message(conv_id, "assistant", response_text, tokens_used=tokens)
                self.memory.update_context(conv_id, {
                    "last_query": message,
                    "last_response": response_text,
                })

            return {
                "conversation_id": conv_id,
                "response": response_text,
                "tokens_used": tokens,
                "suggestions": self._generate_suggestions(response_text, context),
            }

        except Exception as e:
            import traceback
            logger.error(f"AI chat error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            try:
                cid = conv_id
            except NameError:
                cid = None
            return {
                "conversation_id": cid,
                "response": "I apologize, but I'm having trouble processing your request right now. Please try again, or browse our catalog directly.",
                "tokens_used": 0,
                "suggestions": ["Browse categories", "View recommendations", "Track my order"],
            }

    def _generate_suggestions(self, response: str, context: dict) -> list[str]:
        """Generate follow-up suggestions based on the response and context."""
        suggestions = []

        # Context-aware suggestions
        if "recommend" in response.lower() or "suggest" in response.lower():
            suggestions.append("Tell me more about these")
            suggestions.append("Show me cheaper options")
        elif "search" in response.lower() or "find" in response.lower():
            suggestions.append("Show me trending products")
            suggestions.append("What's on sale?")
        else:
            suggestions.append("Show me more products")
            suggestions.append("What's popular right now?")
            suggestions.append("Help me find something specific")

        return suggestions[:3]


class RecommendationService:
    """AI-powered product recommendation engine."""

    def __init__(self, db: Session):
        self.db = db

    def get_recommendations(self, user_id: Optional[str] = None, product_id: Optional[str] = None,
                            context_type: str = "home", limit: int = 12) -> list[dict]:
        """Get personalized product recommendations."""
        import hashlib
        context_id = user_id or product_id or "anonymous"
        cache_key = hashlib.md5(f"{context_type}:{context_id}".encode()).hexdigest()

        # Check cache
        cached = self.db.query(RecommendationCache).filter(
            RecommendationCache.context_type == context_type,
            RecommendationCache.context_id == context_id,
        ).first()

        if cached and cached.expires_at and cached.expires_at > utcnow():
            return cached.recommendations[:limit] if cached.recommendations else []

        # Generate recommendations
        recommendations = self._generate_recommendations(user_id, product_id, context_type, limit)

        # Cache the results (expire in 1 hour)
        from datetime import timedelta
        expires = utcnow() + timedelta(hours=1)
        if cached:
            cached.recommendations = recommendations
            cached.expires_at = expires
        else:
            cached = RecommendationCache(
                context_type=context_type,
                context_id=context_id,
                recommendations=recommendations,
                expires_at=expires,
            )
            self.db.add(cached)
        self.db.commit()

        return recommendations

    def _generate_recommendations(self, user_id: Optional[str], product_id: Optional[str],
                                   context_type: str, limit: int) -> list[dict]:
        """Generate recommendations using AI + collaborative filtering."""

        if context_type == "product" and product_id:
            return self._get_similar_products(product_id, limit)
        elif context_type == "cart" and user_id:
            return self._get_cart_complements(user_id, limit)
        elif context_type == "post_purchase" and user_id:
            return self._get_post_purchase_picks(user_id, limit)
        elif user_id:
            return self._get_personalized_picks(user_id, limit)
        else:
            return self._get_trending_products(limit)

    def _get_similar_products(self, product_id: str, limit: int) -> list[dict]:
        """Get products similar to the current product."""
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return self._get_trending_products(limit)

        # Try AI recommendations first
        from app.services.ai_service import get_ai_client, _call_llm, get_active_model
        client = get_ai_client()

        if client:
            all_products = self.db.query(Product).filter(
                Product.inventory > 0,
                Product.id != product_id,
            ).order_by(Product.rating.desc()).limit(50).all()

            product_list = [
                {"id": p.id, "name": p.name, "category": p.category.name if p.category else "",
                 "brand": p.brand or "", "price": p.price, "description": (p.description or "")[:100]}
                for p in all_products
            ]

            result = _call_llm(
                system_prompt=(
                    "You are a product recommendation engine. "
                    "Given the current product and a list of candidates, "
                    "return a JSON array of up to 6 product IDs ranked by relevance. "
                    "Consider category, price range, brand, and complementary items. "
                    "Return ONLY valid JSON array of IDs, no other text."
                ),
                user_prompt=(
                    f"Current product: {json.dumps({'name': product.name, 'category': product.category.name if product.category else '', 'brand': product.brand or '', 'price': product.price})}\n"
                    f"Candidates: {json.dumps(product_list)}"
                ),
                temperature=0.3,
                max_tokens=300,
            )

            if result:
                try:
                    text = result
                    if "```" in text:
                        text = text.split("```")[1].strip()
                        if text.startswith("json"):
                            text = text[4:].strip()
                    recommended_ids = json.loads(text)
                    if isinstance(recommended_ids, list):
                        id_order = {pid: idx for idx, pid in enumerate(recommended_ids)}
                        ordered = [p for p in all_products if p.id in id_order]
                        ordered.sort(key=lambda p: id_order.get(p.id(), 999))
                        return [self._product_to_dict(p, "Similar to what you're viewing") for p in ordered[:limit]]
                except Exception as e:
                    logger.warning(f"AI recommendation parse failed: {e}")

        # Fallback: same category
        similar = self.db.query(Product).filter(
            Product.category_id == product.category_id,
            Product.id != product_id,
            Product.inventory > 0,
        ).order_by(Product.rating.desc()).limit(limit).all()

        return [self._product_to_dict(p, "Similar to what you're viewing") for p in similar]

    def _get_cart_complements(self, user_id: str, limit: int) -> list[dict]:
        """Get products that complement items in the user's cart."""
        from app.models import CartItem
        cart_items = self.db.query(CartItem).filter(CartItem.user_id == user_id).all()
        if not cart_items:
            return self._get_trending_products(limit)

        cart_product_ids = [ci.product_id for ci in cart_items]
        cart_products = self.db.query(Product).filter(Product.id.in_(cart_product_ids)).all()
        cart_category_ids = list(set(p.category_id for p in cart_products if p.category_id))

        complementary = self.db.query(Product).filter(
            Product.category_id.in_(cart_category_ids),
            ~Product.id.in_(cart_product_ids),
            Product.inventory > 0,
        ).order_by(Product.rating.desc()).limit(limit).all()

        return [self._product_to_dict(p, "Completes your order") for p in complementary]

    def _get_post_purchase_picks(self, user_id: str, limit: int) -> list[dict]:
        """Get recommendations based on past purchases."""
        orders = self.db.query(Order).filter(Order.customer_id == user_id).all()
        order_ids = [o.id for o in orders]
        purchased_product_ids = []
        for oid in order_ids:
            items = self.db.query(OrderItem).filter(OrderItem.order_id == oid).all()
            purchased_product_ids.extend([i.product_id for i in items])

        if not purchased_product_ids:
            return self._get_trending_products(limit)

        purchased_products = self.db.query(Product).filter(Product.id.in_(purchased_product_ids)).all()
        category_ids = list(set(p.category_id for p in purchased_products if p.category_id))

        picks = self.db.query(Product).filter(
            Product.category_id.in_(category_ids),
            ~Product.id.in_(purchased_product_ids),
            Product.inventory > 0,
        ).order_by(Product.rating.desc()).limit(limit).all()

        return [self._product_to_dict(p, "Based on your purchase history") for p in picks]

    def _get_personalized_picks(self, user_id: str, limit: int) -> list[dict]:
        """Get personalized picks based on user preferences."""
        pref = self.db.query(UserPreferenceVector).filter(
            UserPreferenceVector.user_id == user_id
        ).first()

        if pref and pref.category_affinities:
            top_categories = sorted(
                pref.category_affinities.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:3]
            cat_ids = [c[0] for c in top_categories]

            products = self.db.query(Product).filter(
                Product.category_id.in_(cat_ids),
                Product.inventory > 0,
            ).order_by(Product.rating.desc()).limit(limit).all()

            return [self._product_to_dict(p, "Based on your interests") for p in products]

        return self._get_trending_products(limit)

    def _get_trending_products(self, limit: int) -> list[dict]:
        """Get trending/popular products."""
        popular = self.db.query(Product).filter(
            Product.inventory > 0
        ).order_by(Product.rating.desc(), Product.review_count.desc()).limit(limit).all()

        return [self._product_to_dict(p, "Popular on ForgeStore") for p in popular]

    def _product_to_dict(self, product: Product, reason: str) -> dict:
        """Convert a Product model to a recommendation dict."""
        return {
            "product_id": product.id,
            "name": product.name,
            "slug": product.slug,
            "price": product.price,
            "discount_price": product.discount_price,
            "rating": product.rating,
            "review_count": product.review_count,
            "image": product.images[0] if product.images else None,
            "reason": reason,
        }


class VectorSearchService:
    """Hybrid vector search preparation for products (pgvector-compatible)."""

    @staticmethod
    def prepare_product_text(product: Product) -> str:
        """Prepare product text for embedding."""
        parts = [
            product.name or "",
            product.brand or "",
            product.description or "",
            f"Price: {product.price}",
        ]
        if product.sub_category:
            parts.append(product.sub_category)
        return " | ".join(parts)

    @staticmethod
    def chunk_text(text: str, max_chars: int = 512) -> list[str]:
        """Split text into chunks for embedding."""
        if len(text) <= max_chars:
            return [text]

        chunks = []
        words = text.split()
        current = []
        current_len = 0

        for word in words:
            if current_len + len(word) + 1 > max_chars and current:
                chunks.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len += len(word) + 1

        if current:
            chunks.append(" ".join(current))

        return chunks

    @staticmethod
    def embed_text(text: str, api_key: str = "") -> list[float]:
        """Generate embedding for text using OpenAI."""
        if not api_key:
            import hashlib
            seed = hashlib.md5(text.encode()).hexdigest()
            import random
            rng = random.Random(seed)
            return [rng.uniform(-1, 1) for _ in range(384)]

        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
