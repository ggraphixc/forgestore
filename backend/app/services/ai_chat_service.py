"""AI Shopping Assistant — System 3"""
import json
import logging
import uuid
from datetime import datetime
from app.utils import utcnow
from typing import Optional
from sqlalchemy.orm import Session

from app.models import (
    AIConversation, AIMessage, UserPreferenceVector, RecommendationCache,
    Product, Category, User,
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
    """AI-powered conversational shopping assistant with RAG architecture."""

    def __init__(self, db: Session):
        self.db = db
        self.memory = ConversationMemory(db)
        self.settings = get_settings()

    def _get_llm_client(self):
        """Get the configured AI provider client."""
        provider = self.settings.get("AI_PROVIDER", "openai")
        api_key = self.settings.get("AI_API_KEY", "")

        if provider == "anthropic":
            import anthropic
            return anthropic.Anthropic(api_key=api_key)
        else:
            import openai
            client = openai.OpenAI(api_key=api_key)
            return client

    def _build_system_prompt(self, context: dict) -> str:
        """Build the system prompt with shopping context."""
        return f"""You are ForgeAI, the intelligent shopping assistant for ForgeStore — a premium multi-vendor e-commerce marketplace.

Your capabilities:
- Help customers find products they'll love
- Compare products across different vendors
- Provide personalized recommendations
- Answer questions about products, orders, shipping, and policies
- Assist with the shopping experience

Context:
- User preferences: {json.dumps(context.get('preferences', {}), default=str)}
- Current cart items: {json.dumps(context.get('cart', {}), default=str)}
- Browsing history: {json.dumps(context.get('browsing', {}), default=str)}
- Available categories: {json.dumps(context.get('categories', []), default=str)}

Guidelines:
- Be helpful, concise, and friendly
- Recommend specific products with reasons when appropriate
- Ask clarifying questions to narrow down preferences
- Never make up pricing or product details
- If you don't know something, offer to search the catalog
- Keep responses under 200 words unless detailed information is needed
- Format product recommendations clearly with product names"""

    def chat(self, session_id: str, message: str, user_id: Optional[str] = None) -> dict:
        """Process a chat message and return AI response with context."""
        conversation = self.memory.get_or_create_conversation(session_id, user_id)
        self.memory.add_message(conversation.id, "user", message)

        # Get conversation history
        history = self.memory.get_history(conversation.id)

        # Get user preferences for context
        preferences = {}
        if user_id:
            pref_vector = self.db.query(UserPreferenceVector).filter(
                UserPreferenceVector.user_id == user_id
            ).first()
            if pref_vector:
                preferences = {
                    "category_affinities": pref_vector.category_affinities,
                    "price_range_prefs": pref_vector.price_range_prefs,
                    "brand_affinities": pref_vector.brand_affinities,
                }

        # Get available categories for context
        categories = self.db.query(Category).limit(20).all()
        category_list = [{"name": c.name, "slug": c.slug} for c in categories]

        # Get the conversation context
        context = self.memory.get_context(conversation.id)
        context.update({
            "preferences": preferences,
            "categories": category_list,
        })

        # Build system prompt
        system_prompt = self._build_system_prompt(context)

        try:
            provider = self.settings.get("AI_PROVIDER", "openai")

            if provider == "anthropic":
                response_text, tokens = self._call_anthropic(system_prompt, history, message)
            else:
                response_text, tokens = self._call_openai(system_prompt, history, message)

            # Store the assistant response
            self.memory.add_message(conversation.id, "assistant", response_text, tokens_used=tokens)

            # Update conversation context with latest interaction
            self.memory.update_context(conversation.id, {
                "last_query": message,
                "last_response": response_text,
            })

            return {
                "conversation_id": conversation.id,
                "response": response_text,
                "tokens_used": tokens,
                "suggestions": self._generate_suggestions(response_text),
            }

        except Exception as e:
            logger.error(f"AI chat error: {e}")
            return {
                "conversation_id": conversation.id,
                "response": "I apologize, but I'm having trouble processing your request right now. Please try again, or browse our catalog directly.",
                "tokens_used": 0,
                "suggestions": ["Browse categories", "View recommendations", "Track my order"],
            }

    def _call_openai(self, system_prompt: str, history: list, message: str) -> tuple[str, int]:
        """Call OpenAI API."""
        import openai
        client = openai.OpenAI(api_key=self.settings.get("AI_API_KEY", ""))

        messages = [{"role": "system", "content": system_prompt}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})

        response = client.chat.completions.create(
            model=self.settings.get("AI_MODEL", "gpt-4o-mini"),
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        return response.choices[0].message.content, response.usage.total_tokens if response.usage else 0

    def _call_anthropic(self, system_prompt: str, history: list, message: str) -> tuple[str, int]:
        """Call Anthropic API."""
        import anthropic
        client = anthropic.Anthropic(api_key=self.settings.get("AI_API_KEY", ""))

        messages = []
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})

        response = client.messages.create(
            model=self.settings.get("AI_MODEL", "claude-3-haiku-20240307"),
            system=system_prompt,
            messages=messages,
            max_tokens=500,
        )
        return response.content[0].text, response.usage.input_tokens + response.usage.output_tokens if response.usage else 0

    def _generate_suggestions(self, response: str) -> list[str]:
        """Generate follow-up suggestions based on the response."""
        suggestions = [
            "Show me more products",
            "What's popular right now?",
            "Help me find something",
        ]
        return suggestions


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
            # Return placeholder embedding
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

        # Cache the results
        if cached:
            cached.recommendations = recommendations
            cached.expires_at = utcnow()
        else:
            cached = RecommendationCache(
                context_type=context_type,
                context_id=context_id,
                recommendations=recommendations,
                expires_at=utcnow(),
            )
            self.db.add(cached)
        self.db.commit()

        return recommendations

    def _generate_recommendations(self, user_id: Optional[str], product_id: Optional[str],
                                   context_type: str, limit: int) -> list[dict]:
        """Generate recommendations based on context."""
        if context_type == "product" and product_id:
            # Similar products (same category, excluding current)
            product = self.db.query(Product).filter(Product.id == product_id).first()
            if product and product.category_id:
                similar = self.db.query(Product).filter(
                    Product.category_id == product.category_id,
                    Product.id != product_id,
                    Product.inventory > 0,
                ).order_by(Product.rating.desc()).limit(limit).all()
                return [
                    {"product_id": p.id, "name": p.name, "slug": p.slug, "price": p.price,
                     "discount_price": p.discount_price, "rating": p.rating, "image": p.images[0] if p.images else None,
                     "reason": "Similar to what you're viewing"}
                    for p in similar
                ]

        elif user_id:
            # Personalized based on browsing history
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

                return [
                    {"product_id": p.id, "name": p.name, "slug": p.slug, "price": p.price,
                     "discount_price": p.discount_price, "rating": p.rating, "image": p.images[0] if p.images else None,
                     "reason": "Based on your interests"}
                    for p in products
                ]

        # Fallback: popular products
        popular = self.db.query(Product).filter(
            Product.inventory > 0
        ).order_by(Product.rating.desc()).limit(limit).all()

        return [
            {"product_id": p.id, "name": p.name, "slug": p.slug, "price": p.price,
             "discount_price": p.discount_price, "rating": p.rating, "image": p.images[0] if p.images else None,
             "reason": "Popular on ForgeStore"}
            for p in popular
        ]
