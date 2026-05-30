"""
Tests for OrderEarnings payout endpoints.

Covers:
- POST /api/admin/earnings/request-payout — Retailer self-service payout
- POST /api/admin/earnings/batch-mark-paid — Admin batch payout
"""

import pytest
import uuid

from app.auth import create_access_token, hash_password
from app.models import OrderEarning, AdminUser, AdminRole, Retailer, Product, Order, OrderItem, OrderStatus
from app.utils import utcnow


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def retailer_admin(db, sample_retailer):
    """Create an AdminUser with RETAILER role linked to sample_retailer."""
    admin = AdminUser(
        id=f"ret-admin-earn-{uuid.uuid4().hex[:8]}",
        email="retailer-earnings@test.com",
        password=hash_password("testpass123"),
        name="Retailer Earnings Admin",
        role=AdminRole.RETAILER,
        vendor_id=sample_retailer.id,
    )
    db.add(admin)
    db.commit()
    return admin


@pytest.fixture
def retailer_headers(retailer_admin):
    """Generate auth headers for the retailer admin user."""
    token = create_access_token({
        "sub": retailer_admin.id,
        "email": retailer_admin.email,
        "role": "RETAILER",
        "type": "admin",
        "vendor_id": retailer_admin.vendor_id,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_order(db, sample_user, sample_retailer, sample_products):
    """Create a sample PAID order with one item."""
    order = Order(
        id=f"test-order-earn-{uuid.uuid4().hex[:8]}",
        order_number=f"EARN-{uuid.uuid4().hex[:8].upper()}",
        status=OrderStatus.PAID,
        total_amount=99.99,
        shipping_address={"street": "123 Test St", "city": "Testville"},
        customer_id=sample_user.id,
    )
    db.add(order)
    db.flush()

    item = OrderItem(
        product_id=sample_products[0].id,
        order_id=order.id,
        quantity=1,
        price=99.99,
    )
    db.add(item)
    db.commit()
    db.refresh(order)
    return order


@pytest.fixture
def sample_earnings(db, sample_retailer, sample_order, sample_products):
    """Create sample OrderEarning records (one SCHEDULED, one PENDING) for the retailer."""
    earnings = [
        OrderEarning(
            order_id=sample_order.id,
            retailer_id=sample_retailer.id,
            product_id=sample_products[0].id,
            amount=99.99,
            commission=9.99,
            net_amount=90.00,
            status="SCHEDULED",
        ),
        OrderEarning(
            order_id=sample_order.id,
            retailer_id=sample_retailer.id,
            product_id=sample_products[1].id,
            amount=149.99,
            commission=14.99,
            net_amount=135.00,
            status="PENDING",
        ),
    ]
    for e in earnings:
        db.add(e)
    db.commit()
    return earnings


@pytest.fixture
def dir_admin_headers(admin_user):
    """Generate auth headers for the DIR_ADMIN admin user."""
    token = create_access_token({
        "sub": admin_user.id,
        "email": admin_user.email,
        "role": "DIR_ADMIN",
        "type": "admin",
    })
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# TESTS: POST /api/admin/earnings/request-payout
# ==============================================================================


class TestRequestPayout:
    """Retailer self-service payout request."""

    ENDPOINT = "/api/admin/earnings/request-payout"

    def test_request_payout_success(self, client, db, sample_retailer, sample_earnings, retailer_headers):
        """Successful payout request marks all SCHEDULED/PENDING earnings as PAID."""
        # Act
        resp = client.post(self.ENDPOINT, headers=retailer_headers)

        # Assert
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["marked"] == 2
        assert data["total_net"] == 90.00 + 135.00  # 225.00

        # Assert DB records updated
        for e in sample_earnings:
            db.refresh(e)
            assert e.status == "PAID"
            assert e.paid_at is not None

    def test_request_payout_no_pending_earnings(self, client, db, sample_retailer, retailer_headers):
        """Requesting payout with no SCHEDULED/PENDING earnings returns 0 marked."""
        # Act — no earnings exist
        resp = client.post(self.ENDPOINT, headers=retailer_headers)

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["marked"] == 0
        assert "message" in data

    def test_request_payout_non_retailer_returns_403(self, client, admin_user, dir_admin_headers):
        """DIR_ADMIN role gets 403 when calling the RETAILER-only endpoint."""
        # Act
        resp = client.post(self.ENDPOINT, headers=dir_admin_headers)

        # Assert
        assert resp.status_code == 403
        assert "Only RETAILERs" in resp.text

    def test_request_payout_no_vendor_id_returns_400(self, client, db):
        """RETAILER admin without vendor_id gets 400."""
        # Create a RETAILER admin with no vendor_id
        admin = AdminUser(
            id=f"ret-no-vendor-{uuid.uuid4().hex[:8]}",
            email="ret-no-vendor@test.com",
            password=hash_password("testpass123"),
            name="No Vendor Retailer",
            role=AdminRole.RETAILER,
            vendor_id=None,
        )
        db.add(admin)
        db.commit()

        token = create_access_token({
            "sub": admin.id,
            "email": admin.email,
            "role": "RETAILER",
            "type": "admin",
        })
        headers = {"Authorization": f"Bearer {token}"}

        # Act
        resp = client.post(self.ENDPOINT, headers=headers)

        # Assert
        assert resp.status_code == 400
        assert "vendor_id" in resp.text.lower()

    def test_request_payout_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(self.ENDPOINT)
        assert resp.status_code == 401

    def test_request_payout_idempotent(self, client, db, sample_retailer, sample_earnings, retailer_headers):
        """Calling request-payout twice is idempotent — second call marks 0."""
        # First call
        resp1 = client.post(self.ENDPOINT, headers=retailer_headers)
        assert resp1.status_code == 200
        assert resp1.json()["marked"] == 2

        # Second call — all already PAID
        resp2 = client.post(self.ENDPOINT, headers=retailer_headers)
        assert resp2.status_code == 200
        assert resp2.json()["marked"] == 0


# ==============================================================================
# TESTS: POST /api/admin/earnings/batch-mark-paid
# ==============================================================================


class TestBatchMarkPaid:
    """Admin batch payout mark-as-paid."""

    ENDPOINT = "/api/admin/earnings/batch-mark-paid"

    def test_batch_mark_specific_ids(self, client, db, sample_retailer, sample_earnings, dir_admin_headers):
        """Batch-marking specific earning IDs works."""
        earning_ids = [e.id for e in sample_earnings[:1]]  # Mark only first one

        resp = client.post(
            self.ENDPOINT,
            json={"earning_ids": earning_ids},
            headers=dir_admin_headers,
        )

        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["marked"] == 1

        # Check only the selected one is PAID
        db.refresh(sample_earnings[0])
        assert sample_earnings[0].status == "PAID"
        db.refresh(sample_earnings[1])
        assert sample_earnings[1].status != "PAID"

    def test_batch_mark_all_pending(self, client, db, sample_retailer, sample_earnings, dir_admin_headers):
        """Batch-marking with filter_all_pending=true marks all pending/scheduled."""
        resp = client.post(
            self.ENDPOINT,
            json={"filter_all_pending": True},
            headers=dir_admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["marked"] == 2

        for e in sample_earnings:
            db.refresh(e)
            assert e.status == "PAID"

    def test_batch_mark_no_ids_or_filter_returns_400(self, client, dir_admin_headers):
        """Calling batch-mark without earning_ids or filter_all_pending returns 400."""
        resp = client.post(
            self.ENDPOINT,
            json={},
            headers=dir_admin_headers,
        )

        assert resp.status_code == 400

    def test_batch_mark_non_admin_returns_403(self, client, retailer_headers):
        """RETAILER role gets 403 on the admin-only endpoint."""
        resp = client.post(
            self.ENDPOINT,
            json={"filter_all_pending": True},
            headers=retailer_headers,
        )
        assert resp.status_code == 403

    def test_batch_mark_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(self.ENDPOINT, json={"filter_all_pending": True})
        assert resp.status_code == 401
