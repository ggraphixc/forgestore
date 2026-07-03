"""
AI Assistant Router — Dedicated endpoints for the AI shopping assistant and recommendations.

Endpoints:
  POST /api/ai/assistant/chat       — Chat with AI (text + optional image)
  GET  /api/ai/assistant/products   — AI-curated product list
  POST /api/ai/assistant/compare    — Compare products via AI
  GET  /api/ai/assistant/history    — Chat history
  GET  /api/ai/recommendations      — AI-powered recommendations
"""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.auth import get_current_customer_from_cookie
from app.services.ai_chat_service import AIChatService, RecommendationService
from app.services.ai_service import get_ai_client, _call_llm, get_active_model, get_active_provider
from app.models import Product, Category

logger = logging.getLogger("forgestore.ai")

router = APIRouter(prefix="/api/ai", tags=["ai-assistant"])


@router.get("/debug/ai-status")
def debug_ai_status():
    """Debug endpoint — shows AI provider config. Remove after debugging."""
    from app.services.ai_service import get_active_provider, get_active_model, get_ai_client, _get_db_setting, PROVIDER_CONFIGS
    provider = get_active_provider()
    config = PROVIDER_CONFIGS.get(provider, {})
    api_key = _get_db_setting(config.get("api_key_setting", ""))
    client = get_ai_client()
    return {
        "provider": provider,
        "model": get_active_model(),
        "api_key_set": bool(api_key),
        "api_key_preview": api_key[:15] + "..." if api_key else "",
        "client_ok": client is not None,
        "base_url": config.get("base_url"),
    }


class ChatRequest(BaseModel):
    session_id: str
    message: str
    image_url: Optional[str] = None


# ===== AI Shopping Assistant =====

@router.post("/assistant/chat")
def ai_assistant_chat(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Chat with the AI shopping assistant.
    Supports text-only and multimodal (text + image) queries.
    """
    # Check if AI assistant is enabled
    from app.models import Settings
    setting = db.query(Settings).filter(Settings.key == "ai_assistant_enabled").first()
    if setting and setting.value == "false":
        return {
            "conversation_id": None,
            "response": "The AI assistant is currently disabled. Please browse our catalog directly.",
            "tokens_used": 0,
            "suggestions": ["Browse categories", "View all products"],
        }

    customer = get_current_customer_from_cookie(request, db)
    user_id = customer.id if customer else None

    service = AIChatService(db)
    return service.chat(body.session_id, body.message, user_id, image_url=body.image_url)


@router.get("/assistant/products")
def ai_assistant_products(
    request: Request,
    query: str = "",
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = 12,
    db: Session = Depends(get_db),
):
    """
    Get AI-curated product list based on natural language query.
    Uses the AI search assistant to understand intent and filter products.
    """
    # Build base query
    q = db.query(Product).filter(Product.inventory > 0)

    if category:
        cat = db.query(Category).filter(Category.slug == category).first()
        if cat:
            q = q.filter(Product.category_id == cat.id)

    if min_price is not None:
        q = q.filter(Product.price >= min_price)
    if max_price is not None:
        q = q.filter(Product.price <= max_price)

    products = q.order_by(Product.rating.desc()).limit(100).all()

    if not query.strip():
        # No query — return top products
        return {
            "products": [
                {
                    "id": p.id, "name": p.name, "slug": p.slug,
                    "price": p.price, "discount_price": p.discount_price,
                    "rating": p.rating, "image": p.images[0] if p.images else None,
                    "category": p.category.name if p.category else "",
                }
                for p in products[:limit]
            ],
            "message": None,
        }

    # Use AI to refine search
    from app.services.ai_service import ai_search_assistant
    product_dicts = [
        {
            "id": p.id, "name": p.name, "category": p.category.name if p.category else "",
            "brand": p.brand or "", "price": p.price,
            "description": (p.description or "")[:150],
        }
        for p in products
    ]

    result = ai_search_assistant(query, product_dicts, max_results=limit)

    if result and "product_ids" in result:
        id_set = set(result["product_ids"])
        matched = [p for p in products if p.id in id_set]
        # Preserve AI ordering
        matched.sort(key=lambda p: result["product_ids"].index(p.id) if p.id in id_set else 999)
        return {
            "products": [
                {
                    "id": p.id, "name": p.name, "slug": p.slug,
                    "price": p.price, "discount_price": p.discount_price,
                    "rating": p.rating, "image": p.images[0] if p.images else None,
                    "category": p.category.name if p.category else "",
                }
                for p in matched[:limit]
            ],
            "message": result.get("message"),
            "refined_query": result.get("refined_query"),
        }

    # Fallback
    return {
        "products": [
            {
                "id": p.id, "name": p.name, "slug": p.slug,
                "price": p.price, "discount_price": p.discount_price,
                "rating": p.rating, "image": p.images[0] if p.images else None,
                "category": p.category.name if p.category else "",
            }
            for p in products[:limit]
        ],
        "message": f"Here are our top products. Try searching for something specific!",
    }


@router.post("/assistant/compare")
def ai_compare_products(
    request: Request,
    product_ids: list[str],
    db: Session = Depends(get_db),
):
    """
    Compare 2-3 products using AI analysis.
    Returns a structured comparison with pros, cons, and recommendation.
    """
    if len(product_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 product IDs required")
    if len(product_ids) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 products for comparison")

    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    if len(products) < 2:
        raise HTTPException(status_code=404, detail="Products not found")

    product_data = [
        {
            "id": p.id, "name": p.name, "brand": p.brand or "",
            "category": p.category.name if p.category else "",
            "price": p.price, "discount_price": p.discount_price,
            "rating": p.rating, "review_count": p.review_count,
            "description": (p.description or "")[:200],
            "specifications": p.specifications or {},
        }
        for p in products
    ]

    result = _call_llm(
        system_prompt=(
            "You are a product comparison expert. Compare these products and return a JSON object with:\n"
            '- "summary": a 2-sentence overall comparison\n'
            '- "best_value": the product ID that offers the best value\n'
            '- "comparison": array of objects with "product_id", "pros" (array), "cons" (array), "verdict" (string)\n'
            "Return ONLY valid JSON, no other text."
        ),
        user_prompt=f"Products to compare: {json.dumps(product_data)}",
        temperature=0.3,
        max_tokens=500,
    )

    comparison = None
    if result:
        try:
            text = result
            if "```" in text:
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()
            comparison = json.loads(text)
        except Exception as e:
            logger.warning(f"AI comparison parse failed: {e}")

    return {
        "products": product_data,
        "comparison": comparison,
    }


@router.get("/assistant/history")
def get_ai_chat_history(
    request: Request,
    session_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Get AI chat history for a session."""
    from app.services.ai_chat_service import ConversationMemory
    memory = ConversationMemory(db)
    conversation = memory.get_or_create_conversation(session_id)
    history = memory.get_history(conversation.id, limit)
    return {"history": history, "conversation_id": conversation.id}


# ===== AI Product Recommendations =====

@router.get("/recommendations")
def get_ai_recommendations(
    request: Request,
    context_type: str = "home",
    product_id: Optional[str] = None,
    limit: int = 12,
    db: Session = Depends(get_db),
):
    """
    Get AI-powered product recommendations.

    context_type options:
    - home: Personalized picks for homepage
    - product: Similar products on product detail page
    - cart: Complementary items for cart page
    - post_purchase: Post-order recommendations
    """
    # Check if AI recommendations are enabled
    from app.models import Settings
    setting = db.query(Settings).filter(Settings.key == "ai_recommendations_enabled").first()
    if setting and setting.value == "false":
        return {"recommendations": [], "message": "AI recommendations are currently disabled."}

    customer = get_current_customer_from_cookie(request, db)
    user_id = customer.id if customer else None

    service = RecommendationService(db)
    recommendations = service.get_recommendations(user_id, product_id, context_type, limit)

    return {"recommendations": recommendations}
