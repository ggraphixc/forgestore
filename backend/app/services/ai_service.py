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

PROVIDER_CONFIGS = {
    "openai": {
        "label": "OpenAI (GPT-4o, GPT-4o-mini)",
        "sdk": "openai",
        "base_url": None,  # default https://api.openai.com/v1
        "api_key_setting": "openai_api_key",
        "model_setting": "openai_model",
        "default_model": "gpt-4o-mini",
    },
    "deepseek": {
        "label": "DeepSeek (DeepSeek-V3, DeepSeek-R1)",
        "sdk": "openai",  # OpenAI-compatible API
        "base_url": "https://api.deepseek.com/v1",
        "api_key_setting": "deepseek_api_key",
        "model_setting": "deepseek_model",
        "default_model": "deepseek-chat",
    },
    "groq": {
        "label": "Groq (Llama 3, Mixtral, Gemma)",
        "sdk": "openai",  # OpenAI-compatible API
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_setting": "groq_api_key",
        "model_setting": "groq_model",
        "default_model": "llama3-70b-8192",
    },
    "anthropic": {
        "label": "Anthropic (Claude 3 Haiku, Sonnet, Opus)",
        "sdk": "anthropic",
        "base_url": None,
        "api_key_setting": "anthropic_api_key",
        "model_setting": "anthropic_model",
        "default_model": "claude-3-haiku-20240307",
    },
    "openrouter": {
        "label": "OpenRouter (Mistral, Gemini, Llama free models)",
        "sdk": "openai",  # OpenAI-compatible API
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_setting": "openrouter_api_key",
        "model_setting": "openrouter_model",
        "default_model": "mistralai/mistral-7b-instruct:free",
    },
    "siliconflow": {
        "label": "SiliconFlow (Qwen, GLM, DeepSeek models)",
        "sdk": "openai",  # OpenAI-compatible API
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_setting": "siliconflow_api_key",
        "model_setting": "siliconflow_model",
        "default_model": "Qwen/Qwen2-7B-Instruct",
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
            return setting.value if setting else ""
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to get DB setting '{key}': {e}")
        return ""


def get_active_provider() -> str:
    """Get the currently selected AI provider from DB settings."""
    return _get_db_setting("ai_provider") or "openai"


def get_ai_client():
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
            return openai.OpenAI(**kwargs)

        elif config["sdk"] == "anthropic":
            import anthropic
            return anthropic.Anthropic(api_key=api_key)

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
) -> Optional[str]:
    """
    Unified LLM call that works across all providers.
    Returns the text content of the response, or None on failure.
    """
    client = get_ai_client()
    if not client:
        return None

    provider = get_active_provider()
    model = get_active_model()
    config = PROVIDER_CONFIGS.get(provider)

    try:
        if config and config["sdk"] == "anthropic":
            # Anthropic SDK format
            resp = client.messages.create(
                model=model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.content[0].text.strip()

        else:
            # OpenAI-compatible SDK format (OpenAI, DeepSeek, Groq,
            # OpenRouter, SiliconFlow, etc.)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"LLM call failed ({provider}/{model}): {e}")
        return None


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 400,
) -> Optional[str]:
    """
    Synchronous LLM call — delegates to _call_llm_sync.
    Exists as a thin wrapper so importers can use `_call_llm` without
    changing their code after the sync→async refactor.
    """
    return _call_llm_sync(system_prompt, user_prompt, temperature, max_tokens)


async def _call_llm_async(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 400,
) -> Optional[str]:
    """
    Async wrapper around _call_llm_sync that offloads the blocking
    HTTP call to a thread pool, preventing the uvicorn worker from
    being blocked during AI requests.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _call_llm_sync,
        system_prompt,
        user_prompt,
        temperature,
        max_tokens,
    )


# ─── ADMIN: Product Description Generator ───────────────────────────


def generate_product_description(
    product_name: str,
    category: str = "",
    brand: str = "",
    keywords: str = "",
    tone: str = "professional",
) -> Optional[str]:
    """
    Generate a rich product description using AI.
    Returns None if AI is not configured.
    """
    system_prompt = (
        f"You are a professional e-commerce copywriter. "
        f"Write a compelling product description in a {tone} tone. "
        f"Format with short paragraphs. Include features, benefits, "
        f"and a call to action. Keep it 100-200 words."
    )

    user_prompt = (
        f"Product: {product_name}\n"
        f"{'Category: ' + category if category else ''}\n"
        f"{'Brand: ' + brand if brand else ''}\n"
        f"{'Keywords: ' + keywords if keywords else ''}"
    )

    return _call_llm(system_prompt, user_prompt, temperature=0.7, max_tokens=400)


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
    {"key": "logo_url", "category": "design", "type": "text", "label": "Logo URL",
     "description": "URL to the site logo image.", "default": ""},
    {"key": "favicon_url", "category": "design", "type": "text", "label": "Favicon URL",
     "description": "URL to the favicon image.", "default": ""},
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
    {"key": "cache_ttl_seconds", "category": "technical", "type": "number", "label": "Cache TTL (seconds)",
     "description": "How long pages are cached.", "default": "300"},
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

    # ── Developer ──
    {"key": "smtp_host", "category": "developer", "type": "text", "label": "SMTP Host",
     "description": "SMTP server hostname (e.g. smtp.gmail.com).", "default": ""},
    {"key": "smtp_port", "category": "developer", "type": "number", "label": "SMTP Port",
     "description": "SMTP server port (587 for TLS, 465 for SSL).", "default": "587"},
    {"key": "smtp_user", "category": "developer", "type": "text", "label": "SMTP Username",
     "description": "SMTP login username (usually your full email address).", "default": ""},
    {"key": "smtp_password", "category": "developer", "type": "password", "label": "SMTP Password",
     "description": "SMTP login password (use Gmail App Password for Gmail).", "default": ""},
    {"key": "from_email", "category": "developer", "type": "text", "label": "From Email Address",
     "description": "Email address shown in the 'From' field of all outgoing emails.", "default": "noreply@forgestore.com"},
    {"key": "ai_provider", "category": "developer", "type": "select", "label": "AI Provider",
     "description": "Which AI provider to use for product descriptions, search, and recommendations.",
     "default": "openai",
     "options": [{"value": "openai", "label": "OpenAI (GPT-4o, GPT-4o-mini)"},
                 {"value": "deepseek", "label": "DeepSeek (DeepSeek-V3, R1)"},
                 {"value": "groq", "label": "Groq (Llama 3, Mixtral, Gemma)"},
                 {"value": "anthropic", "label": "Anthropic (Claude 3 Haiku, Sonnet, Opus)"},
                 {"value": "openrouter", "label": "OpenRouter (Mistral, Gemini, Llama free models)"},
                 {"value": "siliconflow", "label": "SiliconFlow (Qwen, GLM, DeepSeek models)"}]},
    {"key": "openai_api_key", "category": "developer", "type": "password", "label": "OpenAI API Key",
     "description": "Required for OpenAI provider.", "default": ""},
    {"key": "openai_model", "category": "developer", "type": "text", "label": "OpenAI Model",
     "description": "e.g. gpt-4o-mini, gpt-4o, gpt-4-turbo", "default": "gpt-4o-mini"},
    {"key": "deepseek_api_key", "category": "developer", "type": "password", "label": "DeepSeek API Key",
     "description": "Required for DeepSeek provider.", "default": ""},
    {"key": "deepseek_model", "category": "developer", "type": "text", "label": "DeepSeek Model",
     "description": "e.g. deepseek-chat, deepseek-reasoner", "default": "deepseek-chat"},
    {"key": "groq_api_key", "category": "developer", "type": "password", "label": "Groq API Key",
     "description": "Required for Groq provider.", "default": ""},
    {"key": "groq_model", "category": "developer", "type": "text", "label": "Groq Model",
     "description": "e.g. llama3-70b-8192, mixtral-8x7b-32768", "default": "llama3-70b-8192"},
    {"key": "anthropic_api_key", "category": "developer", "type": "password", "label": "Anthropic API Key",
     "description": "Required for Anthropic provider.", "default": ""},
    {"key": "anthropic_model", "category": "developer", "type": "text", "label": "Anthropic Model",
     "description": "e.g. claude-3-haiku-20240307, claude-3-sonnet-20240229", "default": "claude-3-haiku-20240307"},
    {"key": "openrouter_api_key", "category": "developer", "type": "password", "label": "OpenRouter API Key",
     "description": "Required for OpenRouter provider.", "default": ""},
    {"key": "openrouter_model", "category": "developer", "type": "text", "label": "OpenRouter Model",
     "description": "e.g. mistralai/mistral-7b-instruct:free, google/gemini-flash-1.5-8b:free", "default": "mistralai/mistral-7b-instruct:free"},
    {"key": "siliconflow_api_key", "category": "developer", "type": "password", "label": "SiliconFlow API Key",
     "description": "Required for SiliconFlow provider.", "default": ""},
    {"key": "siliconflow_model", "category": "developer", "type": "text", "label": "SiliconFlow Model",
     "description": "e.g. Qwen/Qwen2-7B-Instruct, deepseek-ai/deepseek-v2-chat", "default": "Qwen/Qwen2-7B-Instruct"},
    {"key": "debug_mode", "category": "developer", "type": "boolean", "label": "Debug Mode",
     "description": "Enable detailed error logging.", "default": "false"},
    {"key": "cors_origins", "category": "developer", "type": "text", "label": "CORS Origins",
     "description": "Comma-separated list of allowed CORS origins.", "default": ""},
    {"key": "webhook_url", "category": "developer", "type": "text", "label": "Order Webhook URL",
     "description": "URL called when a new order is placed.", "default": ""},

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
