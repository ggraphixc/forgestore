"""
Tests for authentication endpoints:
- POST /api/auth/signup
- POST /api/auth/login
- GET /api/account/profile (authenticated)
"""

import pytest


class TestAuth:
    """Authentication endpoint tests."""

    def test_signup_success(self, client):
        """A new user can sign up with valid credentials."""
        resp = client.post("/api/auth/signup", json={
            "email": "newuser@example.com",
            "password": "secure123!",
            "name": "New User",
        })
        assert resp.status_code == 200, f"Signup failed: {resp.text}"
        data = resp.json()
        assert "access_token" in data, f"Missing access_token in {data}"
        assert "user" in data
        assert data["user"]["email"] == "newuser@example.com"

    def test_signup_duplicate_email(self, client, sample_user):
        """Signup with an existing email returns 400."""
        resp = client.post("/api/auth/signup", json={
            "email": sample_user.email,
            "password": "testpass123",
            "name": "Duplicate User",
        })
        assert resp.status_code in (400, 409), (
            f"Expected 400/409 for duplicate, got {resp.status_code}: {resp.text}"
        )

    def test_login_success(self, client, sample_user):
        """A registered user can log in with correct credentials."""
        resp = client.post("/api/auth/login", json={
            "email": "testuser@example.com",
            "password": "testpass123",
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        data = resp.json()
        assert "access_token" in data, f"Missing access_token in {data}"
        assert "user" in data
        assert data["is_admin"] is False

    def test_login_wrong_password(self, client, sample_user):
        """Login with wrong password returns 401."""
        resp = client.post("/api/auth/login", json={
            "email": "testuser@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401, (
            f"Expected 401 for wrong password, got {resp.status_code}: {resp.text}"
        )

    def test_login_nonexistent_user(self, client):
        """Login with unregistered email returns 401."""
        resp = client.post("/api/auth/login", json={
            "email": "nobody@example.com",
            "password": "somepass",
        })
        assert resp.status_code == 401, (
            f"Expected 401 for nonexistent user, got {resp.status_code}: {resp.text}"
        )

    def test_profile_authenticated(self, client, sample_user):
        """Authenticated user can fetch their profile."""
        # Login first to get the cookie
        login_resp = client.post("/api/auth/login", json={
            "email": "testuser@example.com",
            "password": "testpass123",
        })
        assert login_resp.status_code == 200

        # Use the cookie from the login response
        cookies = login_resp.cookies
        resp = client.get("/api/account/profile", cookies=cookies)
        assert resp.status_code == 200, f"Profile fetch failed: {resp.text}"
        data = resp.json()
        assert data["email"] == "testuser@example.com"

    def test_profile_unauthenticated(self, client):
        """Unauthenticated request to profile returns 401."""
        resp = client.get("/api/account/profile")
        assert resp.status_code == 401, (
            f"Expected 401 for unauthenticated, got {resp.status_code}"
        )
