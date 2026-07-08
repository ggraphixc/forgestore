"""
AI Service for ForgeStore — powers product descriptions, recommendations, and search.
Supports multiple AI providers: OpenAI, DeepSeek, Groq, Anthropic, OpenRouter, SiliconFlow.
"""
import json
import logging
import asyncio
from typing import Optional, List, Dict, Any
from functools import lru_cache

logger = logging.getLogger("forgestore.ai")


# ─── Provider Registry ──────────────────────────────────────────────

PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI (GPT-4o, GPT-4o-mini)",
        "sdk": "openai",
        "base_url": None,  # default https://api.openai.com/v1
        "api_key_setting": "openai_api_key",
        "model_setting": "openai_model",
        "default_model": "gpt-4o-mini",
    },
    "opencode_zen": {
        "label": "OpenCode Zen (MiMo-V2.5, DeepSeek-V4 free, Nemotron free, North-Mini free)",
        "sdk": "openai",  # OpenAI-compatible API
        "base_url": "https://opencode.ai/zen/v1",
        "api_key_setting": "opencode_zen_api_key",
        "model_setting": "opencode_zen_model",
        "default_model": "mimo-v2.5-free",
    },
}


def _get_db_setting(key: str) -> str:
    """Fetch a single setting value from the DB."""
    try:
        from app.database import SessionLocal
        from app.models import Settings as SettingsModel
        db = SessionLocal()
        try:
            setting = db.query(SettingsModel).filter(SettingsModel.key == key).first()
            val = setting.value if setting else ""
            logger.info(f"DB setting '{key}' = '{val[:20]}...' " if len(val) > 20 else f"DB setting '{key}' = '{val}'")
            return val
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to get DB setting '{key}': {e}")
        return ""


def get_active_provider() -> str:
    """Get the currently selected AI provider from DB settings.
    Falls back to opencode_zen if the configured provider has no API key."""
    configured = _get_db_setting("ai_provider") or "opencode_zen"
    config = PROVIDER_CONFIGS.get(configured)
    if config:
        api_key = _get_db_setting(config["api_key_setting"])
        if api_key:
            return configured
        # Configured provider has no key — try opencode_zen
        zen_config = PROVIDER_CONFIGS.get("opencode_zen")
        if zen_config and _get_db_setting(zen_config["api_key_setting"]):
            return "opencode_zen"
    return configured


def get_ai_client() -> Any:
    """
    Get an AI client for the currently configured provider.
    Returns None if the provider's API key is not set.
    """
    provider = get_active_provider()
    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        logger.warning(f"Unknown AI provider: {provider}")
        return None

    api_key = _get_db_setting(config["api_key_setting"])
    if not api_key:
        logger.info(f"AI provider '{provider}' has no API key configured")
        return None

    try:
        if config["sdk"] == "openai":
            import openai
            kwargs = {"api_key": api_key}
            if config["base_url"]:
                kwargs["base_url"] = config["base_url"]
            return openai.OpenAI(**kwargs)  # type: ignore[arg-type]

    except Exception as e:
        logger.error(f"Failed to init {provider} client: {e}")
        return None


def get_active_model() -> str:
    """Get the model name for the active provider."""
    provider = get_active_provider()
    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        return "gpt-4o-mini"
    model = _get_db_setting(config["model_setting"])
    return model or config["default_model"]


# ─── Unified LLM Call ──────────────────────────────────────────────


def _call_llm_sync(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 400,
    images: list[str] | None = None,
) -> Optional[str]:
    """
    Unified LLM call that works across all providers.
    Supports multimodal (images) when provider supports it (e.g. MiMo-V2.5).
    Returns the text content of the response, or None on failure.
    """
    client = get_ai_client()
    if not client:
        return None

    provider = get_active_provider()
    model = get_active_model()
    config = PROVIDER_CONFIGS.get(provider)

    try:
        # OpenAI-compatible SDK format (OpenAI, OpenCode Zen)
        user_content = [{"type": "text", "text": user_prompt}]
        if images:
            for img_url in images:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_url},
                })

        if images:
            # Multimodal: use content array
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        else:
            # Text-only: simpler format
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

        logger.info(f"Calling LLM: provider={provider}, model={model}, base_url={config.get('base_url')}")
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not resp.choices or not resp.choices[0].message:
            logger.error(f"LLM returned empty response: {resp}")
            return None
        result = resp.choices[0].message.content
        if not result:
            logger.error("LLM returned None content")
            return None
        result = result.strip()
        logger.info(f"LLM response length: {len(result)}")
        return result

    except Exception as e:
        logger.error(f"LLM call failed ({provider}/{model}): {type(e).__name__}: {e}")
        return None


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 400,
    images: list[str] | None = None,
) -> Optional[str]:
    """
    Synchronous LLM call — delegates to _call_llm_sync.
    """
    return _call_llm_sync(system_prompt, user_prompt, temperature, max_tokens, images)


async def _call_llm_async(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 400,
    images: list[str] | None = None,
) -> Optional[str]:
    """
    Async wrapper around _call_llm_sync.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _call_llm_sync,
        system_prompt,
        user_prompt,
        temperature,
        max_tokens,
        images,
    )


# ─── ADMIN: Product Description Generator ───────────────────────────


def generate_product_description(
    product_name: str,
    category: str = "",
    brand: str = "",
    keywords: str = "",
    tone: str = "professional",
    images: list[str] | None = None,
) -> Optional[str]:
    """
    Generate a rich, marketing-enriched product description using AI.
    Supports multimodal: if images are provided, the AI analyzes them to write a description
    that matches the visual attributes of the product.
    Returns None if AI is not configured.
    """
    tone_descriptions = {
        "professional": "confident, authoritative, and trustworthy — like a premium brand speaking to discerning buyers",
        "casual": "warm, friendly, and approachable — like a helpful friend recommending something they love",
        "luxury": "elegant, aspirational, and indulgent — evoking exclusivity and refined taste",
        "technical": "precise, detail-rich, and specification-forward — speaking to informed buyers who care about the numbers",
        "playful": "fun, energetic, and enthusiastic — making shopping feel exciting and delightful",
        "minimalist": "clean, refined, and intentional — letting the product speak for itself with few powerful words",
    }
    tone_desc = tone_descriptions.get(tone, tone_descriptions["professional"])

    image_context = ""
    if images:
        image_context = (
            f"\n\nVISUAL CONTEXT: You have been provided with {len(images)} product image(s). "
            f"Analyze them carefully and incorporate visual details into the description — "
            f"color, texture, material, design elements, form factor, packaging, and any "
            f"visible features. The description must reflect what a customer would see."
        )

    system_prompt = (
        f"You are an elite e-commerce copywriter who crafts descriptions that convert browsers into buyers. "
        f"Write in a {tone_desc} tone.\n\n"
        f"RULES:\n"
        f"- NO code, NO markdown syntax, NO bullet-point lists with dashes\n"
        f"- Use rich, evocative language — sensory words, power verbs, benefit-driven phrasing\n"
        f"- Structure: Hook paragraph → Key features (2-3 benefit-rich sentences) → Emotional appeal → Call to action\n"
        f"- Each sentence should paint a picture and answer 'why should I care?'\n"
        f"- 150-300 words, broken into 3-5 natural paragraphs\n"
        f"- Include the product name naturally in the opening\n"
        f"- If brand is provided, reference it with authority\n"
        f"- End with a compelling call to action that creates urgency"
        f"{image_context}"
    )

    parts = [f"Product: {product_name}"]
    if category:
        parts.append(f"Category: {category}")
    if brand:
        parts.append(f"Brand: {brand}")
    if keywords:
        parts.append(f"Keywords: {keywords}")
    user_prompt = "\n".join(parts)

    return _call_llm(system_prompt, user_prompt, temperature=0.75, max_tokens=600, images=images)


def generate_product_tags(
    product_name: str,
    description: str = "",
) -> Optional[List[str]]:
    """
    Generate relevant tags/keywords for a product.
    """
    result = _call_llm(
        system_prompt=(
            "Generate 5-8 comma-separated SEO tags for this product. "
            "Return ONLY the tags, no preamble."
        ),
        user_prompt=f"Product: {product_name}\nDescription: {description[:500]}",
        temperature=0.3,
        max_tokens=150,
    )

    if result:
        return [t.strip() for t in result.split(",") if t.strip()]
    return None


# ─── WEB: AI Product Recommendations ────────────────────────────────


def get_ai_recommendations(
    current_product: Dict[str, Any],
    all_products: List[Dict[str, Any]],
    max_results: int = 4,
) -> Optional[List[Dict[str, Any]]]:
    """
    Use AI to recommend products based on the current product's attributes.
    Falls back to same-category / same-retailer recommendations if AI is off.
    """
    client = get_ai_client()
    if not client or len(all_products) < 3:
        return None

    product_list = [
        {
            "id": p["id"],
            "name": p["name"],
            "category": p.get("category", ""),
            "brand": p.get("brand", ""),
            "price": p.get("price", 0),
            "description": (p.get("description", "") or "")[:100],
        }
        for p in all_products
        if p["id"] != current_product["id"]
    ]

    result = _call_llm(
        system_prompt=(
            "You are a product recommendation engine. "
            "Given the current product and a list of other products, "
            "return a JSON array of up to 4 product IDs ranked by relevance. "
            "Consider category, price range, brand, and complementary items. "
            "Return ONLY valid JSON, no other text."
        ),
        user_prompt=(
            f"Current product: {json.dumps(current_product)}\n"
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
                ordered = [p for p in all_products if p["id"] in id_order]
                ordered.sort(key=lambda p: id_order.get(p["id"], 999))
                return ordered[:max_results]
        except Exception as e:
            logger.warning(f"Failed to parse AI recommendations: {e}")

    # Fallback to basic recommendations
    fallback = [
        p for p in all_products
        if p["id"] != current_product["id"] and (
            p.get("category") == current_product.get("category") or
            p.get("retailer_id") == current_product.get("retailer_id")
        )
    ]
    return fallback[:max_results]


# ─── WEB: AI Search Assistant ───────────────────────────────────────


def ai_search_assistant(
    query: str,
    products: List[Dict[str, Any]],
    max_results: int = 6,
) -> Optional[Dict[str, Any]]:
    """
    AI-powered search that understands natural language queries.
    Returns refined results + a helpful message.
    """
    if not query.strip():
        return None

    product_list = [
        {
            "id": p["id"],
            "name": p["name"],
            "category": p.get("category", ""),
            "brand": p.get("brand", ""),
            "price": p.get("price", 0),
            "description": (p.get("description", "") or "")[:150],
        }
        for p in products
    ]

    result = _call_llm(
        system_prompt=(
            "You are a shopping assistant. Given a user's search query "
            "and a list of available products, return a JSON object with:\n"
            '- "refined_query": a better search term (or same)\n'
            '- "message": a helpful 1-sentence response to the user\n'
            '- "product_ids": array of up to 6 product IDs that match\n'
            "Return ONLY valid JSON, no other text."
        ),
        user_prompt=f"Query: {query}\nProducts: {json.dumps(product_list)}",
        temperature=0.3,
        max_tokens=400,
    )

    if result:
        try:
            text = result
            if "```" in text:
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()
            return json.loads(text)
        except Exception as e:
            logger.warning(f"Failed to parse AI search result: {e}")

    return None


# ─── Known Settings Definitions ─────────────────────────────────────


SETTINGS_DEFINITIONS: List[Dict[str, Any]] = [
    # ── Global ──
    {"key": "site_name", "category": "global", "type": "text", "label": "Site Name",
     "description": "The name displayed throughout the storefront.", "default": "ForgeStore"},
    {"key": "site_tagline", "category": "global", "type": "text", "label": "Site Tagline",
     "description": "A short tagline shown in the header.", "default": "Your One-Stop Marketplace"},
    {"key": "contact_phone", "category": "global", "type": "text", "label": "Contact Phone Number",
     "description": "Phone number displayed on the storefront and support pages.", "default": ""},
    {"key": "business_hours", "category": "global", "type": "text", "label": "Business Hours",
     "description": "Operating hours shown on the storefront (e.g. Mon-Fri 9am-6pm).", "default": ""},
    {"key": "currency", "category": "global", "type": "select", "label": "Default Currency",
     "description": "The currency used for all prices on the storefront.",
     "default": "NGN",
     "options": [{"value": "NGN", "label": "₦ NGN (Nigerian Naira)"},
                 {"value": "USD", "label": "$ USD (US Dollar)"},
                 {"value": "GBP", "label": "£ GBP (British Pound)"},
                 {"value": "EUR", "label": "€ EUR (Euro)"}]},
    {"key": "site_timezone", "category": "global", "type": "select", "label": "Timezone",
     "description": "Default timezone for orders and analytics.",
     "default": "Africa/Lagos",
     "options": [{"value": "Africa/Lagos", "label": "WAT (Africa/Lagos)"},
                 {"value": "UTC", "label": "UTC"},
                 {"value": "America/New_York", "label": "EST (America/New_York)"},
                 {"value": "Europe/London", "label": "GMT (Europe/London)"}]},
    {"key": "maintenance_mode", "category": "global", "type": "boolean", "label": "Maintenance Mode",
     "description": "When enabled, only admins can access the site.", "default": "false"},

    # ── Design ──
    {"key": "primary_color", "category": "design", "type": "select", "label": "Primary Color",
     "description": "The primary brand color for buttons and accents.",
     "default": "amber",
     "options": [{"value": "amber", "label": "Amber"},
                 {"value": "blue", "label": "Blue"},
                 {"value": "emerald", "label": "Emerald"},
                 {"value": "purple", "label": "Purple"},
                 {"value": "rose", "label": "Rose"},
                 {"value": "stone", "label": "Stone"}]},
    {"key": "theme_mode", "category": "design", "type": "select", "label": "Theme Mode",
     "description": "Default color scheme for the storefront.",
     "default": "light",
     "options": [{"value": "light", "label": "Light"},
                 {"value": "dark", "label": "Dark"},
                 {"value": "system", "label": "System Preference"}]},
    {"key": "logo_url", "category": "design", "type": "file", "label": "Logo Image",
     "description": "Upload the site logo image.", "default": ""},
    {"key": "favicon_url", "category": "design", "type": "file", "label": "Favicon Image",
     "description": "Upload the favicon image.", "default": ""},
    {"key": "font_family", "category": "design", "type": "select", "label": "Font Family",
     "description": "Main font for the storefront.",
     "default": "inter",
     "options": [{"value": "inter", "label": "Inter"},
                 {"value": "system", "label": "System UI"},
                 {"value": "serif", "label": "Serif"}]},

    # ── Technical ──
    {"key": "inventory_threshold", "category": "technical", "type": "number", "label": "Low Stock Threshold",
     "description": "Inventory count at which low-stock alerts are triggered.", "default": "5"},
    {"key": "max_upload_size_mb", "category": "technical", "type": "number", "label": "Max Upload Size (MB)",
     "description": "Maximum file size for product images.", "default": "10"},
    {"key": "image_quality", "category": "technical", "type": "number", "label": "Image Quality %",
     "description": "JPEG quality for compressed product images.", "default": "85"},
    {"key": "session_timeout_minutes", "category": "technical", "type": "number", "label": "Session Timeout (minutes)",
     "description": "Admin session timeout duration.", "default": "1440"},

    # ── Optional Features ──
    {"key": "newsletter_enabled", "category": "optional", "type": "boolean", "label": "Newsletter Signup",
     "description": "Show newsletter signup form on the homepage.", "default": "true"},
    {"key": "reviews_auto_approve", "category": "optional", "type": "boolean", "label": "Auto-Approve Reviews",
     "description": "Product reviews are published without manual approval.", "default": "false"},
    {"key": "guest_checkout", "category": "optional", "type": "boolean", "label": "Guest Checkout",
     "description": "Allow customers to checkout without an account.", "default": "true"},
    {"key": "max_discount_percent", "category": "optional", "type": "number", "label": "Max Discount %",
     "description": "Maximum allowed discount percentage.", "default": "70"},
    {"key": "wishlist_enabled", "category": "optional", "type": "boolean", "label": "Wishlist Feature",
     "description": "Enable product wishlist for customers.", "default": "true"},
    {"key": "ai_assistant_enabled", "category": "optional", "type": "boolean", "label": "AI Shopping Assistant",
     "description": "Enable the AI-powered shopping assistant that helps customers find products, compare options, and get personalized recommendations via chat.", "default": "true"},
    {"key": "ai_recommendations_enabled", "category": "optional", "type": "boolean", "label": "AI Product Recommendations",
     "description": "Show AI-powered product recommendations on product pages and throughout the store based on browsing history, cart contents, and popular items.", "default": "true"},
    {"key": "whatsapp_notifications_enabled", "category": "optional", "type": "boolean", "label": "WhatsApp Order Notifications",
     "description": "Send order status updates (placed, confirmed, shipped, delivered) to customers and vendors via WhatsApp free-form messages.", "default": "true"},

    # ── Developer ──
    {"key": "brevo_api_key", "category": "developer", "type": "password", "label": "Brevo API Key",
     "description": "Brevo SMTP API v3 key for transactional emails (Brevo > SMTP & API > API Keys).", "default": ""},
    {"key": "mail_from_email", "category": "developer", "type": "text", "label": "Sender Email Address",
     "description": "Email address used as the 'From' field for all outgoing emails via Brevo.", "default": "noreply@forgestore.com"},
    {"key": "mail_console_fallback", "category": "developer", "type": "boolean", "label": "Console Fallback Mode",
     "description": "When enabled, all emails are printed to terminal instead of sending via API (useful for development).", "default": "true"},
    {"key": "ai_provider", "category": "developer", "type": "select", "label": "AI Provider",
     "description": "Which AI provider to use for product descriptions, search, and recommendations.",
     "default": "opencode_zen",
     "options": [{"value": "opencode_zen", "label": "OpenCode Zen (MiMo-V2.5 free multimodal)"},
                 {"value": "openai", "label": "OpenAI (GPT-4o, GPT-4o-mini)"}]},
    {"key": "opencode_zen_api_key", "category": "developer", "type": "password", "label": "OpenCode Zen API Key",
     "description": "API key from opencode.ai/zen. Free tier available.", "default": ""},
    {"key": "opencode_zen_model", "category": "developer", "type": "text", "label": "OpenCode Zen Model",
     "description": "Free models: mimo-v2.5-free, deepseek-v4-flash-free, nemotron-3-ultra-free, north-mini-code-free", "default": "mimo-v2.5-free"},
    {"key": "openai_api_key", "category": "developer", "type": "password", "label": "OpenAI API Key",
     "description": "Required for OpenAI provider.", "default": ""},
    {"key": "openai_model", "category": "developer", "type": "text", "label": "OpenAI Model",
     "description": "e.g. gpt-4o-mini, gpt-4o, gpt-4-turbo", "default": "gpt-4o-mini"},
    {"key": "debug_mode", "category": "developer", "type": "boolean", "label": "Debug Mode",
     "description": "Enable detailed error logging.", "default": "false"},
    {"key": "cors_origins", "category": "developer", "type": "text", "label": "CORS Origins",
     "description": "Comma-separated list of allowed CORS origins.", "default": ""},
    {"key": "webhook_url", "category": "developer", "type": "text", "label": "Order Webhook URL",
     "description": "URL called when a new order is placed.", "default": ""},
    {"key": "default_payment_provider", "category": "developer", "type": "select", "label": "Default Payment Provider",
     "description": "Which payment gateway to use as the primary option.",
     "default": "paystack",
     "options": [{"value": "paystack", "label": "Paystack"}]},

    # ── Logistics ──
    {"key": "default_shipping_fee", "category": "logistics", "type": "number", "label": "Default Shipping Fee",
     "description": "Flat shipping fee charged per order.", "default": "0"},
    {"key": "free_shipping_threshold", "category": "logistics", "type": "number", "label": "Free Shipping Threshold",
     "description": "Order amount above which shipping is free (0=disabled).", "default": "0"},
    {"key": "tax_percentage", "category": "logistics", "type": "number", "label": "Tax Percentage",
     "description": "Sales tax / VAT percentage applied to orders.", "default": "0"},
    {"key": "return_window_days", "category": "logistics", "type": "number", "label": "Return Window (days)",
     "description": "Number of days customers have to return items.", "default": "14"},
    {"key": "max_order_items", "category": "logistics", "type": "number", "label": "Max Items Per Order",
     "description": "Maximum quantity of items allowed in a single order.", "default": "50"},
    {"key": "logistics_auto_dispatch_enabled", "category": "logistics", "type": "boolean", "label": "Auto-Dispatch Shipments",
     "description": "Automatically assign shipments when orders enter PROCESSING status.", "default": "true"},

    # ── Multi-Vendor / Affiliate ──
    {"key": "vendor_to_vendor_percentage_cut", "category": "global", "type": "number", "label": "Vendor-to-Vendor Affiliate %",
     "description": "Percentage cut credited to the referring vendor when an invited vendor makes a sale.", "default": "2.5"},
    {"key": "vendor_to_customer_points_per_signup", "category": "global", "type": "number", "label": "Customer Signup Points",
     "description": "Attribute points credited to a vendor when a customer joins via their referral link.", "default": "10"},
    {"key": "customer_product_affiliate_commission_rate", "category": "global", "type": "number", "label": "Customer Product Affiliate %",
     "description": "Commission rate for customers sharing product affiliate links.", "default": "5.0"},
    {"key": "vendor_auto_approval_policy", "category": "global", "type": "boolean", "label": "Auto-Approve Vendors",
     "description": "When enabled, new vendor applications are automatically approved.", "default": "false"},
    {"key": "vendor_minimum_rating", "category": "global", "type": "number", "label": "Minimum Vendor Rating",
     "description": "Vendors below this rating are automatically suspended. Set 0 to disable.", "default": "3.0"},

    # ── Multi-Vendor Shipping & Point Conversions ──
    {"key": "shipping_fee_per_vendor", "category": "logistics", "type": "number", "label": "Shipping Fee Per Vendor",
     "description": "Flat shipping fee charged per distinct vendor in a multi-vendor cart checkout.", "default": "1500"},
    {"key": "points_to_currency_ratio", "category": "global", "type": "number", "label": "Points-to-Currency Ratio",
     "description": "How many attribute points equal 1 unit of currency (e.g. 100 points = ₦1,000 → ratio=100).", "default": "100"},

    # ── Commission & Settlement ──
    {"key": "market_commission_percentage", "category": "global", "type": "number", "label": "Market Commission %",
     "description": "Platform commission percentage deducted from each vendor sale before payout.", "default": "10.0"},

    # ── Low-Stock Alerts ──
    {"key": "low_stock_limit", "category": "logistics", "type": "number", "label": "Low Stock Alert Threshold",
     "description": "Inventory level at which vendors receive low-stock warnings.", "default": "5"},

    # ── Other ──
    {"key": "analytics_id", "category": "other", "type": "text", "label": "Analytics ID",
     "description": "Google Analytics / tracking ID.", "default": ""},
    {"key": "social_links", "category": "other", "type": "json", "label": "Social Media Links (JSON)",
     "description": "JSON object of social platform URLs.", "default": "{}"},
    {"key": "custom_css", "category": "other", "type": "textarea", "label": "Custom CSS",
     "description": "Extra CSS injected into the storefront header.", "default": ""},
    {"key": "custom_js", "category": "other", "type": "textarea", "label": "Custom JavaScript",
     "description": "Extra JavaScript injected into the storefront footer.", "default": ""},
    {"key": "terms_url", "category": "other", "type": "text", "label": "Terms of Service URL",
     "description": "Link to terms of service page.", "default": ""},
    {"key": "privacy_url", "category": "other", "type": "text", "label": "Privacy Policy URL",
     "description": "Link to privacy policy page.", "default": ""},
]


# ─── Settings Permission Map ────────────────────────────────────────

# Maps setting categories to the permission string required to view/edit them.
SETTINGS_PERMISSIONS = {
    "global": "settings",
    "design": "settings",
    "technical": "settings",
    "optional": "settings",
    "developer": "settings",
    "logistics": "settings",
    "other": "settings",
}
