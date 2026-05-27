"""AI-Powered Smart Search — System 7"""
import json
import logging
import re
from datetime import datetime
from datetime import timedelta
from app.utils import utcnow
from app.utils import utcnow
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, desc

from app.models import (
    Product, Category, Retailer,
    SearchHistory, SearchTrend, SearchEmbedding, SearchClickAnalytics,
    UserPreferenceVector,
)

logger = logging.getLogger("forgestore.search")


class SearchService:
    """Core search engine with smart features."""

    def __init__(self, db: Session):
        self.db = db

    def search(self, query: str, category: Optional[str] = None,
               min_price: Optional[float] = None, max_price: Optional[float] = None,
               sort: str = "relevance", page: int = 1, per_page: int = 20,
               user_id: Optional[str] = None, session_id: Optional[str] = None) -> dict:
        """Execute a smart search with full-text matching and filters."""
        q = self.db.query(Product).filter(Product.inventory > 0)

        # Full-text search across name, brand, description
        if query:
            search_terms = query.strip().split()
            filters = []
            for term in search_terms:
                term_filter = or_(
                    Product.name.ilike(f"%{term}%"),
                    Product.brand.ilike(f"%{term}%"),
                    Product.description.ilike(f"%{term}%"),
                    Product.sub_category.ilike(f"%{term}%"),
                )
                filters.append(term_filter)
            q = q.filter(or_(*filters) if len(filters) > 1 else filters[0])

        # Category filter
        if category:
            q = q.join(Category).filter(Category.slug == category)

        # Price range filter
        if min_price is not None:
            q = q.filter(Product.price >= min_price)
        if max_price is not None:
            q = q.filter(Product.price <= max_price)

        # Sorting
        if sort == "price_asc":
            q = q.order_by(Product.price.asc())
        elif sort == "price_desc":
            q = q.order_by(Product.price.desc())
        elif sort == "rating":
            q = q.order_by(Product.rating.desc())
        elif sort == "newest":
            q = q.order_by(Product.created_at.desc())
        else:  # relevance - use rating + review_count as proxy
            q = q.order_by((Product.rating * 0.7 + Product.review_count * 0.3).desc())

        # Pagination
        total = q.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        products = q.offset((page - 1) * per_page).limit(per_page).all()

        # Log search history
        self._log_search(query, user_id, session_id, total)

        # Check for typo suggestions
        suggestion = None
        if total == 0 and query:
            suggestion = self._suggest_correction(query)

        return {
            "results": [
                {
                    "id": p.id, "slug": p.slug, "name": p.name,
                    "brand": p.brand, "description": p.description[:200] if p.description else "",
                    "price": p.price, "discount_price": p.discount_price,
                    "image": p.images[0] if p.images else None,
                    "rating": p.rating, "review_count": p.review_count,
                    "inventory": p.inventory,
                }
                for p in products
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "suggestion": suggestion,
        }

    def _suggest_correction(self, query: str) -> Optional[str]:
        """Suggest a corrected search query using known product names."""
        # Check against product names for similar matches
        products = self.db.query(Product.name).all()
        product_names = [p[0] for p in products if p[0]]

        query_lower = query.lower()
        for name in product_names:
            name_lower = name.lower()
            # Simple Levenshtein-like check
            if self._levenshtein_ratio(query_lower, name_lower) > 0.6:
                return name

        return None

    @staticmethod
    def _levenshtein_ratio(s1: str, s2: str) -> float:
        """Compute similarity ratio between two strings."""
        if not s1 or not s2:
            return 0.0
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
        return 1 - dp[m][n] / max(m, n)

    def _log_search(self, query: str, user_id: Optional[str], session_id: Optional[str], result_count: int):
        """Log a search query to history."""
        if not query:
            return
        history = SearchHistory(
            user_id=user_id,
            session_id=session_id,
            query=query,
            result_count=result_count,
            search_type="text",
        )
        self.db.add(history)
        self.db.commit()

    def log_click(self, search_id: str, product_id: str, position: int = 0):
        """Log a click on a search result."""
        click = SearchClickAnalytics(
            search_id=search_id,
            product_id=product_id,
            position=position,
        )
        self.db.add(click)
        self.db.commit()

    def get_suggestions(self, query: str, limit: int = 5) -> list[str]:
        """Get autocomplete suggestions for a partial query."""
        if not query or len(query) < 2:
            return []

        # Search product names
        products = self.db.query(Product.name).filter(
            Product.name.ilike(f"{query}%"),
            Product.inventory > 0,
        ).distinct().limit(limit).all()

        suggestions = [p[0] for p in products]

        # Fill remaining slots with trending searches
        if len(suggestions) < limit:
            trending = self.db.query(SearchTrend.normalized_query).filter(
                SearchTrend.normalized_query.ilike(f"%{query}%"),
            ).order_by(SearchTrend.count.desc()).limit(limit - len(suggestions)).all()

            for t in trending:
                if t[0] not in suggestions:
                    suggestions.append(t[0])

        return suggestions[:limit]


class SemanticSearchService:
    """Semantic search preparation (pgvector-ready)."""

    def __init__(self, db: Session):
        self.db = db

    def get_products_by_embedding(self, query_embedding: list[float], limit: int = 20) -> list[Product]:
        """Find products by embedding similarity.
        NOTE: This requires pgvector extension installed in PostgreSQL.
        Falls back to text search if pgvector is not available."""
        try:
            # Attempt vector similarity search
            from sqlalchemy import text
            embedding_json = json.dumps(query_embedding)
            sql = text(f"""
                SELECT p.*, 1 - (se.embedding::vector <=> '{embedding_json}'::vector) AS similarity
                FROM product p
                JOIN search_embedding se ON se.product_id = p.id
                WHERE p.inventory > 0
                ORDER BY similarity DESC
                LIMIT :limit
            """)
            result = self.db.execute(sql, {"limit": limit})
            return [row[0] for row in result] if result else []
        except Exception as e:
            logger.warning(f"pgvector search failed, falling back: {e}")
            return []


class RankingService:
    """Personalized search ranking with user preferences."""

    def __init__(self, db: Session):
        self.db = db

    def rank_results(self, products: list, user_id: Optional[str] = None) -> list:
        """Rank search results based on user preferences and signals."""
        if not user_id or not products:
            return products

        # Get user preference vector
        pref = self.db.query(UserPreferenceVector).filter(
            UserPreferenceVector.user_id == user_id
        ).first()

        if not pref:
            return products

        # Calculate personalization scores
        category_affinities = pref.category_affinities or {}

        ranked = []
        for product in products:
            score = 1.0

            # Boost by category affinity
            if product.category_id in category_affinities:
                score += category_affinities[product.category_id] * 0.3

            # Boost by brand affinity
            if pref.brand_affinities and product.brand in pref.brand_affinities:
                score += pref.brand_affinities[product.brand] * 0.2

            # Boost by rating
            score += (product.rating or 0) * 0.1

            ranked.append((score, product))

        ranked.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in ranked]


class TrendingService:
    """Trending searches and search analytics."""

    def __init__(self, db: Session):
        self.db = db

    def get_trending_searches(self, limit: int = 10) -> list[dict]:
        """Get currently trending search queries."""
        today = utcnow().date()
        week_ago = today - timedelta(days=7)

        trends = self.db.query(
            SearchTrend.normalized_query,
            func.sum(SearchTrend.count).label("total"),
        ).filter(
            SearchTrend.period_start >= week_ago,
        ).group_by(SearchTrend.normalized_query).order_by(
            desc("total")
        ).limit(limit).all()

        return [
            {"query": t[0], "count": t[1]}
            for t in trends
        ]

    def record_search_trend(self, query: str):
        """Record a search query for trending analytics."""
        if not query or len(query) < 2:
            return

        normalized = query.lower().strip()
        today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        trend = self.db.query(SearchTrend).filter(
            SearchTrend.normalized_query == normalized,
            SearchTrend.period == "daily",
            SearchTrend.period_start == today_start,
        ).first()

        if trend:
            trend.count += 1
        else:
            trend = SearchTrend(
                query=query,
                normalized_query=normalized,
                count=1,
                unique_users=1,
                period="daily",
                period_start=today_start,
                period_end=today_start + timedelta(days=1),
            )
            self.db.add(trend)

        self.db.commit()
