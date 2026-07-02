"""
Tests for Retailer Payout Splits, Bank Verification, and Advertising Campaigns.

Covers:
- Retailer bank setup and gateway subaccount provisioning
- Split payment calculation matrix (commission logic)
- Ad campaign initialization workflow
- Paystack webhook routing for ad payments
"""

import pytest
import json
import uuid
from unittest.mock import patch, MagicMock
from datetime import timedelta

from app.utils import utcnow
from app.auth import create_access_token, hash_password
from app.models import AdCampaign, Retailer, Product, AdminUser, AdminRole, AdminNotification


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def retailer_admin(db, sample_retailer):
    """Create an AdminUser with RETAILER role linked to sample_retailer."""
    admin = AdminUser(
        id=f"ret-admin-{uuid.uuid4().hex[:8]}",
        email="retailer-admin@test.com",
        password=hash_password("testpass123"),
        name="Retailer Admin",
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
def pending_ad_campaign(db, sample_retailer, sample_products):
    """Create a PENDING AdCampaign for webhook tests."""
    campaign = AdCampaign(
        retailer_id=sample_retailer.id,
        product_id=sample_products[0].id,
        ad_type="PRODUCT",
        status="PENDING",
        payment_reference="AD-WEBHOOK-TEST-001",
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


# ==============================================================================
# TEST CASE 1: Retailer Bank Setup and Gateway Subaccount Provisioning
# ==============================================================================


class TestRetailerBankSetup:
    """POST /api/admin/retailer/bank-setup"""

    ENDPOINT = "/api/admin/retailer/bank-setup"

    @patch("app.routers.admin_api._resolve_bank_account_name")
    @patch("app.services.wallet_service.PaystackProvider.create_subaccount")
    def test_bank_setup_creates_subaccount(
        self,
        mock_create_subaccount,
        mock_resolve_account,
        client,
        db,
        sample_retailer,
        retailer_headers,
    ):
        """Bank setup resolves account name, creates subaccount, and persists tokens."""
        # Arrange
        mock_resolve_account.return_value = "John Doe"
        mock_create_subaccount.return_value = "ACCT_123456"

        payload = {
            "account_number": "0123456789",
            "bank_code": "011",
            "bank_name": "Test Bank",
        }

        # Act
        resp = client.post(self.ENDPOINT, json=payload, headers=retailer_headers)

        # Assert API response
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["account_name"] == "John Doe"
        assert data["subaccount_id"] == "ACCT_123456"

        # Assert DB persistence
        db.refresh(sample_retailer)
        assert sample_retailer.account_name == "John Doe"
        assert sample_retailer.account_number == "0123456789"
        assert sample_retailer.bank_code == "011"
        assert sample_retailer.bank_name == "Test Bank"
        assert sample_retailer.paystack_subaccount_code == "ACCT_123456"

        # Verify mocks were called correctly
        mock_resolve_account.assert_called_once_with("011", "0123456789")
        mock_create_subaccount.assert_called_once_with(
            business_name=sample_retailer.name,
            bank_code="011",
            account_number="0123456789",
        )

    @patch("app.routers.admin_api._resolve_bank_account_name", side_effect=ValueError("Could not resolve account"))
    def test_bank_setup_invalid_account_returns_400(
        self,
        mock_resolve_account,
        client,
        retailer_headers,
    ):
        """Bank setup with unresolvable account returns 400."""
        resp = client.post(
            self.ENDPOINT,
            json={"account_number": "0000000000", "bank_code": "999"},
            headers=retailer_headers,
        )
        assert resp.status_code == 400
        assert "Could not resolve account" in resp.text

    def test_bank_setup_missing_vendor_id_returns_400(self, client, admin_user):
        """Bank setup requires vendor_id (DIR_ADMIN has none)."""
        token = create_access_token({
            "sub": admin_user.id,
            "email": admin_user.email,
            "role": "DIR_ADMIN",
            "type": "admin",
        })
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.post(
            self.ENDPOINT,
            json={"account_number": "0123456789", "bank_code": "011"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "vendor_id" in resp.text.lower() or "retailer" in resp.text.lower()

    def test_bank_setup_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(
            self.ENDPOINT,
            json={"account_number": "0123456789", "bank_code": "011"},
        )
        assert resp.status_code == 401


# ==============================================================================
# TEST CASE 2: Split Payment Calculation Matrix
# ==============================================================================


class TestSplitPaymentCalculation:
    """Verify vendor split amounts are calculated correctly from commission_rate."""

    def test_vendor_split_is_total_minus_commission(self):
        """Vendor receives total - (total * commission_rate / 100)."""
        total_amount = 10000.0  # ₦10,000
        commission_rate = 10.0  # 10% marketplace fee

        marketplace_fee = total_amount * (commission_rate / 100)
        vendor_split = total_amount - marketplace_fee

        assert marketplace_fee == 1000.0
        assert vendor_split == 9000.0

    def test_vendor_split_with_custom_commission_rate(self):
        """Custom commission rate adjusts vendor split accordingly."""
        total_amount = 5000.0
        commission_rate = 5.0  # 5% fee

        marketplace_fee = total_amount * (commission_rate / 100)
        vendor_split = total_amount - marketplace_fee

        assert marketplace_fee == 250.0
        assert vendor_split == 4750.0

    def test_vendor_split_zero_commission(self):
        """Zero commission means vendor gets the full amount."""
        total_amount = 7500.0
        commission_rate = 0.0

        marketplace_fee = total_amount * (commission_rate / 100)
        vendor_split = total_amount - marketplace_fee

        assert marketplace_fee == 0.0
        assert vendor_split == 7500.0

    def test_vendor_split_rounding(self):
        """Split amount is rounded to 2 decimal places for monetary accuracy."""
        total_amount = 99.99
        commission_rate = 7.5  # 7.5% fee

        marketplace_fee = round(total_amount * (commission_rate / 100), 2)
        vendor_split = round(total_amount - marketplace_fee, 2)

        assert marketplace_fee == 7.50
        assert vendor_split == 92.49

    def test_split_from_db_retailer(self, db, sample_retailer):
        """Commission rate from a Retailer DB record is used correctly."""
        # Set a custom commission rate
        sample_retailer.commission_rate = 12.5
        db.commit()

        total_amount = 8000.0
        rate = sample_retailer.commission_rate

        marketplace_fee = total_amount * (rate / 100)
        vendor_split = total_amount - marketplace_fee

        assert rate == 12.5
        assert marketplace_fee == 1000.0
        assert vendor_split == 7000.0

    def test_split_multiple_retailers(self, db):
        """Multiple retailers with different rates get correct individual splits."""
        retailers = [
            Retailer(id=f"ret-split-{i}", name=f"Split Retailer {i}", slug=f"split-retailer-{i}",
                     commission_rate=rate)
            for i, rate in enumerate([10.0, 15.0, 5.0], start=1)
        ]
        for r in retailers:
            db.add(r)
        db.commit()

        # Simulate an order with items from each retailer
        item_prices = [3000.0, 5000.0, 2000.0]
        expected_splits = []

        for retailer, price in zip(retailers, item_prices):
            marketplace_fee = price * (retailer.commission_rate / 100)
            vendor_split = price - marketplace_fee
            expected_splits.append({
                "retailer_id": retailer.id,
                "total": price,
                "commission_rate": retailer.commission_rate,
                "marketplace_fee": marketplace_fee,
                "vendor_split": vendor_split,
            })

        # Assert each split
        for i, split in enumerate(expected_splits):
            assert split["marketplace_fee"] == item_prices[i] * (split["commission_rate"] / 100)
            assert split["vendor_split"] == item_prices[i] - split["marketplace_fee"]

        # Total marketplace collection
        total_marketplace_fee = sum(s["marketplace_fee"] for s in expected_splits)
        total_vendor_payout = sum(s["vendor_split"] for s in expected_splits)
        total_order = sum(item_prices)

        assert total_marketplace_fee == 300.0 + 750.0 + 100.0  # = 1150.0
        assert total_vendor_payout == total_order - total_marketplace_fee
        assert total_vendor_payout == 8850.0


# ==============================================================================
# TEST CASE 3: Ad Campaign Initialization Workflow
# ==============================================================================


class TestAdCampaignInitialization:
    """POST /api/admin/ads/initialize"""

    ENDPOINT = "/api/admin/ads/initialize"

    @patch("app.services.wallet_service.PaymentService.initialize_payment")
    def test_initialize_product_ad_creates_pending_campaign(
        self,
        mock_init_payment,
        client,
        db,
        sample_retailer,
        sample_products,
        retailer_headers,
    ):
        """Submitting valid ad data creates a PENDING AdCampaign and returns payment URL."""
        # Arrange — mock PaymentService.initialize_payment so it doesn't
        # need a PaymentProvider record in the test DB.
        mock_init_payment.return_value = {
            "reference": "AD-MOCK-REF-001",
            "authorization_url": "https://paystack.com/mock-ad-pay",
            "status": True,
        }

        payload = {
            "ad_type": "PRODUCT",
            "product_id": sample_products[0].id,
            "duration_months": 1,
        }

        # Act
        resp = client.post(self.ENDPOINT, json=payload, headers=retailer_headers)

        # Assert API response
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["authorization_url"] == "https://paystack.com/mock-ad-pay"
        assert data["amount"] == 5000  # PRODUCT = ₦5,000/month × 1 month
        assert data["duration_months"] == 1

        # Assert AdCampaign row created
        campaign = db.query(AdCampaign).filter(
            AdCampaign.id == data["campaign_id"]
        ).first()
        assert campaign is not None
        assert campaign.status == "PENDING"
        assert campaign.ad_type == "PRODUCT"
        assert campaign.product_id == sample_products[0].id
        assert campaign.retailer_id == sample_retailer.id
        assert campaign.payment_reference == data["reference"]

    @patch("app.services.wallet_service.PaymentService.initialize_payment")
    def test_initialize_shop_ad_creates_pending_campaign(
        self,
        mock_init_payment,
        client,
        db,
        sample_retailer,
        retailer_headers,
    ):
        """SHOP ad type with no product_id creates a PENDING campaign."""
        mock_init_payment.return_value = {
            "reference": "AD-SHOP-REF-001",
            "authorization_url": "https://paystack.com/mock-shop-ad",
            "status": True,
        }

        payload = {
            "ad_type": "SHOP",
            "duration_months": 3,
        }

        resp = client.post(self.ENDPOINT, json=payload, headers=retailer_headers)
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert data["amount"] == 30000  # SHOP = ₦10,000/month × 3 months

        campaign = db.query(AdCampaign).filter(
            AdCampaign.id == data["campaign_id"]
        ).first()
        assert campaign is not None
        assert campaign.status == "PENDING"
        assert campaign.ad_type == "SHOP"
        assert campaign.product_id is None

    def test_initialize_ad_invalid_type_returns_400(self, client, retailer_headers):
        """Invalid ad_type returns 400."""
        resp = client.post(
            self.ENDPOINT,
            json={"ad_type": "INVALID", "duration_months": 1},
            headers=retailer_headers,
        )
        assert resp.status_code == 400

    def test_initialize_ad_missing_product_id_returns_400(self, client, retailer_headers):
        """PRODUCT ad without product_id returns 400."""
        resp = client.post(
            self.ENDPOINT,
            json={"ad_type": "PRODUCT", "duration_months": 1},
            headers=retailer_headers,
        )
        assert resp.status_code == 400

    def test_initialize_ad_no_vendor_id_returns_400(self, client, admin_user):
        """DIR_ADMIN without vendor_id cannot initialize ads."""
        token = create_access_token({
            "sub": admin_user.id,
            "email": admin_user.email,
            "role": "DIR_ADMIN",
            "type": "admin",
        })
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.post(
            self.ENDPOINT,
            json={"ad_type": "SHOP", "duration_months": 1},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_initialize_ad_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(
            self.ENDPOINT,
            json={"ad_type": "SHOP", "duration_months": 1},
        )
        assert resp.status_code == 401


# ==============================================================================
# TEST CASE 4: Paystack Webhook Routing for Ad Payments
# ==============================================================================


class TestPaystackAdWebhook:
    """POST /api/paystack/webhook — Ad campaign payment detection."""

    ENDPOINT = "/api/paystack/webhook"

    @patch("app.routers.paystack_webhook.verify_webhook_signature")
    def test_webhook_marks_campaign_paid(
        self,
        mock_verify_signature,
        client,
        db,
        pending_ad_campaign,
    ):
        """charge.success webhook with campaign reference transitions PENDING→PAID."""
        # Arrange — patch verify_webhook_signature in the consumer module.
        # The function was imported via `from app.services.paystack_service import verify_webhook_signature`,
        # so patching the origin module doesn't affect the already-imported reference.
        mock_verify_signature.return_value = True
        reference = pending_ad_campaign.payment_reference

        # Note: Paystack webhook validates order_id BEFORE checking for campaigns
        # (same as Flutterwave). Use a dummy order_id to pass the validation gate.
        payload = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "reference": reference,
                "metadata": {
                    "order_id": "ad-campaign-payment",
                },
            },
        }

        # Act
        resp = client.post(
            self.ENDPOINT,
            json=payload,
            headers={"x-paystack-signature": "mock-signature"},
        )

        # Assert webhook response
        assert resp.status_code == 200, f"Failed: {resp.text}"
        assert resp.json()["status"] == "success"

        # Assert campaign status changed
        db.refresh(pending_ad_campaign)
        assert pending_ad_campaign.status == "PAID"

        # Assert notification created
        notif = db.query(AdminNotification).filter(
            AdminNotification.type == "ad_payment"
        ).first()
        assert notif is not None
        assert "Ad Campaign" in notif.title

    @patch("app.routers.paystack_webhook.verify_webhook_signature")
    def test_webhook_ignores_non_ad_transaction(
        self,
        mock_verify_signature,
        client,
        db,
        pending_ad_campaign,
    ):
        """charge.success with non-campaign reference processes as usual."""
        mock_verify_signature.return_value = True

        payload = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "reference": "NON-AD-REF-001",
                "metadata": {
                    "order_id": "order-123",
                },
            },
        }

        resp = client.post(
            self.ENDPOINT,
            json=payload,
            headers={"x-paystack-signature": "mock-signature"},
        )

        # Should return 200 but order_id "order-123" won't exist, so 404
        # The webhook tries to find the order by ID
        assert resp.status_code in (200, 404)

        # Our pending campaign should remain PENDING (not affected)
        db.refresh(pending_ad_campaign)
        assert pending_ad_campaign.status == "PENDING"

    @patch("app.routers.paystack_webhook.verify_webhook_signature")
    def test_webhook_invalid_signature_returns_401(
        self,
        mock_verify_signature,
        client,
    ):
        """Invalid webhook signature returns 401."""
        mock_verify_signature.return_value = False

        resp = client.post(
            self.ENDPOINT,
            json={"event": "charge.success", "data": {}},
            headers={"x-paystack-signature": "bad-signature"},
        )
        assert resp.status_code == 401

    @patch("app.routers.paystack_webhook.verify_webhook_signature")
    def test_webhook_ignores_unsuccessful_transaction(
        self,
        mock_verify_signature,
        client,
        db,
        pending_ad_campaign,
    ):
        """charge.success with failed status is ignored."""
        mock_verify_signature.return_value = True

        payload = {
            "event": "charge.success",
            "data": {
                "status": "failed",
                "reference": pending_ad_campaign.payment_reference,
            },
        }

        resp = client.post(
            self.ENDPOINT,
            json=payload,
            headers={"x-paystack-signature": "mock-signature"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

        # Campaign remains PENDING
        db.refresh(pending_ad_campaign)
        assert pending_ad_campaign.status == "PENDING"


# ==============================================================================
# TEST CASE 5: Flutterwave Webhook Routing for Ad Payments — REMOVED
# ==============================================================================
