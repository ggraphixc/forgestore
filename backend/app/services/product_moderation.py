"""
AI-Powered Product Moderation Service for ForgeStore.
Analyzes products for quality, policy compliance, pricing, and image standards.
Auto-approves high-confidence products, escalates uncertain ones to human review.
"""
import json
import logging
from typing import Optional
from app.services.ai_service import get_ai_client, get_active_model, _call_llm_sync

logger = logging.getLogger("forgestore.moderation")

# ─── Prohibited Keywords ───────────────────────────────────────────

PROHIBITED_KEYWORDS = [
    "fake", "counterfeit", "knockoff", "replica", "imitation",
    "stolen", "illegal", "banned", "restricted",
    "meth", "cocaine", "heroin", "drugs", "narcotics",
    "weapon", "gun", "firearm", "ammunition", "explosive",
    "porn", "nude", "nsfw",
]

# ─── Category Price Ranges (₦) ─────────────────────────────────────

CATEGORY_PRICE_RANGES = {
    "electronics": {"min": 500, "max": 5000000},
    "fashion": {"min": 200, "max": 500000},
    "home": {"min": 100, "max": 2000000},
    "beauty": {"min": 100, "max": 100000},
    "sports": {"min": 200, "max": 1000000},
    "toys": {"min": 100, "max": 300000},
    "default": {"min": 50, "max": 5000000},
}


def analyze_text(product_data: dict) -> dict:
    """Analyze product text for policy compliance and quality."""
    result = {
        "prohibited_items": [],
        "text_quality_score": 0,
        "suggestions": [],
        "flagged_words": [],
    }

    text_to_check = " ".join([
        product_data.get("name", ""),
        product_data.get("brand", ""),
        product_data.get("description", ""),
        product_data.get("sub_category", ""),
    ]).lower()

    # Check prohibited keywords
    for keyword in PROHIBITED_KEYWORDS:
        if keyword in text_to_check:
            result["prohibited_items"].append(keyword)
            result["flagged_words"].append(keyword)

    # Text quality scoring
    score = 80
    name = product_data.get("name", "")
    desc = product_data.get("description", "")
    brand = product_data.get("brand", "")

    if not name or len(name) < 3:
        score -= 20
        result["suggestions"].append("Product name too short")
    if not desc:
        score -= 20
        result["suggestions"].append("No description provided")
    elif len(desc) < 20:
        score -= 10
        result["suggestions"].append("Description is very short")
    if not brand:
        score -= 5
        result["suggestions"].append("No brand specified")
    if len(name) > 200:
        score -= 10
        result["suggestions"].append("Product name is too long")

    result["text_quality_score"] = max(0, min(100, score))
    return result


def analyze_price(product_data: dict) -> dict:
    """Analyze product pricing for anomalies and errors."""
    result = {
        "price_anomalies": [],
        "price_score": 100,
        "suggestions": [],
    }

    price = product_data.get("price", 0)
    discount_price = product_data.get("discount_price")
    category_name = product_data.get("category_name", "default").lower()

    # Get expected range
    range_key = "default"
    for key in CATEGORY_PRICE_RANGES:
        if key in category_name:
            range_key = key
            break
    expected = CATEGORY_PRICE_RANGES[range_key]

    # Price checks
    if price <= 0:
        result["price_anomalies"].append("Price is zero or negative")
        result["price_score"] = 0
    elif price < expected["min"]:
        result["price_anomalies"].append(f"Price ₦{price} below typical minimum ₦{expected['min']} for {range_key}")
        result["price_score"] -= 30
    elif price > expected["max"]:
        result["price_anomalies"].append(f"Price ₦{price:,.0f} above typical maximum ₦{expected['max']:,.0f} for {range_key}")
        result["price_score"] -= 15

    # Discount check
    if discount_price and discount_price > 0:
        if discount_price >= price:
            result["price_anomalies"].append("Discount price is not lower than original price")
            result["price_score"] -= 20
        elif discount_price < price * 0.1:
            result["price_anomalies"].append(f"Discount of {((price - discount_price) / price * 100):.0f}% is extreme")
            result["price_score"] -= 10

    # Common price errors
    if price == 50 or price == 100:
        result["suggestions"].append("Confirm this price is correct (₦50/₦100 is unusually low)")

    result["price_score"] = max(0, min(100, result["price_score"]))
    return result


def analyze_images(product_data: dict) -> dict:
    """Analyze product images for quality signals."""
    result = {
        "image_score": 80,
        "image_count": 0,
        "suggestions": [],
        "flags": [],
    }

    images = product_data.get("images") or []
    result["image_count"] = len(images)

    if len(images) == 0:
        result["image_score"] = 0
        result["flags"].append("No product images")
        result["suggestions"].append("Add at least one product image")
    elif len(images) == 1:
        result["image_score"] = 50
        result["suggestions"].append("Consider adding more images (3-5 recommended)")
    elif len(images) < 3:
        result["image_score"] = 70
        result["suggestions"].append("More images improve buyer confidence")

    return result


def calculate_inventory_score(product_data: dict) -> int:
    """Score based on inventory levels."""
    inventory = product_data.get("inventory", 0)
    if inventory <= 0:
        return 0
    elif inventory < 3:
        return 40
    elif inventory < 10:
        return 70
    return 100


def run_moderation(product_data: dict) -> dict:
    """
    Run full AI moderation analysis on a product.
    Returns confidence score (0-100) and detailed analysis.
    """
    text_analysis = analyze_text(product_data)
    price_analysis = analyze_price(product_data)
    image_analysis = analyze_images(product_data)
    inventory_score = calculate_inventory_score(product_data)

    # Weighted confidence score
    weights = {
        "text": 0.30,
        "price": 0.25,
        "image": 0.30,
        "inventory": 0.15,
    }

    confidence = (
        text_analysis["text_quality_score"] * weights["text"]
        + price_analysis["price_score"] * weights["price"]
        + image_analysis["image_score"] * weights["image"]
        + inventory_score * weights["inventory"]
    )

    # Hard blocks — these override the score
    hard_blocks = []
    if text_analysis["prohibited_items"]:
        hard_blocks.append(f"Prohibited keywords detected: {', '.join(text_analysis['prohibited_items'])}")
    if price_analysis["price_score"] == 0:
        hard_blocks.append("Invalid pricing")
    if image_analysis["image_score"] == 0:
        hard_blocks.append("No product images")

    # Determine decision
    if hard_blocks:
        decision = "REJECT"
        confidence = 0
    elif confidence >= 75:
        decision = "APPROVE"
    elif confidence >= 50:
        decision = "ESCALATE"
    else:
        decision = "REJECT"

    # Build AI reasoning
    reasoning_parts = []
    if text_analysis["prohibited_items"]:
        reasoning_parts.append(f"Prohibited items: {', '.join(text_analysis['prohibited_items'])}")
    if text_analysis["suggestions"]:
        reasoning_parts.append(f"Text issues: {'; '.join(text_analysis['suggestions'])}")
    if price_analysis["price_anomalies"]:
        reasoning_parts.append(f"Price issues: {'; '.join(price_analysis['price_anomalies'])}")
    if image_analysis["flags"]:
        reasoning_parts.append(f"Image issues: {'; '.join(image_analysis['flags'])}")
    if image_analysis["suggestions"]:
        reasoning_parts.append(f"Image suggestions: {'; '.join(image_analysis['suggestions'])}")

    return {
        "confidence": round(confidence, 1),
        "decision": decision,
        "reasoning": "; ".join(reasoning_parts) if reasoning_parts else "Product meets all standards",
        "analysis": {
            "text": text_analysis,
            "price": price_analysis,
            "image": image_analysis,
            "inventory_score": inventory_score,
        },
        "hard_blocks": hard_blocks,
        "suggestions": (
            text_analysis["suggestions"]
            + price_analysis["suggestions"]
            + image_analysis["suggestions"]
        ),
    }


def generate_ai_moderation_summary(product_data: dict, moderation_result: dict) -> str:
    """Use LLM to generate a human-readable moderation summary."""
    client = get_ai_client()
    if not client:
        return moderation_result.get("reasoning", "No AI client available")

    system_prompt = """You are a product moderation assistant for an e-commerce marketplace.
Given product data and moderation analysis results, provide a concise moderation summary.
Be direct and actionable. Format as 2-3 sentences max."""

    user_prompt = f"""Product: {product_data.get('name', 'Unknown')}
Brand: {product_data.get('brand', 'N/A')}
Price: ₦{product_data.get('price', 0):,.2f}
Category: {product_data.get('category_name', 'N/A')}
Description: {(product_data.get('description') or 'N/A')[:200]}

Analysis:
- Confidence: {moderation_result['confidence']}%
- Decision: {moderation_result['decision']}
- Text score: {moderation_result['analysis']['text']['text_quality_score']}
- Price score: {moderation_result['analysis']['price']['price_score']}
- Image score: {moderation_result['analysis']['image']['image_score']}
- Issues: {moderation_result.get('reasoning', 'None')}

Write a brief moderation summary explaining the decision."""

    try:
        response = client.chat.completions.create(
            model=get_active_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI summary generation failed: {e}")
        return moderation_result.get("reasoning", "AI summary unavailable")
