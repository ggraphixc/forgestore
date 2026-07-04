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

    def _get_user_context(self, user_id: Optional[str]) -> str:
        """Build user-specific context (preferences, order history)."""
        if not user_id:
            return json.dumps({"user": "anonymous", "preferences": {}, "recent_orders": []})

        user = self.db.query(User).filter(User.id == user_id).first()
        preferences = {}
        recent_orders = []

        pref_vector = self.db.query(UserPreferenceVector).filter(
            UserPreferenceVector.user_id == user_id
        ).first()
        if pref_vector:
            preferences = {
                "category_affinities": pref_vector.category_affinities or {},
                "price_range_prefs": pref_vector.price_range_prefs or {},
            }

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
            "user": {"name": user.name, "email": user.email},
            "preferences": preferences,
            "recent_orders": recent_orders,
        }, default=str)

    def _get_admin_context(self) -> str:
        """Build admin-specific context (revenue, orders, issues)."""
        from app.utils import utcnow
        from datetime import timedelta

        now = utcnow()
        thirty_days_ago = now - timedelta(days=30)

        # Revenue stats
        total_revenue = self.db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
            Order.status.in_(["DELIVERED", "COMPLETED"]),
            Order.created_at >= thirty_days_ago,
        ).scalar()

        # Order stats
        total_orders = self.db.query(func.count(Order.id)).filter(
            Order.created_at >= thirty_days_ago
        ).scalar()
        pending_orders = self.db.query(func.count(Order.id)).filter(
            Order.status.in_(["PENDING", "PROCESSING"])
        ).scalar()
        disputed_orders = self.db.query(func.count(Order.id)).filter(
            Order.status.in_(["DISPUTED", "REFUNDED", "CANCELLED"])
        ).scalar()

        # Vendor stats
        total_vendors = self.db.query(func.count(Retailer.id)).scalar()
        active_vendors = self.db.query(func.count(Retailer.id)).filter(
            Retailer.status == "APPROVED"
        ).scalar()

        # Low stock products
        low_stock = self.db.query(func.count(Product.id)).filter(
            Product.inventory > 0, Product.inventory < 10
        ).scalar()

        # Customer stats
        total_customers = self.db.query(func.count(User.id)).filter(
            User.role == "customer"
        ).scalar()

        return json.dumps({
            "period": "last_30_days",
            "revenue": {"total": float(total_revenue), "currency": "NGN"},
            "orders": {"total": total_orders, "pending": pending_orders, "disputed": disputed_orders},
            "vendors": {"total": total_vendors, "active": active_vendors},
            "customers": {"total": total_customers},
            "low_stock_products": low_stock,
        }, default=str)

    def _build_system_prompt(self, context: dict) -> str:
        """Build the system prompt with shopping context."""
        session_id = context.get("session_id", "")
        is_admin = session_id.startswith("admin-")

        catalog = self._get_catalog_context()
        user_ctx = self._get_user_context(context.get("user_id"))

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
- Identify issues (disputes, low stock, pending orders)
- Provide business insights and recommendations
- Answer questions about vendors, customers, and operations
- Summarize performance metrics

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
        conversation = self.memory.get_or_create_conversation(session_id, user_id)
        self.memory.add_message(conversation.id, "user", message)

        # Get conversation history
        history = self.memory.get_history(conversation.id)

        # Build context
        context = self.memory.get_context(conversation.id)
        context.update({
            "user_id": user_id,
            "session_id": session_id,
            "last_query": message,
        })

        # Build system prompt
        system_prompt = self._build_system_prompt(context)

        try:
            from app.services.ai_service import _call_llm, get_ai_client, get_active_provider, get_active_model

            provider = get_active_provider()
            model = get_active_model()
            client = get_ai_client()
            logger.info(f"AI chat: provider={provider}, model={model}, client={'ok' if client else 'NONE'}")

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
                response_text = "I apologize, but I'm having trouble processing your request right now. Please try again, or browse our catalog directly."

            # Strip any tool_call XML that the model might output
            response_text = re.sub(r'tool_call.*?/tool_call', '', response_text, flags=re.DOTALL)
            response_text = re.sub(r'function=.*?/function', '', response_text, flags=re.DOTALL)
            response_text = re.sub(r'parameter=.*?/parameter', '', response_text, flags=re.DOTALL)
            response_text = response_text.strip()

            if not response_text:
                response_text = "I'd be happy to help you find what you're looking for! Could you tell me more about what you need?"

            tokens = len(response_text.split()) * 2  # rough estimate

            # Store the assistant response
            self.memory.add_message(conversation.id, "assistant", response_text, tokens_used=tokens)

            # Update conversation context
            self.memory.update_context(conversation.id, {
                "last_query": message,
                "last_response": response_text,
            })

            return {
                "conversation_id": conversation.id,
                "response": response_text,
                "tokens_used": tokens,
                "suggestions": self._generate_suggestions(response_text, context),
            }

        except Exception as e:
            logger.error(f"AI chat error: {e}")
            return {
                "conversation_id": conversation.id,
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
