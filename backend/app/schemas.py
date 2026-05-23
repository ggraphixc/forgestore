from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


# --- Auth ---
class LoginRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


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
    slug: str
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
    category_id: Optional[str] = None
    retailer_id: Optional[str] = None
    sub_category: Optional[str] = None
    inventory: Optional[int] = None
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
