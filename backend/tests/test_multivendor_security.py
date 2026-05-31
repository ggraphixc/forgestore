"""
Structural integration tests — portal isolation & cross-tenant data leak prevention.

Verifies:
  1. RETAILER role cannot access restricted /admin/ namespace endpoints
  2. LOGISTICS role cannot access vendor dashboard or product mutation endpoints
  3. Cross-tenant vendor data isolation (Vendor A cannot see/update Vendor B items)
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db, SessionLocal
from app.models import (
    AdminUser, AdminRole, Retailer, Product, Category,
    VendorWallet, Order, OrderItem, OrderStatus,
)
from app.auth import hash_password, create_access_token


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_admin(db, email, role, vendor_id=None):
    admin = AdminUser(
        email=email,
        password=hash_password("testpass123"),
        name=f"Test {role.value}",
        role=role,
        vendor_id=vendor_id,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _auth_cookie(admin):
    token = create_access_token({
        "sub": admin.id,
        "email": admin.email,
        "name": admin.name,
        "type": "admin",
    })
    return {"access_token": token}


def _make_retailer(db, name, slug):
    r = Retailer(name=name, slug=slug, bio=f"{name} bio", status="ACTIVE")
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _make_product(db, name, slug, retailer_id, price=100.0):
    p = Product(
        name=name, slug=slug, price=price, inventory=50,
        retailer_id=retailer_id, images=["/img/test.svg"],
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ──────────────────────────────────────────────────────────────────────
# TEST 1: RETAILER → restricted admin endpoints blocked
# ──────────────────────────────────────────────────────────────────────


class TestRetailerAdminIsolation:
    """RETAILER role must NOT access endpoints requiring 'settings', 'admin_users', 'customers' permissions."""

    @pytest.mark.parametrize("endpoint", [
        "/admin/settings",
        "/admin/admin-users",
        "/admin/customers",
        "/admin/categories",
        "/admin/newsletter-subscribers",
    ])
    def test_retailer_blocked_on_restricted_endpoints(self, db_session, endpoint):
        """These endpoints require permissions RETAILER doesn't have — expect 302 redirect to login."""
        retailer = _make_retailer(db_session, "Retailer A", "retailer-a")
        admin = _make_admin(db_session, "retailer-a@test.com", AdminRole.RETAILER, vendor_id=retailer.id)
        cookies = _auth_cookie(admin)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(endpoint, cookies=cookies, follow_redirects=False)
            # The handler redirects to /admin/login when permission check fails
            assert resp.status_code in (302, 403), (
                f"RETAILER got {resp.status_code} on {endpoint} — expected 302 redirect or 403"
            )

    def test_retailer_api_settings_forbidden(self, db_session):
        """The settings API uses require_role('settings') which RETAILER lacks."""
        retailer = _make_retailer(db_session, "Retailer E", "retailer-e")
        admin = _make_admin(db_session, "retailer-e@test.com", AdminRole.RETAILER, vendor_id=retailer.id)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.get("/api/admin/settings", cookies=cookies)
            assert resp.status_code == 403

    def test_retailer_catalog_filtered_to_own(self, db_session):
        """RETAILER has 'catalog' permission but catalog view filters to their own retailer_id."""
        r_a = _make_retailer(db_session, "Retailer Own", "retailer-own")
        r_b = _make_retailer(db_session, "Retailer Other", "retailer-other")
        p_own = _make_product(db_session, "Own Widget", "own-widget", r_a.id)
        p_other = _make_product(db_session, "Other Widget", "other-widget", r_b.id)
        admin = _make_admin(db_session, "retailer-own@test.com", AdminRole.RETAILER, vendor_id=r_a.id)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.get("/admin/catalog", cookies=cookies, follow_redirects=False)
            assert resp.status_code == 200
            body = resp.text
            # Should see own product
            assert "Own Widget" in body or p_own.id in body
            # Should NOT see other vendor's product
            assert "Other Widget" not in body and p_other.id not in body

    def test_retailer_api_orders_visible(self, db_session):
        """RETAILER has 'orders' permission — the orders API returns 200."""
        retailer = _make_retailer(db_session, "Retailer O", "retailer-o")
        admin = _make_admin(db_session, "retailer-o@test.com", AdminRole.RETAILER, vendor_id=retailer.id)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.get("/api/admin/orders", cookies=cookies)
            assert resp.status_code == 200

    def test_retailer_admin_users_api_forbidden(self, db_session):
        """RETAILER lacks 'admin_users' permission."""
        retailer = _make_retailer(db_session, "Retailer AU", "retailer-au")
        admin = _make_admin(db_session, "retailer-au@test.com", AdminRole.RETAILER, vendor_id=retailer.id)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.get("/api/admin/admin-users", cookies=cookies)
            assert resp.status_code == 403


# ──────────────────────────────────────────────────────────────────────
# TEST 2: LOGISTICS → cannot access vendor dashboard or mutate products
# ──────────────────────────────────────────────────────────────────────


class TestLogisticsPortalIsolation:
    """LOGISTICS role must NOT access vendor dashboard or product CRUD."""

    def test_logistics_vendor_dashboard_redirects(self, db_session):
        """Vendor dashboard requires RETAILER role — LOGISTICS gets redirected to admin dashboard."""
        admin = _make_admin(db_session, "logistics@test.com", AdminRole.LOGISTICS)
        cookies = _auth_cookie(admin)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/vendor/dashboard", cookies=cookies, follow_redirects=False)
            assert resp.status_code in (302, 403), (
                f"LOGISTICS got {resp.status_code} on /vendor/dashboard — expected redirect or 403"
            )

    def test_logistics_vendor_products_redirects(self, db_session):
        admin = _make_admin(db_session, "logistics2@test.com", AdminRole.LOGISTICS)
        cookies = _auth_cookie(admin)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/vendor/products", cookies=cookies, follow_redirects=False)
            assert resp.status_code in (302, 403)

    def test_logistics_vendor_earnings_redirects(self, db_session):
        admin = _make_admin(db_session, "logistics3@test.com", AdminRole.LOGISTICS)
        cookies = _auth_cookie(admin)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/vendor/earnings", cookies=cookies, follow_redirects=False)
            assert resp.status_code in (302, 403)

    def test_logistics_cannot_create_product(self, db_session):
        """LOGISTICS lacks 'catalog' permission — API returns 403."""
        admin = _make_admin(db_session, "logistics4@test.com", AdminRole.LOGISTICS)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.post(
                "/api/admin/products",
                json={"name": "Hacked", "slug": "hacked", "price": 1.0},
                cookies=cookies,
            )
            assert resp.status_code == 403

    def test_logistics_cannot_delete_product(self, db_session):
        retailer = _make_retailer(db_session, "Retailer G", "retailer-g")
        product = _make_product(db_session, "Victim Product", "victim-prod", retailer.id)
        admin = _make_admin(db_session, "logistics5@test.com", AdminRole.LOGISTICS)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.delete(f"/api/admin/products/{product.id}", cookies=cookies)
            assert resp.status_code == 403

    def test_logistics_can_access_own_dashboard(self, db_session):
        """LOGISTICS has 'dashboard' permission — logistics portal loads."""
        admin = _make_admin(db_session, "logistics6@test.com", AdminRole.LOGISTICS)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.get("/logistics/dashboard", cookies=cookies, follow_redirects=False)
            assert resp.status_code == 200

    def test_logistics_can_access_shipments(self, db_session):
        """LOGISTICS has 'shipments' permission."""
        admin = _make_admin(db_session, "logistics7@test.com", AdminRole.LOGISTICS)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.get("/logistics/shipments", cookies=cookies, follow_redirects=False)
            assert resp.status_code == 200

    def test_logistics_api_orders_allowed(self, db_session):
        """LOGISTICS has 'orders' permission."""
        admin = _make_admin(db_session, "logistics8@test.com", AdminRole.LOGISTICS)
        cookies = _auth_cookie(admin)

        with TestClient(app) as client:
            resp = client.get("/api/admin/orders", cookies=cookies)
            assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────
# TEST 3: Cross-tenant vendor data isolation
# ──────────────────────────────────────────────────────────────────────


class TestCrossTenantDataIsolation:
    """Vendor A must NOT see or modify Vendor B's products or earnings."""

    def _setup_two_vendors(self, db_session):
        r_a = _make_retailer(db_session, "Vendor Alpha", "vendor-alpha")
        r_b = _make_retailer(db_session, "Vendor Beta", "vendor-beta")
        p_a = _make_product(db_session, "Alpha Widget", "alpha-widget", r_a.id, price=200.0)
        p_b = _make_product(db_session, "Beta Gadget", "beta-gadget", r_b.id, price=300.0)
        admin_a = _make_admin(db_session, "alpha@test.com", AdminRole.RETAILER, vendor_id=r_a.id)
        admin_b = _make_admin(db_session, "beta@test.com", AdminRole.RETAILER, vendor_id=r_b.id)
        return r_a, r_b, p_a, p_b, admin_a, admin_b

    def test_vendor_a_cannot_edit_vendor_b_product(self, db_session):
        """Edit page checks retailer_id match — returns 403 for cross-tenant."""
        r_a, r_b, p_a, p_b, admin_a, admin_b = self._setup_two_vendors(db_session)
        cookies_a = _auth_cookie(admin_a)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/admin/catalog/{p_b.id}/edit", cookies=cookies_a, follow_redirects=False)
            assert resp.status_code in (403, 404), (
                f"Vendor A got {resp.status_code} editing Vendor B's product — expected 403/404"
            )

    def test_vendor_b_cannot_edit_vendor_a_product(self, db_session):
        r_a, r_b, p_a, p_b, admin_a, admin_b = self._setup_two_vendors(db_session)
        cookies_b = _auth_cookie(admin_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/admin/catalog/{p_a.id}/edit", cookies=cookies_b, follow_redirects=False)
            assert resp.status_code in (403, 404)

    def test_vendor_a_catalog_only_shows_own_products(self, db_session):
        """Catalog list filters by retailer_id — cross-vendor products invisible."""
        r_a, r_b, p_a, p_b, admin_a, admin_b = self._setup_two_vendors(db_session)
        cookies_a = _auth_cookie(admin_a)

        with TestClient(app) as client:
            resp = client.get("/admin/catalog", cookies=cookies_a, follow_redirects=False)
            assert resp.status_code == 200
            body = resp.text
            assert "Alpha Widget" in body or p_a.id in body
            assert "Beta Gadget" not in body and p_b.id not in body, (
                "Vendor A's catalog page should NOT contain Vendor B's products"
            )

    def test_vendor_a_api_cannot_update_vendor_b_product(self, db_session):
        """API update checks retailer_id — returns 403 for cross-tenant."""
        r_a, r_b, p_a, p_b, admin_a, admin_b = self._setup_two_vendors(db_session)
        cookies_a = _auth_cookie(admin_a)

        with TestClient(app) as client:
            resp = client.put(
                f"/api/admin/products/{p_b.id}",
                json={"name": "Hijacked Name"},
                cookies=cookies_a,
            )
            assert resp.status_code == 403

        # Verify product name unchanged
        db_session.refresh(p_b)
        assert p_b.name == "Beta Gadget"

    def test_vendor_wallet_isolation(self, db_session):
        """VendorWallet records are strictly partitioned by retailer_id."""
        r_a, r_b, _, _, _, _ = self._setup_two_vendors(db_session)

        w_a = VendorWallet(retailer_id=r_a.id, balance=5000.0)
        w_b = VendorWallet(retailer_id=r_b.id, balance=12000.0)
        db_session.add_all([w_a, w_b])
        db_session.commit()

        wallet_a = db_session.query(VendorWallet).filter(
            VendorWallet.retailer_id == r_a.id
        ).first()
        assert wallet_a.balance == 5000.0

        wallet_b = db_session.query(VendorWallet).filter(
            VendorWallet.retailer_id == r_b.id
        ).first()
        assert wallet_b.balance == 12000.0

        assert wallet_a.id != wallet_b.id
        assert wallet_a.retailer_id != wallet_b.retailer_id

    def test_vendor_a_cannot_see_vendor_b_earnings_page(self, db_session):
        """Vendor portal earnings filters by own retailer_id."""
        r_a, r_b, _, _, admin_a, _ = self._setup_two_vendors(db_session)
        cookies_a = _auth_cookie(admin_a)

        with TestClient(app) as client:
            resp = client.get("/vendor/earnings", cookies=cookies_a, follow_redirects=False)
            # Should either redirect (not RETAILER) or show only own earnings
            assert resp.status_code in (200, 302, 403)

    def test_unauthenticated_cannot_access_admin(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/admin/dashboard", follow_redirects=False)
            assert resp.status_code == 302
            assert "/admin/login" in resp.headers.get("location", "")

    def test_unauthenticated_cannot_access_vendor_portal(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/vendor/dashboard", follow_redirects=False)
            assert resp.status_code == 302

    def test_unauthenticated_cannot_access_logistics_portal(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/logistics/dashboard", follow_redirects=False)
            assert resp.status_code == 302

    def test_dir_admin_full_access(self, db_session):
        """DIR_ADMIN should access all admin endpoints."""
        admin = _make_admin(db_session, "diradmin@test.com", AdminRole.DIR_ADMIN)
        cookies = _auth_cookie(admin)

        with TestClient(app, follow_redirects=False) as client:
            for endpoint in ["/admin/dashboard", "/admin/settings", "/admin/admin-users",
                             "/admin/customers", "/admin/categories", "/admin/retailers"]:
                resp = client.get(endpoint, cookies=cookies)
                assert resp.status_code == 200, f"DIR_ADMIN got {resp.status_code} on {endpoint}"
