"""
AI-Powered Flag Triage Service for ForgeStore.
Analyzes customer product flags and routes them smartly:
- HIGH confidence → auto-suspend + notify admin + vendor
- MEDIUM confidence → keep live + escalate to admin
- LOW confidence → keep live + notify vendor to self-correct
"""
import logging
import os
import json
from typing import Optional
from app.services.ai_service import get_ai_client, get_active_model, _call_llm_sync

logger = logging.getLogger("forgestore.flag_triage")

# ─── Suspicious Keywords (counterfeit / prohibited) ────────────────

HIGH_RISK_KEYWORDS = [
    "fake", "counterfeit", "knockoff", "replica", "copy", "imitation",
    "not original", "not genuine", "not authentic", "unbranded",
    "stolen", "illegal", "banned", "restricted",
    "meth", "cocaine", "heroin", "drugs", "narcotics",
    "weapon", "gun", "firearm", "ammunition", "explosive",
    "porn", "nude", "nsfw", "sex toy",
]

MEDIUM_RISK_KEYWORDS = [
    "wrong item", "not as described", "misleading", "bait",
    "switch", "scam", "ripoff", "rip off", "terrible quality",
    "broke after", "fell apart", "dangerous", "hazard",
    "allergic reaction", "skin irritation", "rash",
]

LOW_RISK_KEYWORDS = [
    "pricing error", "wrong price", "too expensive",
    "delivery delay", "late delivery", "slow shipping",
    "minor damage", "small scratch", "cosmetic",
    "packaging", "missing instructions",
]


def _text_contains_keywords(text: str, keywords: list) -> list:
    """Return which keywords are found in text."""
    text_lower = text.lower()
    return [kw for kw in keywords if kw in text_lower]


def _calculate_flag_score(
    reason: str,
    description: str,
    product_data: dict,
    existing_flags: int,
    reporter_history: int,
) -> dict:
    """
    Rule-based pre-score before AI call.
    Returns score (0-100) and reasons.
    """
    score = 0
    reasons = []
    text = f"{reason} {description}".lower()

    # High-risk keywords (strong signal)
    high_hits = _text_contains_keywords(text, HIGH_RISK_KEYWORDS)
    if high_hits:
        score += 40
        reasons.append(f"High-risk keywords: {', '.join(high_hits)}")

    # Medium-risk keywords
    med_hits = _text_contains_keywords(text, MEDIUM_RISK_KEYWORDS)
    if med_hits:
        score += 20
        reasons.append(f"Quality/safety concerns: {', '.join(med_hits)}")

    # Low-risk keywords (less serious)
    low_hits = _text_contains_keywords(text, LOW_RISK_KEYWORDS)
    if low_hits:
        score += 5
        reasons.append(f"Minor issue: {', '.join(low_hits)}")

    # Flag count — multiple flags on same product = stronger signal
    if existing_flags >= 5:
        score += 30
        reasons.append(f"High flag count ({existing_flags} flags)")
    elif existing_flags >= 3:
        score += 20
        reasons.append(f"Multiple flags ({existing_flags} flags)")
    elif existing_flags >= 1:
        score += 10
        reasons.append(f"Repeat flag ({existing_flags} prior flags)")

    # Reporter history — serial reporters are less credible
    if reporter_history >= 5:
        score -= 15
        reasons.append("Reporter has many prior reports (low credibility)")
    elif reporter_history >= 3:
        score -= 5
        reasons.append("Reporter has prior reports")

    # Product AI moderation score — products with low AI scores are more suspicious
    ai_score = product_data.get("ai_confidence_score")
    if ai_score is not None:
        if ai_score < 40:
            score += 15
            reasons.append(f"Product has low AI quality score ({ai_score}%)")
        elif ai_score < 60:
            score += 5
            reasons.append(f"Product has moderate AI quality score ({ai_score}%)")

    # Product status — already flagged/suspended is worse
    status = product_data.get("status", "")
    if status == "SUSPENDED":
        score += 10
        reasons.append("Product is already suspended")

    # Category risk — some categories have higher counterfeit risk
    category = (product_data.get("category") or "").lower()
    high_risk_categories = ["electronics", "fashion", "beauty", "luxury"]
    if any(cat in category for cat in high_risk_categories):
        score += 5
        reasons.append(f"High-risk category: {category}")

    # Reason severity
    reason_map = {
        "counterfeit": 30,
        "prohibited": 35,
        "inappropriate": 15,
        "misleading": 10,
        "pricing_error": 5,
        "other": 5,
    }
    score += reason_map.get(reason, 5)

    return {
        "score": min(score, 100),
        "reasons": reasons,
    }


def triage_flag(
    reason: str,
    description: str,
    product_data: dict,
    existing_flags: int = 0,
    reporter_history: int = 0,
) -> dict:
    """
    AI-powered flag triage. Analyzes a product flag and determines:
    - confidence score (0-100)
    - decision: HIGH / MEDIUM / LOW
    - auto_action: suspend / escalate / notify_vendor / none
    - reasoning
    """
    # Rule-based pre-score
    rule_result = _calculate_flag_score(
        reason, description, product_data,
        existing_flags, reporter_history,
    )

    # Use AI for nuanced analysis
    product_name = product_data.get("name", "Unknown")
    product_desc = (product_data.get("description") or "")[:300]
    product_price = product_data.get("price", 0)
    category = product_data.get("category", "unknown")

    system_prompt = """You are a product quality analyst for an e-commerce marketplace.
A customer has flagged a product. Analyze the flag and determine severity.

Classify the flag into one of three categories:
- HIGH: Serious issue (counterfeit, prohibited, dangerous, multiple flags). Product should be suspended.
- MEDIUM: Credible concern (quality, misleading, safety). Needs human review.
- LOW: Minor issue (pricing error, cosmetic, subjective complaint). Vendor can self-correct.

Return ONLY valid JSON with this structure:
{
  "confidence": <0-100>,
  "decision": "HIGH" | "MEDIUM" | "LOW",
  "reasoning": "<brief explanation>",
  "recommended_action": "<what should happen>",
  "vendor_message": "<message to send the vendor>"
}"""

    user_prompt = f"""Customer flagged product:
- Name: {product_name}
- Category: {category}
- Price: ₦{product_price:,.0f}
- Description: {product_desc}

Flag details:
- Reason: {reason}
- Description: {description or 'No additional details'}
- Prior flags on this product: {existing_flags}
- Reporter's total reports: {reporter_history}

Rule-based pre-score: {rule_result['score']}/100
Rule-based reasons: {'; '.join(rule_result['reasons']) or 'None'}

Analyze and classify this flag."""

    try:
        result = _call_llm_sync(
            system_prompt, user_prompt,
            temperature=0.3, max_tokens=500,
        )
        if result:
            # Parse JSON from response
            text = result
            if "```" in text:
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()
            ai_result = json.loads(text)

            # Blend AI score with rule-based score (60% AI, 40% rules)
            blended_score = (
                ai_result.get("confidence", 50) * 0.6 +
                rule_result["score"] * 0.4
            )

            # Override with rule-based if hard keywords found
            if rule_result["score"] >= 70:
                blended_score = max(blended_score, rule_result["score"])

            # Determine final decision from blended score
            if blended_score >= 70:
                decision = "HIGH"
                auto_action = "suspend"
            elif blended_score >= 40:
                decision = "MEDIUM"
                auto_action = "escalate"
            else:
                decision = "LOW"
                auto_action = "notify_vendor"

            return {
                "confidence": round(blended_score, 1),
                "decision": decision,
                "auto_action": auto_action,
                "reasoning": ai_result.get("reasoning", ""),
                "recommended_action": ai_result.get("recommended_action", ""),
                "vendor_message": ai_result.get("vendor_message", ""),
                "rule_score": rule_result["score"],
                "rule_reasons": rule_result["reasons"],
                "ai_score": ai_result.get("confidence", 50),
            }

    except Exception as e:
        logger.error(f"AI triage failed, using rule-based: {e}")

    # Fallback to rule-based only
    if rule_result["score"] >= 70:
        decision = "HIGH"
        auto_action = "suspend"
    elif rule_result["score"] >= 40:
        decision = "MEDIUM"
        auto_action = "escalate"
    else:
        decision = "LOW"
        auto_action = "notify_vendor"

    return {
        "confidence": rule_result["score"],
        "decision": decision,
        "auto_action": auto_action,
        "reasoning": "; ".join(rule_result["reasons"]) or "No specific issues detected",
        "recommended_action": "",
        "vendor_message": "",
        "rule_score": rule_result["score"],
        "rule_reasons": rule_result["reasons"],
        "ai_score": None,
    }
