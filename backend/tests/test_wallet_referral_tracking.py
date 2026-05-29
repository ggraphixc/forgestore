"""
Tests for wallet, referral, and tracking API endpoints that the
redesigned marketplace templates call via client-side JavaScript.

Endpoints tested:
  Wallet:    POST /api/wallet/fund  |  GET /api/wallet/balance  |  GET /api/wallet/transactions
  Referral:  POST /api/referrals/create  |  GET /api/referrals/stats
             GET /api/referrals/earnings  |  GET /api/referrals/history  |  POST /api/referrals/withdraw
  Tracking:  GET /api/orders/{order_id}/tracking  |  GET /api/orders/tracking/{tracking_number}
"""

import pytest
import os


def login_customer(client, email="testuser@example.com", password="testpass123"):
    """Helper: log in as a customer user via the auth endpoint.
    FastAPI TestClient maintains cookies across requests automatically."""
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.cookies


class TestWallet:
    """Wallet API endpoints — used by account/wallet.html JS."""

    def test_wallet_balance_unauthenticated(self, client):
        """GET /api/wallet/balance returns 401 without auth."""
        resp = client.get("/api/wallet/balance")
        assert resp.status_code == 401

    def test_wallet_balance_authenticated(self, client, sample_user):
        """GET /api/wallet/balance returns a balance for authenticated user."""
        login_customer(client)
        resp = client.get("/api/wallet/balance")
        assert resp.status_code == 200
        data = resp.json()
        assert "balance" in data
        assert data["currency"] == "NGN"

    def test_wallet_transactions_empty(self, client, sample_user):
        """GET /api/wallet/transactions returns empty list for new user."""
        login_customer(client)
        resp = client.get("/api/wallet/transactions")
        assert resp.status_code == 200
        data = resp.json()
        assert "transactions" in data
        assert data["transactions"] == []

    def test_wallet_fund_unauthenticated(self, client):
        """POST /api/wallet/fund returns 401 without auth."""
        resp = client.post("/api/wallet/fund", json={"amount": 1000})
        assert resp.status_code == 401

    @pytest.mark.xfail(reason="Requires PAYSTACK_SECRET_KEY or mocked payment provider")
    def test_wallet_fund_authenticated(self, client, sample_user):
        """POST /api/wallet/fund returns a payment initialization for authenticated user."""
        login_customer(client)
        resp = client.post("/api/wallet/fund", json={"amount": 5000, "provider": "paystack"})
        assert resp.status_code == 200
        data = resp.json()
        # Payment initialization returns gateway-specific response
        assert any(k in data for k in ("authorization_url", "reference", "status", "data"))

    @pytest.mark.xfail(reason="Requires PAYSTACK_SECRET_KEY or mocked payment provider")
    def test_wallet_fund_invalid_amount(self, client, sample_user):
        """POST /api/wallet/fund with negative amount returns error."""
        login_customer(client)
        resp = client.post("/api/wallet/fund", json={"amount": -100})
        assert resp.status_code in (400, 422)


class TestReferral:
    """Referral API endpoints — used by account/referrals.html JS."""

    def test_referral_create_unauthenticated(self, client):
        """POST /api/referrals/create returns 401 without auth."""
        resp = client.post("/api/referrals/create")
        assert resp.status_code == 401

    def test_referral_create_authenticated(self, client, sample_user):
        """POST /api/referrals/create returns a referral code for authenticated user."""
        login_customer(client)
        resp = client.post("/api/referrals/create")
        assert resp.status_code == 200
        data = resp.json()
        assert "code" in data
        assert len(data["code"]) > 0
        assert "id" in data

    def test_referral_stats_auto_creates(self, client, sample_user):
        """GET /api/referrals/stats auto-creates an affiliate and returns stats."""
        login_customer(client)
        resp = client.get("/api/referrals/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "referral_code" in data
        assert "total_earnings" in data
        assert "pending_earnings" in data
        assert "total_referrals" in data
        # Fresh account should have zero stats
        assert data["total_earnings"] == 0.0
        assert data["total_referrals"] == 0

    def test_referral_stats_after_create(self, client, sample_user):
        """GET /api/referrals/stats returns consistent data after explicit creation."""
        login_customer(client)
        # Create first
        create_resp = client.post("/api/referrals/create")
        assert create_resp.status_code == 200
        created_code = create_resp.json()["code"]

        # Then get stats
        stats_resp = client.get("/api/referrals/stats")
        assert stats_resp.status_code == 200
        data = stats_resp.json()
        assert data["referral_code"] == created_code

    def test_referral_earnings_unauthenticated(self, client):
        """GET /api/referrals/earnings returns 401 without auth."""
        resp = client.get("/api/referrals/earnings")
        assert resp.status_code == 401

    def test_referral_earnings_authenticated(self, client, sample_user):
        """GET /api/referrals/earnings returns earnings data."""
        login_customer(client)
        # Auto-create affiliate first
        client.post("/api/referrals/create")

        resp = client.get("/api/referrals/earnings")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_earned" in data
        assert "wallet_balance" in data
        assert "total_paid" in data

    def test_referral_history_authenticated(self, client, sample_user):
        """GET /api/referrals/history returns history list."""
        login_customer(client)
        client.post("/api/referrals/create")

        resp = client.get("/api/referrals/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data

    def test_referral_withdraw_no_earnings(self, client, sample_user):
        """POST /api/referrals/withdraw with no earnings returns 400."""
        login_customer(client)
        client.post("/api/referrals/create")

        resp = client.post("/api/referrals/withdraw", json={"amount": 100})
        # Should fail since there are no earnings (insufficient balance)
        assert resp.status_code == 400

    def test_referral_withdraw_unauthenticated(self, client):
        """POST /api/referrals/withdraw returns 401 without auth."""
        resp = client.post("/api/referrals/withdraw", json={"amount": 100})
        assert resp.status_code == 401


class TestTracking:
    """Order tracking API endpoints — used by account/tracking.html JS."""

    def test_tracking_nonexistent_order(self, client):
        """GET /api/orders/{order_id}/tracking for non-existent order returns empty list."""
        resp = client.get("/api/orders/fake-order-999/tracking")
        assert resp.status_code == 200
        data = resp.json()
        assert "shipments" in data
        assert isinstance(data["shipments"], list)

    def test_tracking_by_number_nonexistent(self, client):
        """GET /api/orders/tracking/{number} for non-existent number returns 404."""
        resp = client.get("/api/orders/tracking/FAKE-TRACK-999")
        assert resp.status_code == 404

    def test_tracking_by_number_empty_string(self, client):
        """GET /api/orders/tracking/ with empty string doesn't crash."""
        resp = client.get("/api/orders/tracking/")
        # FastAPI may redirect (307) or return error (404/405/401)
        # The important thing is the endpoint doesn't crash
        assert resp.status_code < 500  # No server error
