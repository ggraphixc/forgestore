"""
Tests for checkout flow:
- POST /api/checkout
"""

import pytest


class TestCheckout:
    """Checkout endpoint tests."""

    def test_checkout_empty_cart(self, client):
        """Checking out with an empty cart returns 400."""
        resp = client.post("/api/checkout", json={
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+2348000000000",
            "address": "123 Test St, Lagos",
        })
        assert resp.status_code == 400
        assert "empty" in resp.text.lower()

    def test_checkout_success(self, client, sample_products):
        """A successful checkout creates an order and clears the cart."""
        # Add items to cart first
        client.post("/api/cart/add", json={
            "product_id": "test-prod-001",
            "quantity": 2,
        })
        client.post("/api/cart/add", json={
            "product_id": "test-prod-002",
            "quantity": 1,
        })

        # Verify items are in cart
        pre_cart = client.get("/api/cart").json()
        assert pre_cart["count"] == 2

        # Checkout
        resp = client.post("/api/checkout", json={
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "+2348012345678",
            "address": "456 Shop St, Abuja",
        })
        assert resp.status_code == 200, f"Checkout failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert "order_id" in data
        assert "order_number" in data
        assert data["order_number"].startswith("FS-")

    def test_checkout_creates_guest_user(self, client, sample_products):
        """Checkout with a new email creates a guest customer."""
        # Add item
        client.post("/api/cart/add", json={
            "product_id": "test-prod-001",
            "quantity": 1,
        })

        resp = client.post("/api/checkout", json={
            "name": "Guest Shopper",
            "email": "guest@example.com",
            "phone": "+2348099999999",
            "address": "789 Guest Rd, Port Harcourt",
        })
        assert resp.status_code == 200, f"Guest checkout failed: {resp.text}"

    def test_checkout_clears_cart(self, client, sample_products):
        """After a successful checkout, the cart should be empty."""
        client.post("/api/cart/add", json={
            "product_id": "test-prod-001",
            "quantity": 1,
        })

        client.post("/api/checkout", json={
            "name": "Clean Cart",
            "email": "cleancart@example.com",
            "phone": "+2348000000001",
            "address": "101 Empty Ln, Ibadan",
        })

        # Cart should now be empty
        cart_resp = client.get("/api/cart").json()
        assert cart_resp["count"] == 0
        assert cart_resp["items"] == []
