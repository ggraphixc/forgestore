from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


# --- Auth ---
class LoginRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None
    phone: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# --- Cart ---
class CartAddRequest(BaseModel):
    product_id: str
    quantity: int = 1


class CartUpdateRequest(BaseModel):
    product_id: str
    quantity: int


# --- Checkout ---
class CheckoutRequest(BaseModel):
    name: str
    email: str
    phone: str
    address: str


# --- Ad Campaigns ---
class AdCampaignCreate(BaseModel):
    product_id: Optional[str] = None
    retailer_id: Optional[str] = None
    ad_type: str  # PRODUCT, SHOP, or SYSTEM_PROMO
    banner_url: str
    target_url: Optional[str] = None
    duration_months: int = 1

    def validate_type(self):
        if self.ad_type == "PRODUCT" and not self.product_id:
            raise ValueError("product_id required for PRODUCT ad type")
        if self.ad_type == "SHOP" and not self.retailer_id:
            raise ValueError("retailer_id required for SHOP ad type")
        if self.ad_type == "SYSTEM_PROMO" and not self.banner_url:
            raise ValueError("banner_url required for SYSTEM_PROMO ad type")


class AdCampaignUpdate(BaseModel):
    product_id: Optional[str] = None
    retailer_id: Optional[str] = None
    ad_type: Optional[str] = None
    banner_url: Optional[str] = None
    target_url: Optional[str] = None
    status: Optional[str] = None


class AdCampaignResponse(BaseModel):
    id: str
    product_id: Optional[str] = None
    retailer_id: Optional[str] = None
    ad_type: str
    status: str
    banner_url: str
    target_url: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    clicks: int = 0
    impressions: int = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Reviews ---
class ReviewCreateRequest(BaseModel):
    product_id: str
    rating: int
    title: Optional[str] = None
    content: Optional[str] = None
    author: Optional[str] = None


# --- Products ---
class ProductResponse(BaseModel):
    id: str
    slug: str
    name: str
    brand: Optional[str] = None
    description: Optional[str] = None
    price: float
    discount_price: Optional[float] = None
    images: Optional[list] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    retailer_id: Optional[str] = None
    retailer_name: Optional[str] = None
    sub_category: Optional[str] = None
    inventory: int = 0
    rating: float = 0.0
    review_count: int = 0
    is_new_arrival: bool = False
    is_flagship: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    price: float
    discount_price: Optional[float] = None
    images: Optional[List[str]] = None
    category_id: Optional[str] = None
    retailer_id: Optional[str] = None
    sub_category: Optional[str] = None
    inventory: int = 0
    is_new_arrival: bool = False
    is_flagship: bool = False


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    discount_price: Optional[float] = None
    images: Optional[List[str]] = None
    video_url: Optional[str] = None
    category_id: Optional[str] = None
    retailer_id: Optional[str] = None
    sub_category: Optional[str] = None
    inventory: Optional[int] = None
    vendor_id: Optional[str] = None
    specifications: Optional[dict] = None
    is_new_arrival: Optional[bool] = None
    is_flagship: Optional[bool] = None


# --- Categories ---
class CategoryResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    image: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    image: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None


# --- Retailers ---
class RetailerResponse(BaseModel):
    id: str
    name: str
    slug: str
    bio: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    location: Optional[str] = None
    primary_color: Optional[str] = "zinc"
    status: Optional[str] = "ACTIVE"
    rating: float = 0.0
    review_count: int = 0
    product_count: int = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RetailerCreate(BaseModel):
    name: str
    slug: str
    bio: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    location: Optional[str] = None
    primary_color: Optional[str] = "zinc"


class RetailerUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    bio: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    location: Optional[str] = None
    primary_color: Optional[str] = None
    status: Optional[str] = None


# --- Orders ---
class OrderResponse(BaseModel):
    id: str
    order_number: str
    status: str
    total_amount: float
    shipping_address: dict
    customer_id: str
    customer_name: Optional[str] = None
    items: Optional[List[dict]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Settings ---
class SettingsResponse(BaseModel):
    key: str
    value: str


class SettingsUpdate(BaseModel):
    value: str


# --- Dashboard ---
class DashboardStats(BaseModel):
    total_products: int
    total_categories: int
    total_retailers: int
    total_orders: int
    total_customers: int
    total_revenue: float
    recent_orders: List[dict] = []


# ===== ENTERPRISE SYSTEM SCHEMAS =====

# --- 1. Shipment / Order Tracking ---
class ShipmentCreate(BaseModel):
    order_id: str
    carrier: str
    tracking_number: str
    estimated_delivery: Optional[datetime] = None
    origin: str = ""
    destination: str = ""


class ShipmentStatusUpdate(BaseModel):
    status: str
    location: Optional[str] = None
    description: Optional[str] = None


class ShipmentResponse(BaseModel):
    id: str
    order_id: str
    carrier: str
    tracking_number: str
    status: str
    estimated_delivery: Optional[datetime] = None
    origin: str = ""
    destination: str = ""
    delivery_agent_id: Optional[str] = None
    created_at: Optional[datetime] = None
    events: List[dict] = []

    class Config:
        from_attributes = True


class DeliveryAgentCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    vehicle_type: Optional[str] = None
    service_zone: Optional[str] = None


class DeliveryAgentResponse(BaseModel):
    id: str
    name: str
    phone: str
    email: Optional[str] = None
    vehicle_type: Optional[str] = None
    service_zone: Optional[str] = None
    is_available: bool = True
    active_deliveries: int = 0
    rating: float = 0.0

    class Config:
        from_attributes = True


# --- 2. Vendor Dashboard ---
class VendorAnalyticsResponse(BaseModel):
    total_revenue: float = 0.0
    total_orders: int = 0
    total_products: int = 0
    total_customers: int = 0
    avg_order_value: float = 0.0
    conversion_rate: float = 0.0
    revenue_growth: float = 0.0
    period: str = "30d"


class VendorPayoutResponse(BaseModel):
    id: str
    amount: float
    status: str
    period_start: datetime
    period_end: datetime
    paid_at: Optional[datetime] = None
    transaction_reference: Optional[str] = None

    class Config:
        from_attributes = True


# --- 3. AI Shopping Assistant ---
class AIChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None


class AIChatResponse(BaseModel):
    message: str
    conversation_id: str
    suggestions: List[str] = []
    products: List[dict] = []


class AICompareRequest(BaseModel):
    product_ids: List[str]
    query: Optional[str] = None


# --- 4. Affiliate & Referral ---
class AffiliateCreate(BaseModel):
    user_id: str
    referral_code: Optional[str] = None


class AffiliateResponse(BaseModel):
    id: str
    user_id: str
    referral_code: str
    total_earnings: float = 0.0
    pending_earnings: float = 0.0
    total_referrals: int = 0
    status: str = "ACTIVE"

    class Config:
        from_attributes = True


class ReferralWithdrawRequest(BaseModel):
    amount: float
    payment_method: str = "wallet"


# --- 5. Wallet & Multi-Payment ---
class WalletFundRequest(BaseModel):
    amount: float
    provider: str = "paystack"


class WalletResponse(BaseModel):
    id: str
    user_id: str
    balance: float = 0.0
    pending_balance: float = 0.0
    currency: str = "NGN"

    class Config:
        from_attributes = True


class PaymentInitializeRequest(BaseModel):
    amount: float
    provider: str = "paystack"
    metadata: Optional[dict] = None


class PaymentVerifyRequest(BaseModel):
    reference: str
    provider: str = "paystack"


class EscrowCreateRequest(BaseModel):
    order_id: str
    amount: float
    release_on: Optional[str] = None


# --- 6. Cart Infrastructure ---
class CartSyncRequest(BaseModel):
    items: List[dict]
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class CartMergeRequest(BaseModel):
    session_id: str
    user_id: str


class CartRecoveryResponse(BaseModel):
    cart_id: str
    items: List[dict]
    total: float


# --- 7. AI Smart Search ---
class SmartSearchRequest(BaseModel):
    query: str
    filters: Optional[dict] = None
    page: int = 1
    page_size: int = 20
    personalized: bool = True


class SmartSearchResponse(BaseModel):
    results: List[dict]
    total: int
    suggestions: List[str] = []
    corrected_query: Optional[str] = None
    trending: List[str] = []


class SearchFeedbackRequest(BaseModel):
    query: str
    clicked_product_id: str
    position: int
    relevant: Optional[bool] = None


# --- 8. Review System ---
class ReviewMediaUpload(BaseModel):
    review_id: str
    media_type: str = "image"  # image | video
    url: str


class ReviewReactionRequest(BaseModel):
    review_id: str
    reaction: str  # like | helpful | funny | insightful


class ReviewReplyRequest(BaseModel):
    review_id: str
    content: str
    retailer_id: Optional[str] = None


class ReviewFilterParams(BaseModel):
    product_id: Optional[str] = None
    rating: Optional[int] = None
    verified_only: bool = False
    media_only: bool = False
    sort_by: str = "recent"  # recent | helpful | highest | lowest
    page: int = 1
    page_size: int = 10


# --- 9. Notification System ---
class NotificationPreferences(BaseModel):
    email_notifications: bool = True
    push_notifications: bool = True
    sms_notifications: bool = False
    order_updates: bool = True
    promotion_alerts: bool = False
    shipment_alerts: bool = True
    weekly_digest: bool = False


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: dict
    user_agent: Optional[str] = None


# --- 10. Enterprise Intelligence ---
class PredictiveAnalyticsResponse(BaseModel):
    revenue_forecast: List[dict] = []
    demand_forecast: List[dict] = []
    confidence_score: float = 0.0
    period: str = "30d"


class CohortAnalysisResponse(BaseModel):
    cohorts: List[dict] = []
    retention_rates: List[float] = []
    avg_lifetime_value: float = 0.0


class InsightResponse(BaseModel):
    insights: List[dict] = []
    generated_at: datetime = None
