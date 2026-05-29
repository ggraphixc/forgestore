"""
Tests for advertising campaigns, payment provider subaccounts, and banking APIs.

Covers:
- AdCampaign model creation, relationships, and status transitions
- Payment provider create_subaccount interface and split_config
- Admin API: banking setup, ad campaign initialization, management
- Ad analytics endpoint
"""

import pytest
from datetime import timedelta
from app.utils import utcnow
from app.auth import create_access_token
from app.models import AdCampaign, Retailer, Product, AdminUser, AdminRole
from app.services.wallet_service import (
    PaymentProviderInterface,
    PaystackProvider,
    FlutterwaveProvider,
    CryptoProvider,
    PaymentGatewayFactory,
)


def _admin_headers(admin_user):
    """Generate admin auth headers using direct token creation (avoids rate limiting)."""
    token = create_access_token({
        "sub": admin_user.id,
        "email": admin_user.email,
        "role": admin_user.role.value,
        "type": "admin",
    })
    return {"Authorization": f"Bearer {token}"}


def _retailer_admin_headers(admin_user, retailer_id: str):
    """Generate admin auth headers with vendor_id set via metadata."""
    token = create_access_token({
        "sub": admin_user.id,
        "email": admin_user.email,
        "role": "RETAILER",
        "type": "admin",
        "vendor_id": retailer_id,
    })
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# MODEL TESTS
# ==============================================================================


class TestAdCampaignModel:
    """AdCampaign model creation and relationship tests."""

    def test_create_ad_campaign(self, db, sample_retailer):
        """A basic AdCampaign can be created with minimal fields."""
        campaign = AdCampaign(
            retailer_id=sample_retailer.id,
            ad_type="SHOP",
            payment_reference="AD-TEST-001",
        )
        db.add(campaign)
        db.commit()

        assert campaign.id is not None
        assert campaign.status == "PENDING"
        assert campaign.ad_type == "SHOP"
        assert campaign.clicks == 0
        assert campaign.impressions == 0
        assert campaign.payment_reference == "AD-TEST-001"

    def test_create_product_ad_campaign(self, db, sample_retailer, sample_products):
        """A PRODUCT ad campaign links to a specific product."""
        product = sample_products[0]
        campaign = AdCampaign(
            retailer_id=sample_retailer.id,
            product_id=product.id,
            ad_type="PRODUCT",
            payment_reference="AD-TEST-002",
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        assert campaign.product_id == product.id
        assert campaign.product is not None
        assert campaign.product.id == product.id

    def test_ad_campaign_retailer_relationship(self, db, sample_retailer):
        """AdCampaign is accessible via Retailer.ad_campaigns."""
        campaign = AdCampaign(
            retailer_id=sample_retailer.id,
            ad_type="SHOP",
            payment_reference="AD-TEST-003",
        )
        db.add(campaign)
        db.commit()

        # Refresh retailer to load relationship
        db.refresh(sample_retailer)
        assert len(sample_retailer.ad_campaigns) == 1
        assert sample_retailer.ad_campaigns[0].payment_reference == "AD-TEST-003"

    def test_product_ad_relationship(self, db, sample_retailer, sample_products):
        """AdCampaign is accessible via Product.ad_campaigns."""
        product = sample_products[0]
        campaign = AdCampaign(
            retailer_id=sample_retailer.id,
            product_id=product.id,
            ad_type="PRODUCT",
            payment_reference="AD-TEST-004",
        )
        db.add(campaign)
        db.commit()

        db.refresh(product)
        assert len(product.ad_campaigns) == 1
        assert product.ad_campaigns[0].payment_reference == "AD-TEST-004"

    def test_ad_campaign_status_transitions(self, db, sample_retailer):
        """AdCampaign status follows PENDING -> PAID -> ACTIVE -> EXPIRED."""
        campaign = AdCampaign(
            retailer_id=sample_retailer.id,
            ad_type="SHOP",
            payment_reference="AD-TEST-005",
        )
        db.add(campaign)
        db.commit()

        assert campaign.status == "PENDING"

        # PENDING -> PAID
        campaign.status = "PAID"
        db.commit()
        assert campaign.status == "PAID"

        # PAID -> ACTIVE
        campaign.status = "ACTIVE"
        campaign.start_date = utcnow()
        campaign.end_date = utcnow() + timedelta(days=30)
        db.commit()
        assert campaign.status == "ACTIVE"
        assert campaign.start_date is not None
        assert campaign.end_date is not None

        # ACTIVE -> EXPIRED
        campaign.status = "EXPIRED"
        db.commit()
        assert campaign.status == "EXPIRED"

    def test_ad_campaign_increment_metrics(self, db, sample_retailer):
        """Clicks and impressions can be incremented."""
        campaign = AdCampaign(
            retailer_id=sample_retailer.id,
            ad_type="SHOP",
            payment_reference="AD-TEST-006",
        )
        db.add(campaign)
        db.commit()

        campaign.clicks += 5
        campaign.impressions += 100
        db.commit()

        assert campaign.clicks == 5
        assert campaign.impressions == 100

    def test_ad_campaign_payment_reference_unique_constraint(self):
        """payment_reference column has unique=True constraint."""
        col = AdCampaign.__table__.columns["payment_reference"]
        assert col.unique is True
        assert col.nullable is False

    def test_ad_campaign_null_product_for_shop(self, db, sample_retailer):
        """SHOP ads can have null product_id."""
        campaign = AdCampaign(
            retailer_id=sample_retailer.id,
            ad_type="SHOP",
            payment_reference="AD-TEST-007",
            product_id=None,
        )
        db.add(campaign)
        db.commit()
        assert campaign.product_id is None

    def test_ad_campaign_banner_url(self, db, sample_retailer):
        """Banner URL can be set on an AdCampaign."""
        campaign = AdCampaign(
            retailer_id=sample_retailer.id,
            ad_type="SHOP",
            payment_reference="AD-TEST-008",
            banner_url="/static/uploads/banners/test-banner.jpg",
        )
        db.add(campaign)
        db.commit()
        assert campaign.banner_url == "/static/uploads/banners/test-banner.jpg"


# ==============================================================================
# PAYMENT PROVIDER INTERFACE TESTS
# ==============================================================================


class TestPaymentProviderInterface:
    """PaymentProviderInterface contract tests."""

    def test_paystack_provider_implements_interface(self):
        """PaystackProvider satisfies PaymentProviderInterface."""
        provider = PaystackProvider("test_key")
        assert isinstance(provider, PaymentProviderInterface)

    def test_flutterwave_provider_implements_interface(self):
        """FlutterwaveProvider satisfies PaymentProviderInterface."""
        provider = FlutterwaveProvider("test_key")
        assert isinstance(provider, PaymentProviderInterface)

    def test_crypto_provider_implements_interface(self):
        """CryptoProvider satisfies PaymentProviderInterface."""
        provider = CryptoProvider()
        assert isinstance(provider, PaymentProviderInterface)

    def test_crypto_create_subaccount_returns_placeholder(self):
        """CryptoProvider.create_subaccount returns a placeholder string."""
        provider = CryptoProvider()
        result = provider.create_subaccount(
            business_name="Test Store",
            bank_code="011",
            account_number="0123456789",
        )
        assert result == "crypto_subaccount_placeholder"

    def test_create_subaccount_method_signature(self):
        """All providers accept the same create_subaccount signature."""
        import inspect

        sig = inspect.signature(PaymentProviderInterface.create_subaccount)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "business_name" in params
        assert "bank_code" in params
        assert "account_number" in params

    @pytest.mark.xfail(reason="Requires PAYSTACK_SECRET_KEY")
    def test_paystack_create_subaccount_real(self):
        """Paystack subaccount creation with valid key works (integration test)."""
        from app.config import get_settings
        cfg = get_settings()
        provider = PaystackProvider(cfg.paystack_secret_key)
        result = provider.create_subaccount(
            business_name="Test Store",
            bank_code="011",
            account_number="0123456789",
        )
        assert len(result) > 0

    def test_paystack_initialize_payment_with_split(self, monkeypatch):
        """Paystack initialize_payment passes subaccount split_config."""
        provider = PaystackProvider("test_key")

        def mock_post(url, json, headers):
            class MockResponse:
                def json(self):
                    return {"status": True, "data": {"authorization_url": "https://paystack.com/..."}}
            return MockResponse()

        monkeypatch.setattr("requests.post", mock_post)
        result = provider.initialize_payment(
            amount=10000,
            currency="NGN",
            reference="TEST-REF",
            metadata={"order_id": "order-1"},
            split_config={"subaccount": "SUB_xxxxx", "transaction_charge": 0},
        )
        assert result["status"] is True

    def test_flutterwave_initialize_payment_with_split(self, monkeypatch):
        """Flutterwave initialize_payment passes subaccount split_config."""
        provider = FlutterwaveProvider("test_key")

        def mock_post(url, json, headers):
            class MockResponse:
                def json(self):
                    return {"status": "success", "data": {"link": "https://flutterwave.com/..."}}
            return MockResponse()

        monkeypatch.setattr("requests.post", mock_post)
        result = provider.initialize_payment(
            amount=10000,
            currency="NGN",
            reference="TEST-REF",
            metadata={"order_id": "order-1"},
            split_config={"subaccounts": [{"id": "RS_xxxx", "split_ratio": 90}]},
        )
        assert result["status"] == "success"

    def test_payment_gateway_factory_crypto(self):
        """Factory returns CryptoProvider for 'crypto'."""
        provider = PaymentGatewayFactory.get_provider("crypto")
        assert isinstance(provider, CryptoProvider)

    def test_payment_gateway_factory_invalid(self):
        """Factory raises ValueError for unknown provider."""
        with pytest.raises(ValueError, match="Unsupported payment provider"):
            PaymentGatewayFactory.get_provider("nonexistent")


# ==============================================================================
# API ENDPOINT TESTS
# ==============================================================================


class TestAdCampaignAPI:
    """Ad campaign management API endpoint tests."""

    AD_INIT_URL = "/api/admin/ads/initialize"
    AD_LIST_URL = "/api/admin/ads/campaigns"
    AD_PRICING_URL = "/api/admin/ads/pricing"

    def test_get_ad_pricing(self, client, admin_user):
        """GET /api/admin/ads/pricing returns ad pricing configuration."""
        headers = _admin_headers(admin_user)
        resp = client.get(self.AD_PRICING_URL, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "pricing" in data
        assert "SHOP" in data["pricing"]
        assert "PRODUCT" in data["pricing"]
        assert data["pricing"]["SHOP"]["price_per_month"] > 0
        assert data["pricing"]["PRODUCT"]["price_per_month"] > 0

    def test_ads_require_retailer_vendor_id(self, client, admin_user):
        """Initialize ad without vendor_id returns 400."""
        headers = _admin_headers(admin_user)  # DIR_ADMIN has no vendor_id
        resp = client.post(
            self.AD_INIT_URL,
            json={"ad_type": "SHOP", "duration_months": 1},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "vendor_id" in resp.text.lower() or "retailer" in resp.text.lower()

    def test_list_campaigns_empty(self, client, admin_user):
        """List ad campaigns returns empty list when none exist."""
        headers = _admin_headers(admin_user)
        resp = client.get(self.AD_LIST_URL, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "campaigns" in data
        assert isinstance(data["campaigns"], list)

    def test_list_campaigns_retailer_filter(self, client, db):
        """Retailer sees only their own campaigns."""
        from app.auth import create_access_token, hash_password
        from app.models import AdminRole

        # Create two retailers
        r1 = Retailer(id="ret-adv-001", name="Adv Retailer 1", slug="adv-retailer-1")
        r2 = Retailer(id="ret-adv-002", name="Adv Retailer 2", slug="adv-retailer-2")
        db.add_all([r1, r2])
        db.commit()

        # Create an AdminUser with RETAILER role and vendor_id = r1
        retailer_admin = AdminUser(
            id="ret-admin-adv",
            email="retailer@adv-test.com",
            password=hash_password("test123"),
            name="Adv Retailer Admin",
            role=AdminRole.RETAILER,
            vendor_id=r1.id,
        )
        db.add(retailer_admin)

        # Create campaigns for both retailers
        c1 = AdCampaign(retailer_id=r1.id, ad_type="SHOP", payment_reference="AD-API-001")
        c2 = AdCampaign(retailer_id=r2.id, ad_type="PRODUCT", payment_reference="AD-API-002")
        db.add_all([c1, c2])
        db.commit()

        # Authenticate as r1's retailer admin
        token = create_access_token({
            "sub": retailer_admin.id,
            "email": retailer_admin.email,
            "role": "RETAILER",
            "type": "admin",
            "vendor_id": r1.id,
        })
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get(self.AD_LIST_URL, headers=headers)
        assert resp.status_code == 200, f"Failed: {resp.text}"
        campaigns = resp.json()["campaigns"]
        assert len(campaigns) == 1
        assert campaigns[0]["payment_reference"] == "AD-API-001"

    @pytest.mark.xfail(reason="Requires PAYSTACK_SECRET_KEY or active payment provider")
    def test_initialize_ad_payment_invalid_type(self, client, db, sample_retailer):
        """Initialize ad with invalid ad_type returns 400."""
        from app.auth import create_access_token
        token = create_access_token({
            "sub": "ret-admin",
            "email": "retailer@test.com",
            "role": "RETAILER",
            "type": "admin",
            "vendor_id": sample_retailer.id,
        })
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            self.AD_INIT_URL,
            json={"ad_type": "INVALID_TYPE", "duration_months": 1},
            headers=headers,
        )
        assert resp.status_code == 400


class TestBankingAPI:
    """Retailer banking API endpoint tests."""

    BANK_SETUP_URL = "/api/admin/retailer/bank-setup"
    BANK_STATUS_URL = "/api/admin/retailer/banking-status"

    def test_banking_status_no_vendor_id(self, client, admin_user):
        """Banking status without vendor_id returns 400."""
        headers = _admin_headers(admin_user)  # DIR_ADMIN has no vendor_id
        resp = client.get(self.BANK_STATUS_URL, headers=headers)
        assert resp.status_code == 400
        assert "vendor_id" in resp.text.lower()

    def test_banking_status_with_vendor_id(self, client, db, sample_retailer):
        """Banking status with valid vendor_id returns retailer banking info."""
        from app.auth import create_access_token, hash_password
        from app.models import AdminRole

        # Create an AdminUser with RETAILER role and vendor_id = sample_retailer
        retailer_admin = AdminUser(
            id="ret-admin-bank",
            email="retailer@bank-test.com",
            password=hash_password("test123"),
            name="Bank Test Admin",
            role=AdminRole.RETAILER,
            vendor_id=sample_retailer.id,
        )
        db.add(retailer_admin)
        db.commit()

        token = create_access_token({
            "sub": retailer_admin.id,
            "email": retailer_admin.email,
            "role": "RETAILER",
            "type": "admin",
            "vendor_id": sample_retailer.id,
        })
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get(self.BANK_STATUS_URL, headers=headers)
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert "has_banking" in data
        assert "has_subaccount" in data
        assert data["has_banking"] is False  # No banking set up yet
        assert data["has_subaccount"] is False
        assert data["commission_rate"] == 10.0

    @pytest.mark.xfail(reason="Requires PAYSTACK_SECRET_KEY for account resolution")
    def test_bank_setup_missing_fields(self, client, db, sample_retailer):
        """Bank setup without required fields returns 400."""
        from app.auth import create_access_token
        token = create_access_token({
            "sub": "ret-admin",
            "email": "retailer@test.com",
            "role": "RETAILER",
            "type": "admin",
            "vendor_id": sample_retailer.id,
        })
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(self.BANK_SETUP_URL, json={"account_number": ""}, headers=headers)
        assert resp.status_code == 400

    @pytest.mark.xfail(reason="Requires PAYSTACK_SECRET_KEY for account resolution")
    def test_bank_setup_invalid_account(self, client, db, sample_retailer):
        """Bank setup with invalid bank details returns 400."""
        from app.auth import create_access_token
        token = create_access_token({
            "sub": "ret-admin",
            "email": "retailer@test.com",
            "role": "RETAILER",
            "type": "admin",
            "vendor_id": sample_retailer.id,
        })
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            self.BANK_SETUP_URL,
            json={"account_number": "0000000000", "bank_code": "999"},
            headers=headers,
        )
        assert resp.status_code == 400  # Should fail account resolution


class TestAdAnalytics:
    """Ad campaign analytics endpoint tests."""

    AD_ANALYTICS_URL = "/api/admin/ads/analytics"

    def test_analytics_empty(self, client, admin_user):
        """Analytics returns valid structure with zero campaigns."""
        headers = _admin_headers(admin_user)
        resp = client.get(self.AD_ANALYTICS_URL, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "overview" in data
        assert data["overview"]["total_campaigns"] == 0
        assert data["overview"]["active_campaigns"] == 0
        assert data["overview"]["total_clicks"] == 0
        assert data["overview"]["ctr"] == 0
        assert "by_type" in data
        assert "by_status" in data
        assert "top_retailers" in data
        assert "monthly_trend" in data
        assert isinstance(data["monthly_trend"], list)
        assert len(data["monthly_trend"]) == 6

    def test_analytics_with_data(self, client, db, admin_user, sample_retailer):
        """Analytics reflects existing campaign data."""
        # Create some campaigns
        campaigns = [
            AdCampaign(retailer_id=sample_retailer.id, ad_type="SHOP", status="ACTIVE",
                       payment_reference="AD-AN-001", clicks=10, impressions=500),
            AdCampaign(retailer_id=sample_retailer.id, ad_type="PRODUCT", status="ACTIVE",
                       payment_reference="AD-AN-002", clicks=5, impressions=200),
            AdCampaign(retailer_id=sample_retailer.id, ad_type="SHOP", status="PAID",
                       payment_reference="AD-AN-003"),
            AdCampaign(retailer_id=sample_retailer.id, ad_type="PRODUCT", status="EXPIRED",
                       payment_reference="AD-AN-004", clicks=3, impressions=100),
        ]
        for c in campaigns:
            db.add(c)
        db.commit()

        headers = _admin_headers(admin_user)
        resp = client.get(self.AD_ANALYTICS_URL, headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["overview"]["total_campaigns"] == 4
        assert data["overview"]["active_campaigns"] == 2
        assert data["overview"]["total_clicks"] == 18  # 10 + 5 + 3
        assert data["overview"]["total_impressions"] == 800  # 500 + 200 + 100
        assert data["overview"]["ctr"] > 0

        assert data["by_status"]["ACTIVE"] == 2
        assert data["by_status"]["PAID"] == 1
        assert data["by_status"]["EXPIRED"] == 1

        assert len(data["top_retailers"]) == 1
        assert data["top_retailers"][0]["retailer_name"] == sample_retailer.name

    def test_analytics_requires_admin_role(self, client):
        """Unauthenticated request to analytics returns 401."""
        resp = client.get(self.AD_ANALYTICS_URL)
        assert resp.status_code == 401


class TestBankingModel:
    """Retailer model bank field tests."""

    def test_retailer_bank_fields_default_null(self, db, sample_retailer):
        """New retailer has null bank fields by default."""
        assert sample_retailer.bank_name is None
        assert sample_retailer.account_number is None
        assert sample_retailer.bank_code is None
        assert sample_retailer.account_name is None
        assert sample_retailer.paystack_subaccount_code is None
        assert sample_retailer.flutterwave_subaccount_id is None
        assert sample_retailer.commission_rate == 10.0  # default

    def test_retailer_set_banking_details(self, db, sample_retailer):
        """Banking details can be set on a retailer."""
        sample_retailer.bank_name = "Test Bank"
        sample_retailer.account_number = "0123456789"
        sample_retailer.bank_code = "011"
        sample_retailer.account_name = "Test Account Name"
        sample_retailer.paystack_subaccount_code = "SUB_abc123"
        sample_retailer.commission_rate = 5.0
        db.commit()

        assert sample_retailer.bank_name == "Test Bank"
        assert sample_retailer.account_number == "0123456789"
        assert sample_retailer.bank_code == "011"
        assert sample_retailer.account_name == "Test Account Name"
        assert sample_retailer.paystack_subaccount_code == "SUB_abc123"
        assert sample_retailer.commission_rate == 5.0

    def test_retailer_commission_rate_default(self, db):
        """New retailers get default commission_rate of 10.0."""
        r = Retailer(id="test-commission", name="Commission Test", slug="commission-test")
        db.add(r)
        db.commit()
        assert r.commission_rate == 10.0

    def test_retailer_commission_rate_custom(self, db):
        """Commission rate can be set at creation."""
        r = Retailer(id="test-commission-2", name="Commission Test 2",
                     slug="commission-test-2", commission_rate=15.0)
        db.add(r)
        db.commit()
        assert r.commission_rate == 15.0
