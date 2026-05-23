"""
Tests for cart API endpoints:
- GET  /api/cart
- POST /api/cart/add
- PUT  /api/cart/update
- DELETE /api/cart/remove/{product_id}
"""

import pytest


class TestCart:
    """Shopping cart endpoint tests."""

    def test_get_empty_cart(self, client):
        """A new cart should be empty."""
        resp = client.get("/api/cart")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["count"] == 0
        assert data["total"] == 0.0

    def test_add_to_cart(self, client, sample_products):
        """Add a product to cart returns success."""
        resp = client.post("/api/cart/add", json={
            "product_id": "test-prod-001",
            "quantity": 2,
        })
        assert resp.status_code == 200, f"Add to cart failed: {resp.text}"
        assert resp.json()["success"] is True

    def test_add_to_cart_nonexistent_product(self, client):
        """Adding a non-existent product returns 404."""
        resp = client.post("/api/cart/add", json={
            "product_id": "fake-product-id",
            "quantity": 1,
        })
        assert resp.status_code == 404

    def test_cart_contains_added_items(self, client, sample_products):
        """Items added to cart appear in GET /api/cart."""
        client.post("/api/cart/add", json={
            "product_id": "test-prod-001",
            "quantity": 2,
        })
        client.post("/api/cart/add", json={
            "product_id": "test-prod-002",
            "quantity": 1,
        })

        resp = client.get("/api/cart")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

        # Find the products by product_id
        items_by_id = {i["product_id"]: i for i in data["items"]}
        assert "test-prod-001" in items_by_id
        assert items_by_id["test-prod-001"]["quantity"] == 2
        assert "test-prod-002" in items_by_id
        assert items_by_id["test-prod-002"]["quantity"] == 1

    def test_update_cart_quantity(self, client, sample_products):
        """Updating cart item quantity works."""
        # Add item first
        add_resp = client.post("/api/cart/add", json={
            "product_id": "test-prod-001",
            "quantity": 1,
        })
        assert add_resp.status_code == 200

        # Update quantity
        update_resp = client.put("/api/cart/update", json={
            "product_id": "test-prod-001",
            "quantity": 5,
        })
        assert update_resp.status_code == 200

        # Verify the updated quantity
        cart_resp = client.get("/api/cart")
        items = cart_resp.json()["items"]
        item = next(i for i in items if i["product_id"] == "test-prod-001")
        assert item["quantity"] == 5

    def test_remove_from_cart(self, client, sample_products):
        """Removing an item from cart works."""
        # Add two items
        client.post("/api/cart/add", json={"product_id": "test-prod-001", "quantity": 1})
        client.post("/api/cart/add", json={"product_id": "test-prod-002", "quantity": 1})

        # Remove one
        remove_resp = client.delete("/api/cart/remove/test-prod-001")
        assert remove_resp.status_code == 200

        # Verify only one remains
        cart_resp = client.get("/api/cart")
        data = cart_resp.json()
        assert data["count"] == 1
        assert data["items"][0]["product_id"] == "test-prod-002"

    def test_cart_total_calculation(self, client, sample_products):
        """Cart total is correctly calculated using discount_price if available."""
        # test-prod-001 has price=99.99, discount_price=79.99
        # test-prod-002 has price=149.99, no discount
        client.post("/api/cart/add", json={"product_id": "test-prod-001", "quantity": 2})
        client.post("/api/cart/add", json={"product_id": "test-prod-002", "quantity": 1})

        resp = client.get("/api/cart")
        data = resp.json()
        expected_total = (79.99 * 2) + 149.99  # = 309.97
        assert abs(data["total"] - expected_total) < 0.01, (
            f"Expected total {expected_total}, got {data['total']}"
        )
