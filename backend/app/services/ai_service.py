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

    logger.info(f"Creating AI client: provider={provider}, model={get_active_model()}, base_url={config.get('base_url')}, api_key_prefix={api_key[:8]}...")

    try:
        if config["sdk"] == "openai":
            import openai
            kwargs = {"api_key": api_key, "timeout": 25.0}
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
    Supports multimodal (images) — fetches URLs and converts to base64 data URLs.
    Falls back to text-only if multimodal fails.
    Returns the text content of the response, or None on failure.
    """
    client = get_ai_client()
    if not client:
        return None

    provider = get_active_provider()
    model = get_active_model()
    config = PROVIDER_CONFIGS.get(provider)

    def _do_call(msgs):
        resp = client.chat.completions.create(
            model=model,
            messages=msgs,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.info(f"LLM response: choices={len(resp.choices) if resp.choices else 0}, finish_reason={resp.choices[0].finish_reason if resp.choices and resp.choices[0] else 'N/A'}")
        if not resp.choices or not resp.choices[0].message:
            logger.error(f"LLM returned empty response: {resp}")
            return None
        content = resp.choices[0].message.content
        # Some providers return content as a list of blocks — extract text
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif isinstance(block, str):
                    texts.append(block)
            content = "\n".join(texts) if texts else None
        logger.info(f"LLM content type={type(content)}, len={len(content) if content else 0}, preview={repr(content[:200]) if content else 'None'}")
        return content

    def _url_to_data_url(url: str) -> str | None:
        """Fetch an image URL and convert to base64 data URL."""
        try:
            import base64
            import urllib.request
            # Determine MIME type from URL
            lower = url.lower()
            if ".png" in lower:
                mime = "image/png"
            elif ".webp" in lower:
                mime = "image/webp"
            elif ".gif" in lower:
                mime = "image/gif"
            else:
                mime = "image/jpeg"
            # Fetch with timeout
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                img_data = resp.read()
            # Limit to 200KB
            if len(img_data) > 200_000:
                # Resize using Pillow
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(img_data))
                    img.thumbnail((800, 800), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=75)
                    img_data = buf.getvalue()
                    mime = "image/jpeg"
                except Exception:
                    # Truncate if Pillow not available
                    img_data = img_data[:200_000]
            b64 = base64.b64encode(img_data).decode("utf-8")
            return f"data:{mime};base64,{b64}"
        except Exception as e:
            logger.warning(f"Failed to fetch image {url[:80]}: {e}")
            return None

    try:
        logger.info(f"Calling LLM: provider={provider}, model={model}, base_url={config.get('base_url')}, has_images={bool(images)}")

        # Try multimodal if images provided
        if images:
            data_urls = []
            for img in images[:3]:
                if img.startswith("data:"):
                    # Already a data URL — check size
                    if len(img) <= 600_000:
                        data_urls.append(img)
                        logger.info(f"Using inline data URL ({len(img)} bytes)")
                elif img.startswith("http"):
                    # Fetch and convert to base64
                    logger.info(f"Fetching image: {img[:80]}...")
                    du = _url_to_data_url(img)
                    if du:
                        data_urls.append(du)
                        logger.info(f"Converted to data URL ({len(du)} bytes)")
                    else:
                        logger.warning(f"Failed to convert image to data URL: {img[:80]}")

            logger.info(f"Prepared {len(data_urls)} images for multimodal call")
            if data_urls:
                user_content = [{"type": "text", "text": user_prompt}]
                for du in data_urls:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": du},
                    })
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]
                try:
                    result = _do_call(messages)
                    if result and result.strip():
                        logger.info(f"Multimodal LLM response length: {len(result)}")
                        return result.strip()
                    logger.warning("Multimodal call returned empty/None, falling back to text-only")
                except Exception as e:
                    logger.warning(f"Multimodal call failed ({e}), falling back to text-only")

        # Text-only fallback
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        result = _do_call(messages)
        if not result:
            logger.error("LLM returned None content (text-only)")
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


def generate_product_specifications(
    product_name: str,
    category: str = "",
    brand: str = "",
    description: str = "",
    images: list[str] | None = None,
) -> Optional[dict]:
    """
    Generate product specifications (key-value pairs) using AI.
    Analyzes product name, description, category, and images.
    Returns a dict of {spec_name: spec_value} or None on failure.
    """
    system_prompt = (
        "You are a technical product analyst for an e-commerce store. "
        "Your job is to list the key specifications a buyer would want to know.\n\n"
        "For each product, list 5-10 specifications as key-value pairs. "
        "Use this exact format for each line:\n"
        "Key: Value\n\n"
        "Examples:\n"
        "Material: 100% Premium Cotton\n"
        "Weight: 250g\n"
        "Color: Midnight Black\n"
        "Care: Machine washable at 30°C\n"
        "Warranty: 2 years manufacturer warranty\n"
        "Origin: Made in Portugal\n\n"
        "Do NOT use JSON format. Do NOT use markdown. "
        "Just write each spec on its own line as Key: Value."
    )

    parts = [f"Product: {product_name}"]
    if category:
        parts.append(f"Category: {category}")
    if brand:
        parts.append(f"Brand: {brand}")
    if description:
        parts.append(f"Description: {description[:500]}")
    user_prompt = "\n".join(parts)

    result = _call_llm(system_prompt, user_prompt, temperature=0.3, max_tokens=500, images=images)

    if result:
        import re
        specs = {}
        # Parse "Key: Value" lines
        for line in result.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Try splitting on first colon
            match = re.match(r'^([^:]+):\s*(.+)$', line)
            if match:
                key = match.group(1).strip().strip('*').strip('#').strip()
                val = match.group(2).strip().strip('*').strip()
                if key and val:
                    specs[key] = val
        if specs:
            return specs

        # Fallback: try JSON parsing if the model returned JSON anyway
        import json
        try:
            specs = json.loads(result)
            if isinstance(specs, dict):
                return specs
        except json.JSONDecodeError:
            pass
        try:
            match = re.search(r'\{[^{}]*\}', result, re.DOTALL)
            if match:
                specs = json.loads(match.group(0))
                if isinstance(specs, dict):
                    return specs
        except json.JSONDecodeError:
            pass
    return None


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


def optimize_product_title(
    product_name: str,
    category: str = "",
    brand: str = "",
) -> Optional[str]:
    """
    Optimize a product title for search discoverability and marketplace best practices.
    Returns a single optimized title string or None.
    """
    system_prompt = (
        "You are an e-commerce title optimization expert. "
        "Rewrite the product title to be:\n"
        "- Clear, concise, and search-friendly\n"
        "- Follows marketplace best practices: Brand + Key Feature + Product Type + Differentiator\n"
        "- Max 80 characters\n"
        "- Include the most important keyword early\n"
        "- No fluff, no ALL CAPS, no excessive punctuation\n\n"
        "Return ONLY the optimized title, nothing else."
    )
    parts = [f"Current title: {product_name}"]
    if category:
        parts.append(f"Category: {category}")
    if brand:
        parts.append(f"Brand: {brand}")
    user_prompt = "\n".join(parts)
    return _call_llm(system_prompt, user_prompt, temperature=0.3, max_tokens=100)


def generate_pricing_advisor(
    product_name: str,
    category: str = "",
    current_price: float = 0,
    description: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Analyze a product and suggest competitive pricing strategies.
    Returns a dict with pricing advice or None.
    """
    system_prompt = (
        "You are a pricing strategy expert for an African e-commerce marketplace (prices in Nigerian Naira ₦). "
        "Analyze the product and provide pricing advice.\n\n"
        "Return a JSON object with exactly these keys:\n"
        '{'
        '  "suggested_min": <number>,'
        '  "suggested_max": <number>,'
        '  "recommended": <number>,'
        '  "strategy": "<one of: competitive, premium, value, penetration>",'
        '  "reasoning": "<1-2 sentences explaining the pricing>",'
        '  "discount_tip": "<tip on how to use discounts effectively>"'
        '}\n\n'
        "Return ONLY valid JSON, no other text."
    )
    parts = [f"Product: {product_name}"]
    if category:
        parts.append(f"Category: {category}")
    if current_price:
        parts.append(f"Current price: ₦{current_price:,.0f}")
    if description:
        parts.append(f"Description: {description[:300]}")
    user_prompt = "\n".join(parts)
    result = _call_llm(system_prompt, user_prompt, temperature=0.3, max_tokens=400)
    if result:
        import json
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            import re
            try:
                match = re.search(r'\{[^{}]*\}', result, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


def generate_product_bundle_suggestions(
    product_name: str,
    category: str = "",
    all_products: list[str] | None = None,
) -> Optional[List[Dict[str, str]]]:
    """
    Suggest complementary products to bundle with the given product.
    Returns a list of bundle suggestions or None.
    """
    system_prompt = (
        "You are a cross-selling expert for an e-commerce store. "
        "Given a product, suggest 3-5 complementary products that customers often buy together.\n\n"
        "Return a JSON array of objects, each with:\n"
        '{'
        '  "name": "<product name>",'
        '  "reason": "<1 sentence why this pairs well>"'
        '}\n\n'
        "Return ONLY valid JSON, no other text."
    )
    parts = [f"Product: {product_name}"]
    if category:
        parts.append(f"Category: {category}")
    if all_products:
        parts.append(f"Also available: {', '.join(all_products[:20])}")
    user_prompt = "\n".join(parts)
    result = _call_llm(system_prompt, user_prompt, temperature=0.5, max_tokens=400)
    if result:
        import json
        try:
            data = json.loads(result)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
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
