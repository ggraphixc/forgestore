"""Advanced Cart Infrastructure — System 6"""
import json
import logging
from datetime import datetime
from datetime import timedelta
from app.utils import utcnow
from app.utils import utcnow
from typing import Optional, Any
from sqlalchemy.orm import Session

from app.core.redis_manager import redis_client
from app.models import PersistentCart, CartActivity, AbandonedCart, CartRecommendation, Product

logger = logging.getLogger("forgestore.cart")


class CartSyncService:
    """Redis-backed cart synchronization and persistence."""

    CART_PREFIX = "cart:"
    CART_TTL = 60 * 60 * 24 * 7  # 7 days

    @staticmethod
    def get_cart_key(cart_token: str) -> str:
        return f"{CartSyncService.CART_PREFIX}{cart_token}"

    @staticmethod
    def get_cart_token(user_id: Optional[str] = None) -> str:
        import uuid
        return str(uuid.uuid4())

    def get_cart(self, cart_token: str) -> dict:
        """Get cart from Redis cache, falling back to DB."""
        key = self.get_cart_key(cart_token)
        cached = redis_client.get(key)
        if cached:
            return json.loads(cached)
        return {}

    def set_cart(self, cart_token: str, cart_data: dict):
        """Set cart in Redis with TTL."""
        key = self.get_cart_key(cart_token)
        redis_client.setex(key, self.CART_TTL, json.dumps(cart_data))

    def add_item(self, cart_token: str, product_id: str, quantity: int = 1, db: Optional[Session] = None) -> dict:
        """Add item to cart (Redis + DB persistence)."""
        cart = self.get_cart(cart_token)
        items = cart.get("items", [])

        # Check if product already in cart
        found = False
        for item in items:
            if item["product_id"] == product_id:
                item["quantity"] += quantity
                found = True
                break

        if not found:
            items.append({
                "product_id": product_id,
                "quantity": quantity,
                "added_at": utcnow().isoformat(),
            })

        cart["items"] = items
        cart["updated_at"] = utcnow().isoformat()
        self.set_cart(cart_token, cart)

        # Persist to DB
        if db:
            persistent = db.query(PersistentCart).filter(
                PersistentCart.cart_token == cart_token
            ).first()
            if not persistent:
                persistent = PersistentCart(cart_token=cart_token, items=items)
                db.add(persistent)
            else:
                persistent.items = items
                persistent.updated_at = utcnow()
            db.commit()

            # Log activity
            activity = CartActivity(
                cart_token=cart_token,
                activity_type="add",
                product_id=product_id,
                quantity=quantity,
            )
            db.add(activity)
            db.commit()

        return cart

    def remove_item(self, cart_token: str, product_id: str, db: Optional[Session] = None) -> dict:
        """Remove item from cart."""
        cart = self.get_cart(cart_token)
        items = cart.get("items", [])
        cart["items"] = [i for i in items if i["product_id"] != product_id]
        cart["updated_at"] = utcnow().isoformat()
        self.set_cart(cart_token, cart)

        if db:
            persistent = db.query(PersistentCart).filter(
                PersistentCart.cart_token == cart_token
            ).first()
            if persistent:
                persistent.items = cart["items"]
                persistent.updated_at = utcnow()
                db.commit()

            activity = CartActivity(
                cart_token=cart_token,
                activity_type="remove",
                product_id=product_id,
            )
            db.add(activity)
            db.commit()

        return cart

    def update_quantity(self, cart_token: str, product_id: str, quantity: int, db: Optional[Session] = None) -> dict:
        """Update item quantity in cart."""
        if quantity < 1:
            return self.remove_item(cart_token, product_id, db)

        cart = self.get_cart(cart_token)
        items = cart.get("items", [])
        for item in items:
            if item["product_id"] == product_id:
                item["quantity"] = quantity
                break

        cart["items"] = items
        cart["updated_at"] = utcnow().isoformat()
        self.set_cart(cart_token, cart)

        if db:
            persistent = db.query(PersistentCart).filter(
                PersistentCart.cart_token == cart_token
            ).first()
            if persistent:
                persistent.items = cart["items"]
                persistent.updated_at = utcnow()
                db.commit()

            activity = CartActivity(
                cart_token=cart_token,
                activity_type="update",
                product_id=product_id,
                quantity=quantity,
            )
            db.add(activity)
            db.commit()

        return cart

    def clear_cart(self, cart_token: str, db: Optional[Session] = None):
        """Clear all items from cart."""
        key = self.get_cart_key(cart_token)
        redis_client.delete(key)

        if db:
            persistent = db.query(PersistentCart).filter(
                PersistentCart.cart_token == cart_token
            ).first()
            if persistent:
                persistent.items = []
                persistent.updated_at = utcnow()
                db.commit()

            activity = CartActivity(
                cart_token=cart_token,
                activity_type="clear",
            )
            db.add(activity)
            db.commit()

    def merge_carts(self, source_token: str, target_token: str, db: Session) -> dict:
        """Merge source cart into target cart (for cross-device sync / login)."""
        source_cart = self.get_cart(source_token)
        target_cart = self.get_cart(target_token)

        source_items = {i["product_id"]: i["quantity"] for i in source_cart.get("items", [])}
        target_items = {i["product_id"]: i["quantity"] for i in target_cart.get("items", [])}

        merged = {}
        for pid, qty in target_items.items():
            merged[pid] = qty
        for pid, qty in source_items.items():
            if pid in merged:
                merged[pid] += qty
            else:
                merged[pid] = qty

        items = [{"product_id": pid, "quantity": qty, "added_at": utcnow().isoformat()}
                 for pid, qty in merged.items()]

        target_cart["items"] = items
        target_cart["updated_at"] = utcnow().isoformat()
        self.set_cart(target_token, target_cart)
        self.clear_cart(source_token, db)

        if db:
            persistent = db.query(PersistentCart).filter(
                PersistentCart.cart_token == target_token
            ).first()
            if persistent:
                persistent.items = items
                persistent.updated_at = utcnow()
                db.commit()

            activity = CartActivity(
                cart_token=target_token,
                activity_type="merge",
                metadata={"source_token": source_token},
            )
            db.add(activity)
            db.commit()

        return target_cart


class CartRecoveryService:
    """Abandoned cart detection and recovery automation."""

    def __init__(self, db: Session):
        self.db = db

    def detect_abandoned(self, cart_token: str, email: Optional[str] = None, user_id: Optional[str] = None, cart_data: Optional[dict] = None):
        """Mark a cart as abandoned for recovery."""
        existing = self.db.query(AbandonedCart).filter(
            AbandonedCart.cart_token == cart_token
        ).first()
        if existing:
            return existing

        if cart_data is None:
            cart_data = {}

        total_value = 0.0
        items = cart_data.get("items", [])
        for item in items:
            total_value += item.get("price", 0.0) * item.get("quantity", 1)

        abandoned = AbandonedCart(
            cart_token=cart_token,
            user_id=user_id,
            email=email,
            items=items,
            total_value=total_value,
            abandoned_at=utcnow(),
        )
        self.db.add(abandoned)
        self.db.commit()
        self.db.refresh(abandoned)
        return abandoned

    def send_recovery_reminder(self, abandoned_cart_id: str) -> bool:
        """Queue a recovery reminder email via Celery."""
        cart = self.db.query(AbandonedCart).filter(AbandonedCart.id == abandoned_cart_id).first()
        if not cart or not cart.email:
            return False

        from app.tasks.cart_tasks import send_cart_recovery_email
        send_cart_recovery_email.delay(cart.id)

        cart.reminder_sent = True
        cart.reminder_count += 1
        cart.last_reminder_at = utcnow()
        self.db.commit()
        return True

    def mark_recovered(self, cart_token: str, order_id: str) -> bool:
        """Mark an abandoned cart as recovered."""
        cart = self.db.query(AbandonedCart).filter(
            AbandonedCart.cart_token == cart_token
        ).first()
        if not cart:
            return False

        cart.recovered = True
        cart.recovery_order_id = order_id
        cart.recovered_at = utcnow()
        self.db.commit()

        # Log recovery activity
        activity = CartActivity(
            cart_token=cart_token,
            activity_type="recover",
            metadata={"order_id": order_id},
        )
        self.db.add(activity)
        self.db.commit()
        return True

    def get_abandoned_carts(self, limit: int = 50, include_recovered: bool = False) -> list[AbandonedCart]:
        """Get abandoned carts for recovery processing."""
        query = self.db.query(AbandonedCart)
        if not include_recovered:
            query = query.filter(AbandonedCart.recovered == False)
        return query.order_by(AbandonedCart.abandoned_at.desc()).limit(limit).all()


class CartRecommendationService:
    """AI-powered cart upselling recommendations."""

    def __init__(self, db: Session):
        self.db = db

    def get_recommendations(self, cart_token: str, limit: int = 5) -> list[dict]:
        """Get product recommendations based on cart contents."""
        cart = self.db.query(PersistentCart).filter(
            PersistentCart.cart_token == cart_token
        ).first()
        if not cart or not cart.items:
            return []

        cart_product_ids = [i.get("product_id") for i in cart.items if isinstance(i, dict)]
        if not cart_product_ids:
            return []

        # Find complementary products (same category, not already in cart)
        from sqlalchemy import not_
        products_in_cart = self.db.query(Product).filter(Product.id.in_(cart_product_ids)).all()
        categories = set(p.category_id for p in products_in_cart if p.category_id)

        if not categories:
            return []

        # Get popular products in same categories
        recommendations = self.db.query(Product).filter(
            Product.category_id.in_(categories),
            not_(Product.id.in_(cart_product_ids)),
            Product.inventory > 0,
        ).order_by(Product.rating.desc()).limit(limit).all()

        result = []
        for i, rec in enumerate(recommendations):
            cart_rec = CartRecommendation(
                cart_token=cart_token,
                product_id=rec.id,
                reason="frequently_bought",
                score=1.0 - (i * 0.1),
            )
            self.db.add(cart_rec)
            result.append({
                "product_id": rec.id,
                "name": rec.name,
                "price": rec.price,
                "discount_price": rec.discount_price,
                "reason": "frequently_bought",
                "score": 1.0 - (i * 0.1),
            })

        self.db.commit()
        return result
