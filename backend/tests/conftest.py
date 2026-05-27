"""
Pytest configuration for ForgeStore backend tests.

Uses a temporary SQLite database isolated from the real database.
"""

import pytest
import os
import sys
import tempfile
from pathlib import Path

# Ensure the app module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

# Override DATABASE_URL before any app imports
# Use a temporary file with a unique name to avoid locking conflicts
import tempfile
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
_test_db = Path(_tmp_db.name)
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db.as_posix()}"

from app.database import Base, init_db, SessionLocal, get_db
from app.main import app
from app.models import (
    Product, Category, Retailer, User, Order, OrderItem,
    Review, AdminUser, CartItem, Settings, AdminRole,
    NewsletterSubscriber, BroadcastCampaign, BroadcastEvent, BroadcastTemplate,
    AdminAuditLog, AdminNotification, PasswordResetToken, WishlistItem,
)


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables before each test, drop after."""
    Base.metadata.create_all(bind=SessionLocal().bind)
    yield
    Base.metadata.drop_all(bind=SessionLocal().bind)


@pytest.fixture
def db():
    """Provide a clean database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """FastAPI test client with overridden DB dependency."""
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_category(db):
    """Create a sample category for tests."""
    cat = Category(
        id="test-cat-001",
        name="Electronics",
        slug="electronics",
        description="Electronic gadgets and devices",
    )
    db.add(cat)
    db.commit()
    return cat


@pytest.fixture
def sample_retailer(db):
    """Create a sample retailer for tests."""
    r = Retailer(
        id="test-ret-001",
        name="Test Retailer",
        slug="test-retailer",
        bio="A test retailer",
        rating=4.5,
        review_count=10,
    )
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def sample_products(db, sample_category, sample_retailer):
    """Create sample products for tests."""
    products = [
        Product(
            id="test-prod-001",
            slug="test-product-1",
            name="Test Product 1",
            brand="TestBrand",
            description="A test product for unit tests",
            price=99.99,
            discount_price=79.99,
            images=["/static/img/placeholder.svg"],
            category_id=sample_category.id,
            retailer_id=sample_retailer.id,
            inventory=50,
            rating=4.0,
            review_count=5,
            is_new_arrival=True,
        ),
        Product(
            id="test-prod-002",
            slug="test-product-2",
            name="Test Product 2",
            brand="TestBrand",
            description="Another test product",
            price=149.99,
            images=["/static/img/placeholder.svg"],
            category_id=sample_category.id,
            retailer_id=sample_retailer.id,
            inventory=30,
            rating=3.5,
            review_count=3,
        ),
    ]
    for p in products:
        db.add(p)
    db.commit()
    return products


@pytest.fixture
def sample_user(db):
    """Create a sample customer user."""
    from app.auth import hash_password
    user = User(
        id="test-user-001",
        email="testuser@example.com",
        name="Test User",
        password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def admin_user(db):
    """Create a sample admin user with DIR_ADMIN role."""
    from app.auth import hash_password
    admin = AdminUser(
        id="test-admin-001",
        email="admin@forgestore.com",
        password=hash_password("admin123"),
        name="Test Admin",
        role=AdminRole.DIR_ADMIN,
    )
    db.add(admin)
    db.commit()
    return admin
