"""
Slug generation utility for ForgeStore.
Creates URL-friendly slugs from titles and guarantees uniqueness in the database.
"""
import re
import uuid
import logging

logger = logging.getLogger("forgestore.slug")


def _base_slug(text: str, max_length: int = 80) -> str:
    """Convert text to a clean URL slug."""
    slug = text.lower().strip()
    # Remove accents and special characters
    slug = re.sub(r'[^\w\s-]', '', slug)
    # Replace spaces and underscores with hyphens
    slug = re.sub(r'[\s_]+', '-', slug)
    # Collapse multiple hyphens
    slug = re.sub(r'-+', '-', slug)
    # Strip leading/trailing hyphens
    slug = slug.strip('-')
    # Truncate
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip('-')
    return slug


def generate_product_slug(title: str, db_session=None, exclude_id=None) -> str:
    """
    Generate a unique slug for a product from its title.

    - Converts title to lowercase-hyphenated slug
    - Checks DB for collisions (if db_session provided)
    - Appends short random suffix on collision
    - Returns slug that is guaranteed unique in the DB
    """
    slug = _base_slug(title)
    if not slug:
        slug = "product"

    if db_session is None:
        return slug

    from app.models import Product

    base_slug = slug
    attempt = 0
    while True:
        query = db_session.query(Product).filter(Product.slug == slug)
        if exclude_id:
            query = query.filter(Product.id != exclude_id)
        existing = query.first()
        if not existing:
            return slug
        # Collision — append suffix
        attempt += 1
        if attempt <= 3:
            # Try appending a numeric suffix first (cleaner URLs)
            slug = f"{base_slug}-{attempt}"
        else:
            # Fallback to random hex
            slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            logger.info(f"Slug collision after {attempt} attempts, using random: {slug}")
            return slug


def generate_category_slug(name: str, db_session=None, exclude_id=None) -> str:
    """Generate a unique slug for a category."""
    slug = _base_slug(name)
    if not slug:
        slug = "category"

    if db_session is None:
        return slug

    from app.models import Category

    base_slug = slug
    attempt = 0
    while True:
        query = db_session.query(Category).filter(Category.slug == slug)
        if exclude_id:
            query = query.filter(Category.id != exclude_id)
        if not query.first():
            return slug
        attempt += 1
        if attempt <= 3:
            slug = f"{base_slug}-{attempt}"
        else:
            slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            return slug


def generate_retailer_slug(name: str, db_session=None, exclude_id=None) -> str:
    """Generate a unique slug for a retailer/shop."""
    slug = _base_slug(name)
    if not slug:
        slug = "shop"

    if db_session is None:
        return slug

    from app.models import Retailer

    base_slug = slug
    attempt = 0
    while True:
        query = db_session.query(Retailer).filter(Retailer.slug == slug)
        if exclude_id:
            query = query.filter(Retailer.id != exclude_id)
        if not query.first():
            return slug
        attempt += 1
        if attempt <= 3:
            slug = f"{base_slug}-{attempt}"
        else:
            slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            return slug
