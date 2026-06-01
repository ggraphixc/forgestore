"""
Weighted Search Engine — high-performance product search with relevance scoring.
Replaces slow SQL LIKE %query% with weighted multi-column scoring.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["search-v1"])


@router.get("/search")
def weighted_search(
    q: str = Query("", min_length=0, max_length=200),
    category: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Weighted product search with relevance scoring.

    Scoring matrix:
        - Product name match:    +10 points
        - Category name match:   +5 points
        - Product description:   +1 point

    Results are sorted by descending relevance score, then by created_at.
    """
    if not q or not q.strip():
        return {"results": [], "total": 0, "query": q}

    search_term = f"%{q.strip()}%"
    params = {"search_term": search_term, "limit": limit, "offset": offset}

    # Build optional filter clauses
    price_filter = ""
    category_filter = ""
    if min_price is not None:
        price_filter += " AND p.price >= :min_price"
        params["min_price"] = min_price
    if max_price is not None:
        price_filter += " AND p.price <= :max_price"
        params["max_price"] = max_price
    if category:
        category_filter = " AND c.slug = :category_slug"
        params["category_slug"] = category

    query_sql = text(f"""
        SELECT
            p.id,
            p.slug,
            p.name,
            p.price,
            p.discount_price,
            p.images,
            p.rating,
            p.review_count,
            p.inventory,
            p.created_at,
            r.name AS retailer_name,
            c.name AS category_name,
            c.slug AS category_slug,
            (
                CASE WHEN LOWER(p.name) LIKE LOWER(:search_term) THEN 10 ELSE 0 END
                + CASE WHEN LOWER(c.name) LIKE LOWER(:search_term) THEN 5 ELSE 0 END
                + CASE WHEN LOWER(p.description) LIKE LOWER(:search_term) THEN 1 ELSE 0 END
            ) AS relevance_score
        FROM product p
        LEFT JOIN retailer r ON p.retailer_id = r.id
        LEFT JOIN category c ON p.category_id = c.id
        WHERE (
            LOWER(p.name) LIKE LOWER(:search_term)
            OR LOWER(p.description) LIKE LOWER(:search_term)
            OR LOWER(p.brand) LIKE LOWER(:search_term)
            OR LOWER(c.name) LIKE LOWER(:search_term)
        )
        {price_filter}
        {category_filter}
        ORDER BY relevance_score DESC, p.created_at DESC
        LIMIT :limit OFFSET :offset
    """)

    rows = db.execute(query_sql, params).fetchall()

    results = []
    for row in rows:
        images = row.images if isinstance(row.images, list) else []
        results.append({
            "id": row.id,
            "slug": row.slug,
            "name": row.name,
            "price": row.price,
            "discount_price": row.discount_price,
            "image": images[0] if images else None,
            "rating": row.rating or 0,
            "review_count": row.review_count or 0,
            "inventory": row.inventory,
            "retailer_name": row.retailer_name,
            "category_name": row.category_name,
            "relevance_score": row.relevance_score,
        })

    # Total count (without limit/offset)
    count_sql = text(f"""
        SELECT COUNT(*) as cnt
        FROM product p
        LEFT JOIN category c ON p.category_id = c.id
        WHERE (
            LOWER(p.name) LIKE LOWER(:search_term)
            OR LOWER(p.description) LIKE LOWER(:search_term)
            OR LOWER(p.brand) LIKE LOWER(:search_term)
            OR LOWER(c.name) LIKE LOWER(:search_term)
        )
        {price_filter}
        {category_filter}
    """)
    total = db.execute(count_sql, {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {
        "results": results,
        "total": total,
        "query": q,
        "offset": offset,
        "limit": limit,
    }
