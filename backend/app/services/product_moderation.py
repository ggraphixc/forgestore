"""
AI-Powered Product Moderation Service for ForgeStore.
Analyzes products for quality, policy compliance, pricing, and image standards.
Auto-approves high-confidence products, escalates uncertain ones to human review.
Supports continuous learning — admin corrections improve future thresholds.
"""
import json
import logging
import os
from typing import Optional
from app.services.ai_service import get_ai_client, get_active_model, _call_llm_sync

logger = logging.getLogger("forgestore.moderation")

# ─── Persistent Threshold Store ────────────────────────────────────

_THRESHOLDS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "moderation_thresholds.json")

DEFAULT_THRESHOLDS = {
    "approve": 75.0,
    "escalate": 50.0,
    "weights": {"text": 0.30, "price": 0.25, "image": 0.30, "inventory": 0.15},
    "updated_at": None,
    "corrections_count": 0,
    "accuracy_history": [],
}


def _load_thresholds() -> dict:
    """Load dynamic thresholds from file. Falls back to defaults."""
    try:
        if os.path.exists(_THRESHOLDS_FILE):
            with open(_THRESHOLDS_FILE, "r") as f:
                data = json.load(f)
                # Merge with defaults in case new keys were added
                merged = {**DEFAULT_THRESHOLDS, **data}
                return merged
    except Exception as e:
        logger.warning(f"Failed to load thresholds: {e}")
    return dict(DEFAULT_THRESHOLDS)


def _save_thresholds(thresholds: dict):
    """Persist thresholds to file."""
    try:
        os.makedirs(os.path.dirname(_THRESHOLDS_FILE), exist_ok=True)
        with open(_THRESHOLDS_FILE, "w") as f:
            json.dump(thresholds, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save thresholds: {e}")


def get_current_thresholds() -> dict:
    """Get current moderation thresholds (read-only)."""
    return _load_thresholds()


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
    Uses dynamic thresholds from continuous learning.
    Returns confidence score (0-100) and detailed analysis.
    """
    text_analysis = analyze_text(product_data)
    price_analysis = analyze_price(product_data)
    image_analysis = analyze_images(product_data)
    inventory_score = calculate_inventory_score(product_data)

    # Load dynamic thresholds
    thresholds = _load_thresholds()
    weights = thresholds.get("weights", DEFAULT_THRESHOLDS["weights"])
    approve_threshold = thresholds.get("approve", 75.0)
    escalate_threshold = thresholds.get("escalate", 50.0)

    # Weighted confidence score
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

    # Determine decision using dynamic thresholds
    if hard_blocks:
        decision = "REJECT"
        confidence = 0
    elif confidence >= approve_threshold:
        decision = "APPROVE"
    elif confidence >= escalate_threshold:
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
        "thresholds_used": {
            "approve": approve_threshold,
            "escalate": escalate_threshold,
            "weights": weights,
        },
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
            max_tokens=2000,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI summary generation failed: {e}")
        return moderation_result.get("reasoning", "AI summary unavailable")


# ─── Continuous Learning ───────────────────────────────────────────


def record_admin_correction(ai_decision: str, admin_decision: str, ai_confidence: float, category: str = "default"):
    """
    Record when admin corrects an AI decision.
    Triggers threshold adjustment after enough corrections accumulate.
    """
    thresholds = _load_thresholds()

    # Determine if this was a correction (AI and admin disagreed)
    is_correction = (
        (ai_decision == "APPROVE" and admin_decision == "REJECTED") or
        (ai_decision == "REJECT" and admin_decision == "APPROVED") or
        (ai_decision == "ESCALATE" and admin_decision in ("APPROVED", "REJECTED"))
    )

    # Determine the direction of correction
    correction_type = None
    if is_correction:
        if admin_decision == "APPROVED" and ai_decision in ("REJECT", "ESCALATE"):
            correction_type = "false_reject"  # AI rejected but should have approved
        elif admin_decision == "REJECTED" and ai_decision in ("APPROVE", "ESCALATE"):
            correction_type = "false_approve"  # AI approved but should have rejected

    # Update correction count
    thresholds["corrections_count"] = thresholds.get("corrections_count", 0) + 1

    # Add to accuracy history (rolling window of 200)
    history = thresholds.get("accuracy_history", [])
    history.append({
        "ai_decision": ai_decision,
        "admin_decision": admin_decision,
        "confidence": ai_confidence,
        "is_correction": is_correction,
        "correction_type": correction_type,
        "category": category,
    })
    # Keep last 200 entries
    thresholds["accuracy_history"] = history[-200:]

    # Auto-adjust thresholds every 10 corrections
    if thresholds["corrections_count"] % 10 == 0:
        _adjust_thresholds(thresholds)

    _save_thresholds(thresholds)
    return {"is_correction": is_correction, "correction_type": correction_type}


def _adjust_thresholds(thresholds: dict):
    """
    Auto-tune thresholds based on correction history.
    If too many false rejects → lower approve threshold.
    If too many false approves → raise approve threshold.
    """
    history = thresholds.get("accuracy_history", [])
    if len(history) < 10:
        return

    recent = history[-50:]  # Look at last 50 decisions
    false_rejects = sum(1 for h in recent if h.get("correction_type") == "false_reject")
    false_approves = sum(1 for h in recent if h.get("correction_type") == "false_approve")
    total = len(recent)

    if total == 0:
        return

    false_reject_rate = false_rejects / total
    false_approve_rate = false_approves / total

    old_approve = thresholds.get("approve", 75.0)
    old_escalate = thresholds.get("escalate", 50.0)

    # If too many false rejects (>15%), lower the approve threshold (be more lenient)
    if false_reject_rate > 0.15:
        new_approve = max(60.0, old_approve - 2.0)
        new_escalate = max(35.0, old_escalate - 1.5)
        thresholds["approve"] = new_approve
        thresholds["escalate"] = new_escalate
        logger.info(f"Thresholds adjusted: approve {old_approve}→{new_approve}, escalate {old_escalate}→{new_escalate} (false_reject_rate={false_reject_rate:.1%})")

    # If too many false approves (>10%), raise the approve threshold (be stricter)
    elif false_approve_rate > 0.10:
        new_approve = min(90.0, old_approve + 2.0)
        new_escalate = min(70.0, old_escalate + 1.5)
        thresholds["approve"] = new_approve
        thresholds["escalate"] = new_escalate
        logger.info(f"Thresholds adjusted: approve {old_approve}→{new_approve}, escalate {old_escalate}→{new_escalate} (false_approve_rate={false_approve_rate:.1%})")

    # If accuracy is good (>90%), fine-tune weights based on which analyzers are most wrong
    else:
        _adjust_weights(thresholds, recent)

    thresholds["updated_at"] = str(__import__('datetime').datetime.utcnow())


def _adjust_weights(thresholds: dict, history: list):
    """
    Adjust analyzer weights based on which ones contribute most to wrong decisions.
    If text analyzer is often wrong, reduce its weight and increase others.
    """
    # This is a simplified version — in production you'd track per-analyzer accuracy
    weights = thresholds.get("weights", DEFAULT_THRESHOLDS["weights"].copy())

    # Analyze confidence distribution of corrections
    high_conf_corrections = [h for h in history if h.get("is_correction") and h.get("confidence", 0) >= 70]
    low_conf_corrections = [h for h in history if h.get("is_correction") and h.get("confidence", 0) < 50]

    # If high-confidence decisions are often wrong, the weights are miscalibrated
    if len(high_conf_corrections) > len(low_conf_corrections):
        # Nudge weights toward balance
        for key in weights:
            weights[key] = max(0.15, min(0.40, weights[key]))

        # Normalize to sum to 1.0
        total = sum(weights.values())
        if total > 0:
            for key in weights:
                weights[key] = round(weights[key] / total, 2)

        # Re-normalize if rounding caused drift
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            weights["text"] = round(weights["text"] + (1.0 - total), 2)

        thresholds["weights"] = weights
        logger.info(f"Weights adjusted: {weights}")


def get_moderation_accuracy(db) -> dict:
    """
    Calculate moderation accuracy metrics from the database.
    Returns accuracy rate, false positive/negative rates, and category breakdown.
    """
    from app.models import ProductModerationLog

    logs = db.query(ProductModerationLog).order_by(
        ProductModerationLog.created_at.desc()
    ).limit(500).all()

    if not logs:
        return {
            "total_decisions": 0,
            "accuracy_rate": 0,
            "false_positive_rate": 0,
            "false_negative_rate": 0,
            "auto_approved": 0,
            "auto_rejected": 0,
            "admin_approved": 0,
            "admin_rejected": 0,
            "corrections": 0,
            "category_accuracy": {},
            "confidence_distribution": {},
        }

    total = len(logs)
    auto_approved = sum(1 for l in logs if l.action == "auto_approve")
    auto_rejected = sum(1 for l in logs if l.action == "auto_reject")
    admin_approved = sum(1 for l in logs if l.action in ("approved", "bulk_approve"))
    admin_rejected = sum(1 for l in logs if l.action in ("rejected", "bulk_reject"))
    escalated = sum(1 for l in logs if l.action == "escalated")

    # Corrections: admin did opposite of AI suggestion
    # If AI auto-rejected but admin approved → false negative (AI was too strict)
    # If AI auto-approved but admin rejected → false positive (AI was too lenient)
    corrections = 0
    false_positives = 0
    false_negatives = 0

    for l in logs:
        ai_result = l.ai_reasoning or ""
        action = l.action
        if action == "auto_approve" and any(r.action in ("rejected", "bulk_reject") for r in logs if r.product_id == l.product_id and r.created_at > l.created_at):
            false_positives += 1
            corrections += 1
        elif action == "auto_reject" and any(r.action in ("approved", "bulk_approve") for r in logs if r.product_id == l.product_id and r.created_at > l.created_at):
            false_negatives += 1
            corrections += 1

    # Confidence distribution
    conf_dist = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    for l in logs:
        if l.ai_score is not None:
            if l.ai_score < 25:
                conf_dist["0-25"] += 1
            elif l.ai_score < 50:
                conf_dist["25-50"] += 1
            elif l.ai_score < 75:
                conf_dist["50-75"] += 1
            else:
                conf_dist["75-100"] += 1

    # Accuracy rate (decisions that weren't overridden)
    accuracy_rate = ((total - corrections) / total * 100) if total > 0 else 0
    fp_rate = (false_positives / total * 100) if total > 0 else 0
    fn_rate = (false_negatives / total * 100) if total > 0 else 0

    return {
        "total_decisions": total,
        "accuracy_rate": round(accuracy_rate, 1),
        "false_positive_rate": round(fp_rate, 1),
        "false_negative_rate": round(fn_rate, 1),
        "auto_approved": auto_approved,
        "auto_rejected": auto_rejected,
        "admin_approved": admin_approved,
        "admin_rejected": admin_rejected,
        "escalated": escalated,
        "corrections": corrections,
        "confidence_distribution": conf_dist,
        "thresholds": get_current_thresholds(),
    }
