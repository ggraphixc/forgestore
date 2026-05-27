"""Extended Web API — storefront-facing endpoints for all new systems."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.auth import get_current_user_from_cookie
from app.services.ai_chat_service import AIChatService, RecommendationService
from app.services.search_service import SearchService, TrendingService
from app.services.affiliate_service import AffiliateService, ReferralService
from app.services.wallet_service import WalletService, PaymentService
from app.services.review_service import ReviewService
from app.services.shipment_service import TrackingService
from app.services.notification_service import NotificationService, PushService
from app.services.cart_sync_service import CartSyncService, CartRecoveryService, CartRecommendationService
from app.models import User

router = APIRouter(prefix="/api", tags=["web-extended"])


# ===== System 3: AI Shopping Assistant =====

@router.post("/ai/chat")
def ai_chat(
    request: Request,
    session_id: str,
    message: str,
    db: Session = Depends(get_db),
):
    """Chat with the AI shopping assistant."""
    admin = get_current_user_from_cookie(request, db)
    user_id = admin.id if admin else None
    service = AIChatService(db)
    return service.chat(session_id, message, user_id)


@router.get("/ai/recommendations")
def get_recommendations(
    request: Request,
    context_type: str = "home",
    product_id: Optional[str] = None,
    limit: int = 12,
    db: Session = Depends(get_db),
):
    """Get AI-powered product recommendations."""
    admin = get_current_user_from_cookie(request, db)
    user_id = admin.id if admin else None
    service = RecommendationService(db)
    return {"recommendations": service.get_recommendations(user_id, product_id, context_type, limit)}


# ===== System 7: Smart Search =====

@router.get("/search/smart")
def smart_search(
    q: str = "",
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Smart search with full-text matching, filters, and personalization."""
    admin = get_current_user_from_cookie(request, db) if request else None
    user_id = admin.id if admin else None
    service = SearchService(db)
    return service.search(q, category, min_price, max_price, sort, page, per_page, user_id)


@router.get("/search/trending")
def get_trending_searches(limit: int = 10, db: Session = Depends(get_db)):
    """Get trending search queries."""
    service = TrendingService(db)
    return {"trending": service.get_trending_searches(limit)}


@router.get("/search/suggestions")
def get_search_suggestions(q: str = "", limit: int = 5, db: Session = Depends(get_db)):
    """Get autocomplete suggestions."""
    if not q:
        return {"suggestions": []}
    service = SearchService(db)
    return {"suggestions": service.get_suggestions(q, limit)}


# ===== System 4: Affiliate & Referral =====

@router.post("/referrals/create")
def create_referral(
    request: Request,
    db: Session = Depends(get_db),
):
    """Create an affiliate/referral account using the current user."""
    admin = get_current_user_from_cookie(request, db)
    user_id = admin.id if admin else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    service = AffiliateService(db)
    affiliate = service.create_affiliate(user_id)
    return {"code": affiliate.code, "id": affiliate.id, "total_earnings": 0, "pending_earnings": 0, "total_referrals": 0}


@router.get("/referrals/stats")
def get_referral_stats(request: Request, db: Session = Depends(get_db)):
    """Get referral statistics for the current user."""
    admin = get_current_user_from_cookie(request, db)
    user_id = admin.id if admin else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    service = AffiliateService(db)
    affiliate = service.get_affiliate_by_user_id(user_id)
    if not affiliate:
        # Auto-create affiliate for the user
        affiliate = service.create_affiliate(user_id)
    return {
        "referral_code": affiliate.code,
        "total_earnings": float(affiliate.total_earned or 0),
        "pending_earnings": float((affiliate.total_earned or 0) - (affiliate.total_paid or 0)),
        "total_referrals": affiliate.total_conversions or 0,
    }


@router.get("/referrals/earnings")
def get_referral_earnings(request: Request, db: Session = Depends(get_db)):
    """Get referral earnings for the current user."""
    admin = get_current_user_from_cookie(request, db)
    user_id = admin.id if admin else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    service = AffiliateService(db)
    affiliate = service.get_affiliate_by_user_id(user_id)
    if not affiliate:
        affiliate = service.create_affiliate(user_id)
    return {"total_earned": float(affiliate.total_earned or 0), "wallet_balance": float(affiliate.wallet_balance or 0), "total_paid": float(affiliate.total_paid or 0)}


@router.post("/referrals/withdraw")
async def withdraw_referral_earnings(
    request: Request,
    db: Session = Depends(get_db),
):
    """Withdraw referral earnings."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    amount = body.get('amount', 0)
    payment_method = body.get('payment_method', 'wallet')
    
    admin = get_current_user_from_cookie(request, db)
    user_id = admin.id if admin else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    from app.services.affiliate_service import ReferralService
    service = AffiliateService(db)
    affiliate = service.get_affiliate_by_user_id(user_id)
    if not affiliate:
        raise HTTPException(status_code=404, detail="Affiliate account not found")
    referral_service = ReferralService(db)
    try:
        payout = referral_service.withdraw_earnings(affiliate.id, amount, payment_method)
        return {"payout_id": payout.id, "amount": float(payout.net_amount), "status": payout.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/referrals/history")
def get_referral_history(request: Request, db: Session = Depends(get_db)):
    """Get referral history for current user."""
    admin = get_current_user_from_cookie(request, db)
    user_id = admin.id if admin else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.affiliate_service import ReferralService
    service = AffiliateService(db)
    affiliate = service.get_affiliate_by_user_id(user_id)
    if not affiliate:
        raise HTTPException(status_code=404, detail="Affiliate account not found")
    referral_service = ReferralService(db)
    events = referral_service.get_referral_history(affiliate.id)
    return {
        "history": [
            {
                "event_type": e.event_type,
                "extra_data": e.extra_data,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }


# ===== System 5: Wallet =====

@router.post("/wallet/fund")
async def fund_wallet(
    request: Request,
    db: Session = Depends(get_db),
):
    """Initialize wallet funding."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Parse JSON body
    try:
        body = await request.json()
        amount = float(body.get('amount', 0))
        provider = body.get('provider', 'paystack')
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")
    
    payment = PaymentService(db)
    result = payment.initialize_payment(None, amount, provider=provider, metadata={"user_id": admin.id, "purpose": "wallet_funding"})
    return result


@router.get("/wallet/balance")
def get_wallet_balance(request: Request, db: Session = Depends(get_db)):
    """Get wallet balance."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    wallet = WalletService(db)
    balance = wallet.get_balance(admin.id)
    return {"balance": balance, "currency": "NGN"}


@router.get("/wallet/transactions")
def get_wallet_transactions(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    """Get wallet transaction history."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    wallet = WalletService(db)
    transactions = wallet.get_transactions(admin.id, limit)
    return {
        "transactions": [
            {
                "id": t.id, "type": t.transaction_type,
                "amount": t.amount, "balance_after": t.balance_after,
                "description": t.description, "status": t.status,
                "created_at": t.created_at.isoformat(),
            }
            for t in transactions
        ],
    }


# ===== System 6: Cart Sync =====

@router.post("/cart/sync")
def sync_cart(request: Request, cart_token: str, items: list[dict], db: Session = Depends(get_db)):
    """Sync cart from client to server."""
    service = CartSyncService()
    for item in items:
        service.add_item(cart_token, item["product_id"], item.get("quantity", 1), db)
    cart = service.get_cart(cart_token)
    return {"cart_token": cart_token, "items": cart.get("items", [])}


@router.post("/cart/merge")
def merge_carts(request: Request, source_token: str, target_token: str, db: Session = Depends(get_db)):
    """Merge two carts together (for cross-device sync)."""
    service = CartSyncService()
    result = service.merge_carts(source_token, target_token, db)
    return {"cart_token": target_token, "items": result.get("items", [])}


@router.get("/cart/recovery")
def get_recoverable_carts(request: Request, email: str, db: Session = Depends(get_db)):
    """Get abandoned carts for recovery by email."""
    from app.models import AbandonedCart
    carts = db.query(AbandonedCart).filter(
        AbandonedCart.email == email,
        AbandonedCart.recovered == False,
    ).order_by(AbandonedCart.abandoned_at.desc()).limit(5).all()
    return {
        "carts": [
            {
                "id": c.id, "items": c.items,
                "total_value": c.total_value,
                "abandoned_at": c.abandoned_at.isoformat(),
            }
            for c in carts
        ],
    }


@router.post("/cart/restore")
def restore_cart(abandoned_cart_id: str, db: Session = Depends(get_db)):
    """Restore an abandoned cart."""
    from app.models import AbandonedCart
    cart = db.query(AbandonedCart).filter(AbandonedCart.id == abandoned_cart_id).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    service = CartSyncService()
    service.set_cart(cart.cart_token, {"items": cart.items, "restored": True})
    return {"cart_token": cart.cart_token, "items": cart.items}


# ===== System 8: Reviews =====

@router.post("/reviews/{review_id}/react")
def react_to_review(review_id: str, request: Request, reaction_type: str = "helpful", db: Session = Depends(get_db)):
    """React to a review."""
    admin = get_current_user_from_cookie(request, db)
    user_id = admin.id if admin else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    service = ReviewService(db)
    result = service.react_to_review(review_id, user_id, reaction_type)
    return {"status": "reacted" if result else "removed"}


@router.post("/reviews/{review_id}/reply")
def reply_to_review(review_id: str, content: str, db: Session = Depends(get_db)):
    """Add a retailer reply to a review."""
    service = ReviewService(db)
    try:
        review = service.add_retailer_reply(review_id, content)
        return {"status": "replied", "review_id": review.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===== System 9: Notifications =====

@router.get("/notifications")
def get_notifications(request: Request, unread_only: bool = False, db: Session = Depends(get_db)):
    """Get user notifications."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    service = NotificationService(db)
    notifications = service.get_user_notifications(admin.id, "customer", unread_only=unread_only)
    return {
        "notifications": [
            {
                "id": n.id, "type": n.notification_type, "title": n.title,
                "message": n.message, "read": n.read_at is not None,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifications
        ],
    }


@router.post("/notifications/read")
def mark_all_read(request: Request, notification_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Mark notification(s) as read."""
    service = NotificationService(db)
    if notification_id:
        service.mark_read(notification_id)
    return {"status": "read"}


@router.post("/notifications/preferences")
def update_notification_preferences(request: Request, preferences: dict, db: Session = Depends(get_db)):
    """Update notification preferences."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    service = NotificationService(db)
    prefs = service.update_preferences(admin.id, preferences)
    return {"status": "updated"}


@router.post("/push/register")
def register_push_subscription(
    request: Request, endpoint: str, keys: dict,
    db: Session = Depends(get_db),
):
    """Register a push notification subscription."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    service = PushService(db)
    sub = service.register_subscription(admin.id, endpoint, keys)
    return {"id": sub.id, "status": "registered"}


# ===== System 3: AI History =====

@router.get("/ai/history")
def get_ai_chat_history(request: Request, session_id: str, limit: int = 20, db: Session = Depends(get_db)):
    """Get AI chat history for a session."""
    from app.services.ai_chat_service import ConversationMemory
    memory = ConversationMemory(db)
    conversation = memory.get_or_create_conversation(session_id)
    history = memory.get_history(conversation.id, limit)
    return {"history": history, "conversation_id": conversation.id}


# ===== System 1: Tracking (customer-facing) =====

@router.get("/orders/{order_id}/tracking")
def get_order_tracking_customer(order_id: str, db: Session = Depends(get_db)):
    """Get tracking info for an order."""
    from app.services.shipment_service import ShipmentService
    service = ShipmentService(db)
    shipments = service.get_order_shipments(order_id)
    return {
        "shipments": [
            {
                "id": s.id, "tracking_number": s.tracking_number,
                "status": s.status, "carrier": s.carrier,
                "estimated_delivery": s.estimated_delivery.isoformat() if s.estimated_delivery else None,
            }
            for s in shipments
        ],
    }
