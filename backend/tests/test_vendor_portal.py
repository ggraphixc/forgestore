"""
Tests for vendor portal rendered pages:
- GET /vendor/dashboard
- GET /vendor/products
- GET /vendor/add-product (via /vendor/products/new)
- GET /vendor/orders
- GET /vendor/earnings
- GET /vendor/profile (via /vendor/me)
- GET /vendor/returns
- GET /vendor/inventory
- GET /vendor/logout
- Unauthenticated access redirects
"""

import pytest
import uuid

from app.auth import hash_password
from app.models import AdminUser, AdminRole, Retailer, Category, Product


def _unique_id(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _hash_password(password: str) -> str:
    try:
        from passlib.hash import bcrypt
        return bcrypt.hash(password)
    except Exception:
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()


class TestVendorPortal:
    """Vendor portal rendered page tests."""

    def _seed_data(self, db):
        """Create a retailer, admin user, category, and product."""
        retailer = Retailer(
            id=_unique_id("ret-vp-"),
            name="Test Vendor",
            slug=f"test-vendor-{uuid.uuid4().hex[:6]}",
            bio="A test vendor store",
            rating=4.0,
            review_count=5,
        )
        db.add(retailer)
        db.flush()

        admin = AdminUser(
            id=_unique_id("adm-vp-"),
            email="vendor@test.com",
            password=_hash_password("test123"),
            name="Vendor Admin",
            role=AdminRole.RETAILER,
            vendor_id=retailer.id,
        )
        db.add(admin)
        db.flush()

        cat = Category(
            id=_unique_id("cat-vp-"),
            name="Test Category",
            slug=f"test-cat-{uuid.uuid4().hex[:6]}",
            description="A test category",
        )
        db.add(cat)
        db.flush()

        product = Product(
            id=_unique_id("prod-vp-"),
            slug=f"test-product-{uuid.uuid4().hex[:6]}",
            name="Test Product",
            brand="TestBrand",
            description="A test product",
            price=99.99,
            discount_price=79.99,
            images=["/static/img/placeholder.svg"],
            category_id=cat.id,
            retailer_id=retailer.id,
            inventory=50,
            rating=4.0,
            review_count=5,
            status="APPROVED",
        )
        db.add(product)
        db.commit()
        db.refresh(retailer)
        db.refresh(admin)
        db.refresh(cat)
        db.refresh(product)
        return retailer, admin, cat, product

    def _login_vendor(self, client):
        """Login as vendor admin and return response."""
        return client.post("/api/auth/login", json={
            "email": "vendor@test.com",
            "password": "test123",
        })

    def test_vendor_dashboard_retailer(self, client, db):
        """Logged-in RETAILER user can GET /vendor/dashboard and see 200."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/dashboard")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    def test_vendor_products_retailer(self, client, db):
        """GET /vendor/products returns 200 for authenticated vendor."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/products")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    def test_vendor_add_product_retailer(self, client, db):
        """GET /vendor/products/new (add-product page) returns 200."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/products/new")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    def test_vendor_orders_retailer(self, client, db):
        """GET /vendor/orders returns 200."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/orders")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    def test_vendor_earnings_retailer(self, client, db):
        """GET /vendor/earnings returns 200."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/earnings")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    def test_vendor_profile_retailer(self, client, db):
        """GET /vendor/me (profile page) returns 200."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/me")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    def test_vendor_returns_retailer(self, client, db):
        """GET /vendor/returns returns 200."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/returns")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    def test_vendor_inventory_retailer(self, client, db):
        """GET /vendor/inventory returns 200."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/inventory")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    def test_vendor_logout_redirects(self, client, db):
        """GET /vendor/logout redirects to /admin/login."""
        retailer, admin, cat, product = self._seed_data(db)
        login_resp = self._login_vendor(client)
        assert login_resp.status_code == 200

        resp = client.get("/vendor/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["location"]

    def test_vendor_dashboard_unauthenticated_redirects(self, client, db):
        """Unauthenticated GET /vendor/dashboard redirects to /admin/login."""
        retailer, admin, cat, product = self._seed_data(db)

        resp = client.get("/vendor/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["location"]
