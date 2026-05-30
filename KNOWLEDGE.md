# ForgeStore — Full Project Knowledge File

> **Generated:** May 30, 2026  
> **Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, Jinja2, Tailwind CSS v3, PostgreSQL/SQLite  
> **Repo:** Monorepo at `C:\Users\USER\Documents\forgestore`

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Directory Structure](#2-directory-structure)
3. [Configuration & Environment](#3-configuration--environment)
4. [Database Schema](#4-database-schema)
5. [Authentication & Security](#5-authentication--security)
6. [API Routes](#6-api-routes)
7. [Web Routes (Templates)](#7-web-routes-templates)
8. [Admin Routes & Templates](#8-admin-routes--templates)
9. [Frontend / UI](#9-frontend--ui)
10. [Email & Notifications](#10-email--notifications)
11. [Payment Integration](#11-payment-integration)
12. [AI / Auto-Generated Content](#12-ai--auto-generated-content)
13. [Testing](#13-testing)
14. [Deployment](#14-deployment)
15. [Scripts & Utilities](#15-scripts--utilities)
16. [Recent Fixes & Changelog](#16-recent-fixes--changelog)

---

## 1. Project Overview

ForgeStore is a full-featured e-commerce marketplace platform. It supports:

- **Multi-vendor / multi-retailer** product catalog
- **Shopping cart** (token-based, no login required)
- **Order management** with Paystack & Flutterwave payment gateways
- **Customer accounts** (signup, login, password reset)
- **Admin dashboard** with RBAC (5 admin roles)
- **Newsletter / broadcast campaigns** with email delivery
- **AI-generated product content** (descriptions, images via API)
- **Dark mode** UI with premium Tailwind theme
- **Responsive design** (mobile-first sidebar, glassmorphism)
- **Rate limiting** via SlowAPI

---

## 2. Directory Structure

```
forgestore/
├── backend/                          # Python FastAPI backend (primary codebase)
│   ├── app/                          # Application package
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI app factory, startup, CORS, rate limiter
│   │   ├── config.py                 # Settings model (env vars), cache helpers
│   │   ├── database.py               # SQLAlchemy engine/session (lazy init), Base
│   │   ├── models.py                 # All SQLAlchemy ORM models
│   │   ├── schemas.py                # Pydantic request/response schemas
│   │   ├── templates_shared.py       # Raw Jinja2 Environment renderer
│   │   ├── utils.py                  # utcnow() and other utilities
│   │   ├── auth.py                   # [SHIM] Re-exports from app.core.security
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   └── security.py           # JWT, password hashing, RBAC, dependencies
│   │   ├── routers/
│   │   │   ├── auth.py               # /api/auth/* (login, signup, logout, me)
│   │   │   ├── admin.py              # /admin/* (dashboard, CRUD pages)
│   │   │   ├── admin_api.py          # /api/admin/* (REST APIs for admin panel)
│   │   │   ├── web.py                # /shop/* (storefront pages)
│   │   │   ├── web_api.py            # /api/* (public storefront APIs)
│   │   │   ├── paystack_webhook.py   # /api/paystack/webhook
│   │   │   ├── flutterwave_webhook.py# /api/flutterwave/webhook
│   │   │   ├── api_admin_ext.py      # Extended admin APIs (shipments, notifications, analytics, affiliates, wallet, reviews)
│   │   │   ├── api_web_ext.py        # Extended web APIs (AI chat, smart search, wallet, referrals, tracking)
│   │   │   └── api_shipment.py       # Order tracking API
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── email_service.py      # SMTP + Brevo transactional email
│   │   │   ├── ai_service.py         # AI content generation + settings defs
│   │   │   ├── ai_chat_service.py    # AI shopping assistant chat
│   │   │   ├── payment_provider.py   # Abstract payment facade + Paystack/Flutterwave
│   │   │   ├── paystack_service.py   # Paystack API integration (legacy, used by webhook)
│   │   │   ├── wallet_service.py     # Wallet, escrow, split payments
│   │   │   ├── affiliate_service.py  # Affiliate/referral system
│   │   │   ├── analytics_service.py  # Commerce analytics, forecasting, fraud
│   │   │   ├── vendor_analytics_service.py # Vendor dashboard analytics
│   │   │   ├── search_service.py     # Smart search with personalization
│   │   │   ├── review_service.py     # Review moderation & sentiment
│   │   │   ├── shipment_service.py   # Shipment tracking & delivery
│   │   │   ├── notification_service.py # Push notifications
│   │   │   ├── notification_bus.py   # Notification event bus
│   │   │   └── cart_sync_service.py  # Cart persistence & recovery
│   │   ├── templates/
│   │   │   ├── base.html             # Global base template
│   │   │   ├── admin/                # Admin panel templates
│   │   │   └── web/                  # Storefront templates
│   │   └── static/
│   │       ├── css/
│   │       └── img/
│   ├── tests/
│   │   ├── conftest.py               # Pytest fixtures, temp SQLite DB
│   │   ├── test_*.py                 # Various test files
│   │   └── test_forgestore.db        # Temp test database (auto-created)
│   ├── seed.py                       # Database seed script (demo data)
│   ├── seed_settings.py              # Settings seed script
│   ├── requirements.txt              # Python dependencies
│   ├── tailwind.config.js            # Tailwind CSS configuration
│   ├── Dockerfile                    # Production Docker image
│   ├── gunicorn_config.py            # Gunicorn production config
│   ├── Procfile                      # Render.com process definition
│   ├── start.sh                      # Unix dev start script
│   ├── start.bat                     # Windows dev start script
│   ├── .env.example                  # Template for environment variables
│   └── forgestore.db                 # SQLite development database
├── render.yaml                       # Render Blueprint (infra-as-code)
├── package.json                      # Root package.json (Turborepo)
├── turbo.json                        # Turborepo config
├── KNOWLEDGE.md                      # This file — full project knowledge base
├── README.md
└── .gitignore
```

---

## 3. Configuration & Environment

### Settings Model (`backend/app/config.py`)

| Field | Default | Env Var | Description |
|---|---|---|---|
| `database_url` | `sqlite:///./forgestore.db` | `DATABASE_URL` | SQLite (dev) or PostgreSQL (production) |
| `secret_key` | `change-this-to-...` | `SECRET_KEY` | JWT signing key |
| `algorithm` | `HS256` | `ALGORITHM` | JWT algorithm |
| `access_token_expire_minutes` | `1440` (24h) | `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime |
| `smtp_host` | `""` | `SMTP_HOST` | SMTP server host |
| `smtp_port` | `587` | `SMTP_PORT` | SMTP server port |
| `smtp_user` | `""` | `SMTP_USER` | SMTP username |
| `smtp_password` | `""` | `SMTP_PASSWORD` | SMTP password |
| `from_email` | `noreply@forgestore.com` | `FROM_EMAIL` | Sender email |
| `site_name` | `ForgeStore` | `SITE_NAME` | Brand name |
| `site_tagline` | `Your One-Stop Marketplace` | `SITE_TAGLINE` | Tagline |
| `site_base_url` | `http://127.0.0.1:8000` | `SITE_BASE_URL` | Public URL (used in emails) |
| `brevo_api_key` | `""` | `BREVO_API_KEY` | Brevo API v3 key |
| `paystack_secret_key` | `""` | `PAYSTACK_SECRET_KEY` | Paystack secret key |
| `paystack_public_key` | `""` | `PAYSTACK_PUBLIC_KEY` | Paystack public key |
| `flutterwave_secret_key` | `""` | `FLUTTERWAVE_SECRET_KEY` | Flutterwave secret key |
| `flutterwave_public_key` | `""` | `FLUTTERWAVE_PUBLIC_KEY` | Flutterwave public key |
| `flutterwave_encryption_key` | `""` | `FLUTTERWAVE_ENCRYPTION_KEY` | Flutterwave encryption key (also used as webhook verif-hash) |
| `default_payment_provider` | `"paystack"` | `DEFAULT_PAYMENT_PROVIDER` | `"paystack"` or `"flutterwave"` |
| `debug` | `False` | `DEBUG` | Debug mode |
| `secure_cookies` | `False` | `SECURE_COOKIES` | Set `secure=True` on cookies (HTTPS) |
| `cors_origins` | `http://127.0.0.1:8000,http://localhost:8000` | `CORS_ORIGINS` | Comma-separated CORS origins |

### `utcnow()` Utility (`backend/app/utils.py`)

- Returns a **naive** UTC datetime (no `tzinfo`), compatible with SQLAlchemy default `DateTime` columns
- Replaces deprecated `datetime.utcnow()` without triggering deprecation warnings
- Implementation: `datetime.now(timezone.utc).replace(tzinfo=None)`

### Settings Cache

- **`get_site_settings(db)`** — Returns all DB site settings as a flat dict, cached with thread lock
- **`invalidate_settings_cache()`** — Clear on settings update
- **`get_categorized_settings(db)`** — Returns settings organized by category (from `SETTINGS_DEFINITIONS` in `ai_service.py`)

### Environment File

`.env` lives at `backend/.env`. See `backend/.env.example` for full template.

---

## 4. Database Schema

All models in `backend/app/models.py`. Uses SQLAlchemy 2.0 `DeclarativeBase` (defined in `database.py`).

### Enums

| Enum | Values |
|---|---|
| `OrderStatus` | PENDING, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED |
| `AdminRole` | DIR_ADMIN, MANAGEMENT, TECH_ADMIN, RETAILER, LOGISTICS |
| `SettingsCategory` | global, design, technical, optional, developer, logistics, other |

### Core Tables

| Table | Key Columns | Relationships |
|---|---|---|
| **retailer** | id (UUID), name, slug (unique), bio, logo_url, status, rating, bank_name, account_number, bank_code, account_name, paystack_subaccount_code, flutterwave_subaccount_id, commission_rate (default 10.0) | → products, ad_campaigns |
| **category** | id (UUID), name (unique), slug (unique), description, image | → products |
| **product** | id (UUID), slug (unique), name, price, discount_price, images (JSON), category_id (FK), retailer_id (FK), inventory, specifications (JSON), rating | → category, retailer, order_items, reviews |
| **user** (customer) | id (UUID), email (unique), name, password (hashed) | → orders, reviews |
| **order** | id (UUID), order_number (unique), status (OrderStatus enum), total_amount, shipping_address (JSON), customer_id (FK) | → customer (User), items (OrderItem) |
| **order_item** | id (UUID), quantity, price, product_id (FK), order_id (FK) | → product, order |
| **review** | id (UUID), product_id (FK), user_id (FK), author, rating, title, content | → product, user |
| **admin_user** | id (UUID), email (unique), password, name, role (AdminRole enum) | (standalone admin auth) |

### Enterprise System Tables

| System | Tables |
|---|---|
| **Admin Notification** | admin_notification |
| **Advertising Campaigns** | ad_campaign (id, retailer_id, product_id, ad_type SHOP/PRODUCT, status PENDING/PAID/ACTIVE/EXPIRED, banner_url, payment_reference, clicks, impressions, dates) |
| **Newsletter** | newsletter_subscriber, broadcast_campaign, broadcast_event, broadcast_template |
| **Settings** | settings |
| **Real-time Order Tracking** | shipment, shipment_event, delivery_agent, delivery_location_log |
| **Vendor Dashboard** | vendor_analytics, vendor_payout, vendor_activity_log, vendor_performance_cache |
| **AI Shopping Assistant** | ai_conversation, ai_message, user_preference_vector, recommendation_cache |
| **Affiliate & Referral** | affiliate, affiliate_commission, referral_event, affiliate_payout |
| **Multi-Payment & Wallet** | wallet, wallet_transaction, payment_provider, payment_log, escrow_transaction, payment_split |
| **Advanced Cart** | persistent_cart, cart_activity, abandoned_cart, cart_recommendation |
| **AI Smart Search** | search_history, search_trend, search_embedding, search_click_analytics |
| **Modern Review System** | review_media, review_reaction, review_sentiment, review_moderation |
| **Notification Infrastructure** | notification_queue, push_subscription, user_notification_preferences, notification_delivery_log |
| **Enterprise Commerce Intelligence** | analytics_snapshot, customer_lifetime_value, fraud_detection_event, predictive_forecast |
| **Chat & Moderation** | product_chat_message (image_url, is_flagged, is_hidden), chat_moderation |
| **Promotional Ads** | promo_ad (6 subtypes: PROMO, FLASH_SALE, SUPER_SALE, HOT_WEEK, FESTIVAL, SEASONAL_SALE; 3 banner types: banner, poster, flyer) |

### Database Initialization

In `backend/app/database.py`:

- Engine and SessionLocal are **lazily initialized** (PEP 562 `__getattr__`) — prevents import-time crashes
- `get_db()` — FastAPI dependency yielding a session per request
- `init_db()` — Creates all tables at startup
- SQLite: `PRAGMA foreign_keys=ON` enabled on connect
- `postgres://` URLs are auto-normalized to `postgresql://`

### Migrations (`backend/migrations/`)

Run individually: `python -m migrations.run_migration 006`  
Or all pending: `python -m migrations.run_migration`

| Migration | Description |
|---|---|
| 001 | Add retailer bank fields |
| 002 | Extend ad campaign columns |
| 003 | Add order_earning and promo_ad tables |
| 004 | Add ad campaign columns (ad_subtype, banner_type, admin_id, note) |
| 005 | Create product_chat_message table |
| 006 | Add image_url/is_flagged/is_hidden to chat; create chat_moderation table |

---

## 5. Authentication & Security

### Architecture

Core logic lives in `backend/app/core/security.py`. `backend/app/auth.py` is a backward-compatible re-export shim.

### Password Hashing

- Library: `passlib[bcrypt]==1.7.4`
- Functions: `hash_password(plain)` → hashed string, `verify_password(plain, hashed)` → bool

### JWT Tokens

- Library: `python-jose[cryptography]==3.3.0`
- Functions: `create_access_token(data: dict, expires_delta=None)` → JWT string, `decode_token(token: str)` → payload dict
- Payload includes: `sub` (user ID), `email`, `role`, `exp` (expiration)
- Signed with `SECRET_KEY` from env

### Cookie Management

```python
set_auth_cookie(response, token, cookie_name="access_token", max_age_days=30)
delete_auth_cookie(response, cookie_name="access_token")
```

Cookie settings: `httponly=True, samesite="lax", secure=settings.secure_cookies, max_age=max_age_days * 86400`

### FastAPI Dependencies

| Dependency | Description |
|---|---|
| `get_current_admin(request, credentials, db)` | Checks Bearer header first, then `access_token` cookie, returns `AdminUser` or raises 401 |
| `get_current_user_from_cookie(request, db)` | Reads `access_token` cookie only, returns `Optional[AdminUser]` |
| `get_current_customer_from_cookie(request, db)` | Reads `customer_token` cookie only, returns `Optional[User]` |
| `get_current_user(request, db)` | Unified — tries admin cookie first, then customer cookie, raises 401 if neither |
| `get_current_user_optional(request, db)` | Same as above but returns `None` instead of raising |

### RBAC (Role-Based Access Control)

```python
ROLE_PERMISSIONS = {
    "manage_products":     [DIR_ADMIN, TECH_ADMIN, RETAILER],
    "manage_categories":   [DIR_ADMIN, TECH_ADMIN],
    "manage_retailers":    [DIR_ADMIN, MANAGEMENT],
    "manage_orders":       [DIR_ADMIN, MANAGEMENT, RETAILER, LOGISTICS],
    "manage_admin_users":  [DIR_ADMIN, MANAGEMENT],
    "view_analytics":      [DIR_ADMIN, MANAGEMENT, TECH_ADMIN],
    "send_broadcasts":     [DIR_ADMIN, MANAGEMENT],
    "manage_settings":     [DIR_ADMIN, TECH_ADMIN],
}
```

- `has_permission(admin, permission)` — checks if admin's role has a permission
- `require_role(*permissions)` — returns a FastAPI dependency that checks multiple permissions

### Audit Logging

`log_admin_action(db, admin, action, resource_type=None, resource_id=None, details=None, ip_address=None)` — logs to `admin_audit_log` table.

---

## 6. API Routes

### Auth Router (`/api/auth`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | Validates email/password, sets `access_token` cookie, returns JSON |
| POST | `/api/auth/signup` | Creates customer account, sets `customer_token` cookie |
| POST | `/api/auth/logout` | Deletes both `access_token` and `customer_token` cookies |
| GET | `/api/auth/me` | Returns authenticated user info (uses unified `get_current_user`) |

### Admin API Router (`/api/admin`)

Comprehensive REST API for admin panel operations — products CRUD, categories, retailers, orders, analytics, customers, admin users, settings, file upload, newsletter/broadcast management.

**Banking & Advertising Endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | `/api/admin/retailer/bank-setup` | Resolves bank account name via Paystack, creates gateway subaccount, persists bank details + subaccount token to retailer record |
| POST | `/api/admin/ads/initialize` | Creates a PENDING AdCampaign, initializes payment via the active gateway, returns authorization URL |
| POST | `/api/admin/ads/approve/{id}` | DIR_ADMIN/MANAGEMENT only — transitions campaign from PAID to ACTIVE |
| POST | `/api/admin/ads/banner/{id}` | Image upload for campaign banner |
| GET | `/api/admin/ads/analytics` | Returns campaign analytics: overview stats (total/active campaigns, clicks, impressions, CTR), type breakdown, status distribution, top 10 retailers with CTR, 6-month monthly trend |

### Web/Storefront API Router (`/api`)

Public APIs for products, categories, retailers, cart, checkout, payments intialize/verify, wishlist, search, AI recommendations, newsletter subscription, password reset.

**Product Chat API:**

| Method | Path | Description |
|---|---|---|
| GET | `/api/products/{product_id}/chat` | Get chat messages (excludes hidden, includes image_url, is_flagged) |
| POST | `/api/products/{product_id}/chat` | Post message (JSON or multipart with image upload, 5MB max, rate-limited 20/min) |

### Paystack Webhook (`/api/paystack/webhook`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/paystack/webhook` | Receives Paystack `charge.success` callbacks — verifies HMAC-SHA512 signature, marks order PAID, decrements inventory, sends email |
| GET | `/api/payments/verify/{reference}` | Verifies payment status by reference (order number), updates order if confirmed |

### Flutterwave Webhook (`/api/flutterwave/webhook`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/flutterwave/webhook` | Receives Flutterwave `charge.completed` or `transfer.completed` callbacks — verifies `verif-hash` header, marks order PAID, decrements inventory, sends email |

### Other

| Method | Path | Description |
|---|---|---|
| GET | `/` | Redirects to `/shop` or `/admin/dashboard` if admin logged in |
| GET | `/health` | Health check (returns `{"status": "ok", "version": "1.0.0"}`) |
| GET | `/api/debug/ip` | Detects server's public outbound IP (for Brevo SMTP authorization) |

---

## 7. Web Routes (Templates)

All storefront routes in `backend/app/routers/web.py`.

| Method | Path | Template | Description |
|---|---|---|---|
| GET | `/shop` | `web/index.html` | Storefront homepage (hero, featured, categories) |
| GET | `/shop/products/{slug}` | `web/product.html` | Product detail page |
| GET | `/shop/cart` | `web/cart.html` | Shopping cart |
| GET | `/shop/checkout` | `web/checkout.html` | Checkout form |
| GET | `/shop/order-success` | `web/order-success.html` | Order confirmation |
| GET | `/shop/category/{slug}` | `web/category.html` | Category listing |
| GET | `/shop/retailer/{slug}` | `web/retailer.html` | Retailer page |
| GET | `/shop/wishlist` | `web/wishlist.html` | Wishlist |
| GET | `/shop/search` | `web/search.html` | Search results |
| GET | `/login` | `web/login.html` | Customer login |
| GET | `/signup` | `web/signup.html` | Customer signup |
| GET | `/forgot-password` | `web/forgot-password.html` | Password reset form |

### Template Context Variables

All page renders receive these global variables via `_render_page()`:
- `request` — FastAPI Request
- `settings` — Site settings dict (from DB)
- `user` — Current customer (or None)
- `categories` — All categories
- `paystack_public_key` — From env
- `flutterwave_public_key` — From env
- `default_payment_provider` — Either `"paystack"` or `"flutterwave"` (defaults to `"paystack"`)
- `active_ads` — List of active AdCampaigns (queried on homepage & marketplace) — visible to ALL visitors including guests

### Guest Visitor Ad Banners

The homepage and marketplace routes use `_get_current_customer()` instead of `_require_customer()`, so guest visitors can browse and see ad banners without logging in.

### Ad Impression Tracking

Impression tracking is handled **asynchronously** via FastAPI's `BackgroundTasks` to avoid blocking page load:

- **Function:** `log_ad_impressions_background(ad_ids: list[str])` in `web.py` — opens its own `SessionLocal()` session (avoids holding the request session), performs bulk `UPDATE` using `db.query(...).update(...)`, with proper `rollback()` on error and `close()` in `finally`.
- **Routes:** Both `homepage` and `marketplace` inject `background_tasks: BackgroundTasks` and call `background_tasks.add_task(log_ad_impressions_background, [ad.id for ad in active_ads])`.
- **Benefit:** HTML context renders instantly for the user; impression counts update out-of-band. Prevents row-locking / `database is locked` errors in high-traffic or SQLite environments.

### Ad Banner Display

- **Homepage (index.html):** Up to 3 active ad banners displayed in a glassmorphic carousel row below the hero section. Each shows banner image, overlay with shop/product name, and CTA link.
- **Marketplace (marketplace.html):** Active ads displayed as square glassmorphic cards in a 3-column grid above the product listing. Hover effects with gradient overlays.
- **Chronological expiration enforced:** Both queries include `AdCampaign.end_date > utcnow()` alongside `status == "ACTIVE"` — manually approved ads stop appearing once their `end_date` passes, even if their status wasn't updated to `EXPIRED`.

### Template Rendering

Uses raw Jinja2 `Environment` (not Starlette's `Jinja2Templates` to avoid compatibility issues with Starlette 1.0.0):

```python
from app.templates_shared import render_template
return render_template("admin/dashboard.html", {"admin": admin, ...})
```

---

## 8. Admin Routes & Templates

All admin page routes in `backend/app/routers/admin.py`.

Provides full CRUD interfaces for: dashboard analytics, products, categories, retailers, orders, customers, admin users, settings, newsletter/broadcast, retail banking, ad campaigns, ad management, ad analytics, and admin profile management.

**Banking & Advertising Routes:**

| Method | Path | Template | Description |
|---|---|---|---|
| GET | `/admin/retailer/banking` | `admin/retailers/banking.html` | Bank setup UI — form to set account number, bank code, bank name; fetches live bank list from Paystack API; displays current bank details |
| GET | `/admin/retailer/ads` | `admin/retailers/ads.html` | Ad purchase UI — lists existing campaigns, purchase form with ad type (SHOP/₦10K/mo or PRODUCT/₦5K/mo), duration selector, checkout button. Also includes Promotional Ads section with 6 quick-create cards (Flash Sale, Hot Week, Festival, Seasonal, Super Sale, General) and promo ad grid |
| GET | `/admin/ads/manage` | `admin/ads/manage.html` | Campaign management UI — lists all campaigns with status, filters (ALL/PENDING/PAID/ACTIVE/EXPIRED), approve action button, pending/active counts |
| GET | `/admin/ads/analytics` | `admin/ads/analytics.html` | Analytics dashboard — overview stats cards (total campaigns, active, impressions, CTR), status distribution bar, ad type breakdown, monthly trend chart, top 10 retailers table with color-coded CTR |
| GET | `/admin/ads/settings` | `admin/ads/settings.html` | Ads Pricing & Provider settings — ad provider selector (Internal/Google/Meta), campaign pricing editor, promotional ads pricing editor (per-day rates), general settings (auto-approve, max duration, min budget, promo type toggles) |

**Chat Moderation Route:**

| Method | Path | Template | Description |
|---|---|---|---|
| GET | `/admin/chat-moderation` | `admin/chat-moderation.html` | Chat moderation panel — lists product chat messages with flag/hidden status, stats (total/flagged/hidden/pending), filter by status, actions: flag, hide, unhide, delete |

**Sidebar Navigation:**
- **Banking** link under retailer management section (payout icon)
- **Ad Campaigns** expandable section with **Manage** + **Analytics** sub-links (matching Newsletter pattern)
- **Ads Pricing** link under System section (for ad pricing & provider settings)
- **Chat Moderation** link under Community section (for moderating product chat messages)

Admin templates use a collapsible sidebar (w-80/w-72), top header, search overlay, dark mode toggle.

---

## 9. Frontend / UI

### Tailwind CSS

- **Config:** `backend/tailwind.config.js`
- **Source:** `backend/app/static/css/input.css`
- **Build:** `npx tailwindcss -i app/static/css/input.css -o app/static/css/output.css --content "app/templates/**/*.html"`
- **Dark mode:** `class` strategy (toggle via JS in admin base.html)

### Design System (Custom CSS Components in `input.css`)

**Glassmorphism:** `.glass`, `.glass-strong`, `.glass-dark` — semi-transparent with backdrop-blur
**Buttons:** `.btn-forge`, `.btn-outline`, `.btn-ghost`, `.btn-amber`, `.btn-glass`
**Cards:** `.card-artisan`, `.card-product`, `.card-stat`, `.card-glass`
**Badges:** `.badge`, `.badge-amber`, `.badge-emerald`, `.badge-blue`, `.badge-red`, `.badge-stone`, `.badge-glass`
**Form Inputs:** `.input-forge`, `.select-forge`
**Layout Helpers:** `.dots-pattern`, `.bg-grid`, `.grain-overlay`, `.section-divider`
**Animations:** `.reveal`, `.reveal-left`, `.reveal-right`, `.blob-morph`, `.skeleton-shimmer`

**Z-Index System:** CSS custom properties (`--z-sticky: 10` through `--z-toast: 100`)

---

## 10. Email & Notifications

### Email Service (`backend/app/services/email_service.py`)

- **Primary:** Brevo API v3 (`BREVO_API_KEY` env var)
- **Fallback:** SMTP (configurable via env vars)
- **Fallback fallback:** Logs to console if neither configured

### Sending Emails

Functions:
- `send_email(to_email, subject, html_content)` — Low-level send
- `send_order_status_email(to_email, order_number, customer_name, status)` — Order status notifications
- `send_password_reset_email(to_email, reset_link, customer_name)` — Password reset
- `send_broadcast_campaign(subscriber_email, subject, html_content, campaign_id, subscriber_id)` — Newsletter broadcasts

### Admin Notifications

- Stored in `admin_notification` table
- Created on: payment received (via Paystack or Flutterwave webhook), new order, low inventory, etc.
- Displayed in admin sidebar as a bell icon with count

### Newsletter / Broadcast System

- **Subscribers:** `newsletter_subscriber` table with double opt-in (confirm token)
- **Campaigns:** `broadcast_campaign` with status tracking (scheduled → sending → sent)
- **Events:** `broadcast_event` per subscriber (sent, opened, clicked, unsubscribed)
- **Templates:** `broadcast_template` for reusable content

---

## 11. Payment Integration

### Architecture

ForgeStore supports two payment gateways: **Paystack** and **Flutterwave**, with a common abstraction layer.

### Payment Provider Abstraction (`backend/app/services/payment_provider.py`)

```python
class PaymentProvider(abc.ABC):
    def initialize_payment(email, amount, reference, callback_url, metadata, currency) -> dict
    def verify_payment(reference) -> dict
    def verify_webhook_signature(signature, body) -> bool
```
- **`PaystackProvider`** — Implementation for Paystack API v1, uses HMAC-SHA512 webhook verification
- **`FlutterwaveProvider`** — Implementation for Flutterwave v3 API, uses HMAC-SHA512 webhook verification (for consistency in abstract interface; actual webhook uses `verif-hash` static token comparison)
- **Factory:** `get_payment_provider(provider="paystack")` — returns configured instance from env vars

### Split Payments & Subaccount Creation

Both Paystack and Flutterwave support **split payments** where each purchase is split between the marketplace and the vendor/retailer.

- **`PaymentProvider.create_subaccount(business_name, bank_code, account_number) -> str`** — Creates a subaccount on the payment gateway for a retailer. Returns the subaccount token/ID. Implemented for Paystack (POST `/subaccount`) and Flutterwave (POST `/v3/subaccounts`). The CryptoProvider returns a stub placeholder.
- **`PaymentProvider.initialize_payment(...)` now accepts `split_config`** — an optional dict with `type: "percentage"` or `"flat"`, `bearer_type: "subaccount"`, `subaccount` (subaccount code), and `transaction_charge`. This allows the marketplace commission to be automatically deducted during payment.
- **Split flow:** During checkout, the system calculates the vendor split as `total_amount - (total_amount * commission_rate / 100)`. The marketplace commission is deducted automatically by the payment gateway and deposited into the marketplace's main account. The retailer's share is settled to their subaccount.

### Paystack (`backend/app/services/paystack_service.py`)

- **`initialize_payment(email, amount, order_id, callback_url, metadata)`** — Creates Paystack transaction
  - Returns: `{ success, authorization_url, access_code, reference }`
- **`verify_payment(reference)`** — Verifies transaction status
  - Returns: `{ success, paid, status, amount, currency, gateway_response }`
- **`verify_webhook_signature(signature, body)`** — HMAC-SHA512 verification

#### Paystack Flow

1. Checkout → `POST /api/payments/initialize` → Paystack authorization URL
2. Customer pays → Paystack redirects to callback URL
3. Paystack sends `POST /api/paystack/webhook` with `charge.success` event
4. Webhook: verifies HMAC-SHA512 signature, marks order PAID, decrements inventory, sends admin notification + customer email
5. Frontend can also poll `GET /api/payments/verify/{reference}`

### Flutterwave

- **Implementation lives in `payment_provider.py`** (abstract class + `FlutterwaveProvider`)
- **Webhook endpoint:** `POST /api/flutterwave/webhook` in `flutterwave_webhook.py`

#### Flutterwave Webhook Verification

Flutterwave uses a **`verif-hash`** header mechanism (different from Paystack's HMAC). The flow is:

1. In your Flutterwave dashboard webhook settings, set a webhook hash
2. Flutterwave sends this hash as the `verif-hash` header with every webhook
3. The webhook compares the received `verif-hash` against `flutterwave_encryption_key` (shared secret)
4. This is a **static token comparison**, NOT an HMAC of the body

#### Flutterwave Flow

1. Checkout → `POST /api/payments/initialize` with provider="flutterwave" → Flutterwave payment link
2. Customer pays → Flutterwave redirects to callback URL
3. Flutterwave sends `POST /api/flutterwave/webhook` with `charge.completed` event
4. Webhook: verifies `verif-hash`, marks order PAID, decrements inventory, sends admin notification + customer email

### Selecting the Active Provider

The `default_payment_provider` setting (`"paystack"` or `"flutterwave"`) controls:
- Which public key is injected into template context
- Which provider the checkout flow uses when no specific provider is requested
- Can also be overridden per-request by passing `provider` parameter to `initialize_payment`

### Key Differences: Paystack vs Flutterwave

| Aspect | Paystack | Flutterwave |
|---|---|---|
| API Base | `https://api.paystack.co` | `https://api.flutterwave.com/v3` |
| Webhook Header | `x-paystack-signature` (HMAC-SHA512 of body) | `verif-hash` (static token comparison) |
| Amount Format | Integer in kobo (amount × 100) | Float in minor units |
| Transaction Ref | `reference` field | `tx_ref` field |
| Payment Flow | Authorization URL | Payment link (`data.link`) |
| Verify Endpoint | `/transaction/verify/{reference}` | `/transactions/by_reference/{reference}` |
| Status Values | `success` | `successful` |

---

## 12. AI / Auto-Generated Content

### AI Service (`backend/app/services/ai_service.py`)

- Provides AI-powered product content generation (descriptions, images)
- `SETTINGS_DEFINITIONS` — Master list of all site settings with categories, types, labels, descriptions
- `AIRecommendationEngine` — Generates product recommendations based on browsing/cart history

### Settings Categories

| Category | Examples |
|---|---|
| `global` | site_name, site_tagline, logo_url |
| `design` | primary_color, secondary_color, font_family |
| `technical` | max_upload_size, cache_ttl, api_rate_limit |
| `optional` | newsletter_popup_enabled, social_links |
| `developer` | debug_mode, log_level |
| `logistics` | shipping_fee, free_shipping_threshold, tax_rate |

---

## 13. Testing

### Test Setup (`backend/tests/`)

- **Framework:** pytest
- **Database:** Isolated file-based SQLite (auto-cleaned per test)
- **Client:** FastAPI `TestClient` with overridden DB dependency
- **Fixtures in `conftest.py`:**
  - `setup_db` — creates/drops tables per test
  - `db` — clean session
  - `client` — TestClient with dependency override
  - `sample_category`, `sample_retailer`, `sample_products` (2 items)
  - `sample_user`, `admin_user` (DIR_ADMIN role)

### Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

All **123 tests** currently pass (117 passed + 6 xfailed for external API keys).

---

## 14. Deployment

### Docker

- **Base image:** `python:3.13-slim`
- **Health check:** `GET /health` every 30s
- **Port:** `$PORT` (default 8080)
- **Startup:** `gunicorn -c gunicorn_config.py app.main:app || uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}`

### Gunicorn Config (`gunicorn_config.py`)

- **Workers:** `WEB_CONCURRENCY` env or `cpu_count * 2 + 1`
- **Worker class:** `uvicorn.workers.UvicornWorker`
- **Timeout:** 120s
- **Max requests per worker:** 1000 (+ 50 jitter, to prevent memory leaks)

### Render Deployment

- **Blueprint:** `render.yaml` — web service, starter plan, Oregon region
- **Docker context:** `./backend`
- **Health check path:** `/health`
- **Auto-deploy:** Triggered by pushing to `master` branch on GitHub

### Environment Variables for Production

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `SECRET_KEY` | ✅ | Generate with `secrets.token_urlsafe(64)` |
| `SITE_BASE_URL` | ✅ | Public URL of the site |
| `CORS_ORIGINS` | ✅ | Frontend URLs |
| `PAYSTACK_SECRET_KEY` | ❌ | From Paystack dashboard (required for Paystack) |
| `PAYSTACK_PUBLIC_KEY` | ❌ | From Paystack dashboard |
| `FLUTTERWAVE_SECRET_KEY` | ❌ | From Flutterwave dashboard (required for Flutterwave) |
| `FLUTTERWAVE_PUBLIC_KEY` | ❌ | From Flutterwave dashboard |
| `FLUTTERWAVE_ENCRYPTION_KEY` | ❌ | From Flutterwave dashboard; also used as webhook verif-hash |
| `DEFAULT_PAYMENT_PROVIDER` | ❌ | `"paystack"` or `"flutterwave"` (default: `"paystack"`) |
| `SMTP_HOST` | ❌ | For transactional emails (or use Brevo) |
| `SMTP_USER` | ❌ | |
| `SMTP_PASSWORD` | ❌ | |
| `FROM_EMAIL` | ❌ | |
| `BREVO_API_KEY` | ❌ | Alternative to SMTP |
| `DEBUG` | ❌ | Set `false` in production |
| `SECURE_COOKIES` | ❌ | Set `true` in production (HTTPS) |

### Sensitive Env Vars (set in Render dashboard, marked `sync: false` in render.yaml)

DATABASE_URL, SECRET_KEY, SITE_BASE_URL, CORS_ORIGINS, PAYSTACK_SECRET_KEY, PAYSTACK_PUBLIC_KEY, FLUTTERWAVE_SECRET_KEY, FLUTTERWAVE_PUBLIC_KEY, FLUTTERWAVE_ENCRYPTION_KEY, DEFAULT_PAYMENT_PROVIDER, SMTP_* vars, FROM_EMAIL

### Deployment Process

1. Push changes to `master` on GitHub
2. Render Blueprint auto-detects the push
3. Render builds the Docker image from `./backend/Dockerfile`
4. App starts with gunicorn + uvicorn workers
5. Health check at `/health` confirms availability

### Common Deployment Error: Missing Imports

If deployment fails with `NameError: name 'XXX' is not defined`, it's usually a missing import in a file. Fix by adding the missing import and redeploying.

---

## 15. Scripts & Utilities

### `backend/seed.py`

Seeds the database with demo data: admin user, sample categories, retailers, products, test customers, sample orders, reviews, site settings.
Run: `python seed.py`

### `backend/seed_settings.py`

Seeds/updates site settings from `SETTINGS_DEFINITIONS`. Creates new entries if missing.
Run: `python seed_settings.py`

### `backend/start.sh` (Unix)

1. Checks for `.env`
2. Installs dependencies
3. Seeds DB if `forgestore.db` doesn't exist
4. Starts uvicorn with hot reload on port 8080

### `backend/start.bat` (Windows)

1. Creates required directories
2. Installs dependencies
3. Seeds DB if `forgestore.db` doesn't exist
4. Starts uvicorn on port 8000

---

### Auth Page Redesign (login, signup, forgot-password, reset-password)

**Files Changed:**
- `backend/app/templates/web/login.html` — Complete redesign with split-screen layout (55% marketplace showcase / 45% auth form), social login buttons, hidden footer
- `backend/app/templates/web/signup.html` — Matching split-screen layout with 4 perk cards grid, password strength indicator, hidden footer
- `backend/app/templates/web/forgot-password.html` — Redesigned with split-screen layout, trust/security indicators, hidden footer
- `backend/app/templates/web/reset-password.html` — Redesigned with split-screen layout, 4 security tips grid, password strength indicator, hidden footer
- `backend/app/templates/web/base.html` — Footer wrapped in `{% block footer %}...{% endblock %}` to allow auth pages to hide it

**Design Features:**
- Left panel (desktop): Dark gradient with animated orbs, grid overlay, brand logo, hero headline, stats/perks, testimonial quotes
- Right panel: Clean white/dark form with social login buttons, password toggle, strength indicators
- Mobile: Logo + form only (left panel hidden)
- Full-viewport with negative margin to overlay header
- Consistent visual language across all 4 auth pages

### 2026-05-29: Full Marketplace & Account Redesign

**Scope:** Complete redesign of all remaining storefront and account templates to match the modern split-screen auth page aesthetic.

**Files Changed (15 templates):**

#### Homepage (`index.html`)
- Full-viewport hero with animated gradient background, floating orbs
- "Discover Artisan Crafts" headline with gradient text, CTA buttons
- Stats bar (500+ Artisans, 10K+ Products, 50K+ Happy Customers)
- 4-category grid with glass-effect cards
- "Why ForgeStore" section with 4 icon cards
- Featured products section with hover-lift cards
- Testimonial carousel with star ratings
- Newsletter CTA section

#### Marketplace & Listing Pages (marketplace, shops, shop-detail, product-detail)
- **marketplace.html:** Product grid with filter sidebar (category, price range, rating, sort), search bar, active filter badges, responsive 2-4 column grid
- **shops.html:** Retailer directory with card grid (logo, name, rating, product count, location), search/filter bar, empty state
- **shop-detail.html:** Shop header with banner/logo, stats row, bio, product grid, back button, empty state
- **product-detail.html:** Image gallery with thumbnails, product info section (price, rating, stock, specs), add-to-cart with quantity selector, related products, retailer card

#### Customer Journey (cart, checkout, success, wishlist)
- **cart.html:** Full-width cart page with item rows (image, name, price, quantity controls, subtotal), order summary sidebar, empty cart with shop CTA
- **checkout.html:** Two-column layout (form left, order summary right), contact info, shipping address, payment method cards (Paystack/Flutterwave), delivery notes
- **success.html:** Celebration layout with checkmark animation, order number, email confirmation note, continue shopping CTA
- **wishlist.html:** Product grid with remove button, empty state with heart icon and browse CTA

#### Utility Page (404)
- Animated gradient background, "Lost in the Workshop" headline
- Decorative spark/plus icon, home button, decorative floating orbs

#### Account Pages (dashboard, orders, order-detail, reviews, settings, wallet, referrals, tracking)
- **dashboard.html:** Sidebar navigation (9 links with icons), user profile card, recent orders table, quick stats row, quick actions grid
- **orders.html:** Order history list with status badges (emerald/amber/blue/red), order search, empty state
- **order-detail.html:** Status timeline (4-step: Placed→Paid→Shipped→Delivered), items list with product thumbnails, order summary card, shipping address card
- **reviews.html:** Star ratings, product images with fallback, empty state with write-review CTA
- **settings.html:** Profile name edit form, password change with strength indicator, danger zone section, quick links sidebar
- **wallet.html:** Balance display, fund wallet action, transaction history, quick stats (total deposited, spent, pending)
- **referrals.html:** Referral code display with copy button, 4-stat row, earnings history, how-it-works section, withdraw functionality
- **tracking.html:** Tracking number lookup form, recent orders list, tracking timeline result, error handling

**Design Language:**
- Consistent with auth pages: Stone + Amber palette, dark mode support
- Card-based layouts with `card-artisan` styling, hover-lift effects
- Glass morphism elements, gradient accents
- Responsive grid layouts (2-4 columns on desktop, stacked on mobile)
- Status badges with color coding (emerald=paid, amber=processing, blue=shipped, red=cancelled)
- Client-side API calls for wallet, referrals, tracking features
- All forms use `input-forge` styling with validation and feedback

### 2026-05-29: Flutterwave Integration & Webhook Setup

**Files Changed:**
- `backend/app/config.py` — Added `flutterwave_secret_key`, `flutterwave_public_key`, `flutterwave_encryption_key`, `default_payment_provider` fields + production validation warnings
- `backend/app/routers/flutterwave_webhook.py` — **New file:** Flutterwave webhook endpoint (`POST /api/flutterwave/webhook`)
  - Verifies `verif-hash` header (static token comparison using `flutterwave_encryption_key`)
  - Processes `charge.completed` and `transfer.completed` events
  - Marks order PAID, decrements inventory, sends admin notification + customer email
  - Falls back to order lookup by `tx_ref` (order_number) when `order_id` missing from metadata
- `backend/app/main.py` — Registered `flutterwave_webhook.router`
- `backend/app/routers/web.py` — Added `flutterwave_public_key` and `default_payment_provider` to template context
- `render.yaml` — Added FLUTTERWAVE_SECRET_KEY, FLUTTERWAVE_PUBLIC_KEY, FLUTTERWAVE_ENCRYPTION_KEY, DEFAULT_PAYMENT_PROVIDER env vars
- `backend/.env.example` — Added Flutterwave and default payment provider documentation
- `KNOWLEDGE.md` — This update

### 2026-05-27: Production Error Fixes (Deployed to Render)

**Commit `9013313`** — 5 files changed, 8 insertions, 11 deletions

**1. Fixed `utcnow()` offset-naive/aware crash**
- `backend/app/utils.py` — `utcnow()` was returning `datetime.now(timezone.utc)` (offset-aware), but SQLAlchemy `DateTime` columns store offset-naive datetimes. Every comparison between a DB value and `utcnow()` crashed with `TypeError: can't compare offset-naive and offset-aware datetimes`.
- **Fix:** `datetime.now(timezone.utc).replace(tzinfo=None)` — same UTC value, no deprecation warning, fully compatible with DB comparisons.
- **Affected endpoints:** Newsletter template (`sub.confirm_expires_at < now()`) and admin profile (`utcnow() - admin.created_at`)

**2. Fixed mangled `type()` artifacts from bulk script**
- `backend/app/routers/api_admin_ext.py:33` — `db.query(type("_", (), {}).__class__)` — removed (dead code, variable never used)
- `backend/app/tasks/notification_tasks.py:41` — `db.query(type("cls", (), {}).__class__)` — replaced with proper `db.query(NotificationQueue).filter(NotificationQueue.status == "PENDING")`

**3. Fixed dead code imports**
- `backend/app/tasks/analytics_tasks.py` — Removed unused `datetime`, `timedelta` imports
- `backend/app/tasks/cart_tasks.py` — Removed unused `timedelta` import

**At that time:** All 34 tests pass. ✅

### 2026-05-29: Auth Fix & Wallet/Referral/Tracking API Tests

**Files Changed:**
- `backend/app/routers/api_web_ext.py` — Fixed auth dependency for all wallet and referral endpoints:
  - Changed from `get_current_user_from_cookie` (reads admin-only `access_token` cookie) to `get_current_customer_from_cookie` (reads customer `customer_token` cookie)
  - Fixed `PaymentService.initialize_payment()` call: keyword arg `provider` → `provider_name` (correct param name)
- `backend/app/services/affiliate_service.py` — Added `get_affiliate_by_user_id(user_id)` method (was missing, only `get_affiliate_by_code` existed)
- `backend/tests/test_wallet_referral_tracking.py` — **New file:** 16 tests covering wallet, referral, and tracking API endpoints

**Test Coverage (16 new tests):**
- Wallet: balance (unauthenticated + authenticated), transactions (empty), fund (xfail for external API)
- Referral: create (unauthenticated + authenticated), stats (auto-create + after-create), earnings, history, withdraw (no earnings + unauthenticated)
- Tracking: non-existent order, non-existent tracking number, empty string handling

**50 / 52 tests pass** (2 xfailed — wallet fund requires PAYSTACK_SECRET_KEY for external Paystack API)

### 2026-05-29: Bulk Commission Migration — Async Impressions, Chronological Expiration & Code Audit

**Scope:** Performance optimization for ad impression tracking, chronological ad expiration enforcement, and service layer code audit.

**Files Changed:**

#### backend/app/routers/web.py

**STEP 1 — Asynchronous Ad Impression Tracking:**
- Added `from fastapi import ... BackgroundTasks` import
- Extracted impression tracking into `log_ad_impressions_background(ad_ids: list[str])` — opens its own DB session, performs bulk `db.query(...).update(...)` for efficient writes, handles `rollback()`/`close()`
- Homepage (`/shop`) and marketplace (`/shop/marketplace`) routes now accept `background_tasks: BackgroundTasks` param
- Inline `ad.impressions += 1; db.commit()` loop replaced with `background_tasks.add_task(log_ad_impressions_background, [ad.id for ad in active_ads])`
- **Benefit:** No blocking page load, no row-locking, no `database is locked` errors on SQLite

**STEP 2 — Chronological Ad Expiration:**
- Both active_ads queries now include `AdCampaign.end_date > utcnow()` alongside `status == "ACTIVE"`
- Expired ads are automatically hidden from the storefront even if their status wasn't updated to `EXPIRED`

**Cleanup:**
- Removed redundant lazy import of `AdCampaign` inside `log_ad_impressions_background` (already imported at module level)

#### Service Layer Audit (No Changes Needed)

**Circular imports:**
- `wallet_service.py` imports from `app.models` only
- `payment_provider.py` imports from `app.config` only
- No cross-imports between the two files → **No circular imports** ✅

**Duplicated `create_subaccount`:**
- `create_subaccount` exists ONLY in `wallet_service.py`'s `PaymentProviderInterface` and its implementations
- `payment_provider.py`'s `PaymentProvider` ABC does NOT have `create_subaccount`
- **No duplication** ✅

**Name collision (cosmetic — not a bug):**
- Both files define `PaystackProvider` and `FlutterwaveProvider` classes with different constructors and method signatures
- `wallet_service.py`: providers implement `PaymentProviderInterface` with `initialize_payment(amount, currency, reference, metadata, split_config)` — used by `PaymentService` for order/ad payment orchestration
- `payment_provider.py`: providers implement `PaymentProvider` (different ABC) with `initialize_payment(email, amount, reference, callback_url, metadata, currency)` — used by direct web routes for payment initialization
- These serve different layers of the system; names are intentionally distinct modules so no runtime collision occurs

---

### 2026-05-29: Retailer Payout Splits & Advertising Campaign System

**Scope:** Complete automated retailer payout split system + advertising campaign platform + full test suites.

**Files Changed (new + modified):**

#### Database
- `backend/app/models.py` — Added bank fields to `Retailer` (`bank_name`, `account_number`, `bank_code`, `account_name`, `paystack_subaccount_code`, `flutterwave_subaccount_id`, `commission_rate`). Created `AdCampaign` model with `id`, `retailer_id`, `product_id`, `ad_type` (SHOP/PRODUCT), `status` (PENDING→PAID→ACTIVE→EXPIRED), `banner_url`, `start_date`, `end_date`, `payment_reference` (unique), `clicks`, `impressions`.

#### Payment Service
- `backend/app/services/wallet_service.py` — Added `create_subaccount(business_name, bank_code, account_number)` to `PaymentProviderInterface`. Implemented for Paystack (POST `/subaccount`) and Flutterwave (POST `/v3/subaccounts`) with CryptoProvider stub. Updated `initialize_payment` to accept `split_config` parameter.

#### API Endpoints
- `backend/app/routers/admin_api.py` — Added `POST /api/admin/retailer/bank-setup` (resolves account name via Paystack API, creates subaccount, persists bank details). Added `POST /api/admin/ads/initialize` (creates PENDING campaign + payment link). Added `POST /api/admin/ads/approve/{id}` (DIR_ADMIN/MANAGEMENT only, PAID→ACTIVE). Added `POST /api/admin/ads/banner/{id}` (image upload). Added `GET /api/admin/ads/analytics` (overview stats, type breakdown, status distribution, top 10 retailers by CTR, 6-month monthly trend).

#### Webhooks
- `backend/app/routers/paystack_webhook.py` — Added AdCampaign detection: extracts `metadata.order_id`, falls back to campaign lookup by `reference`, transitions PENDING→PAID, creates admin notification.
- `backend/app/routers/flutterwave_webhook.py` — Same pattern: extracts `meta.order_id`, checks campaign by `tx_ref`, transitions PENDING→PAID, creates admin notification with provider attribution.

#### Admin Routes & Templates
- `backend/app/routers/admin.py` — Added routes for `/admin/retailer/banking` (bank setup UI with live bank list from Paystack API), `/admin/retailer/ads` (ad purchase UI with campaign listing + pricing), `/admin/ads/manage` (campaign approval/management), `/admin/ads/analytics` (analytics dashboard with async JS data load).
- `backend/app/templates/admin/retailers/banking.html` — **New:** Glassmorphic form with bank dropdown, account number input, bank code, current bank details display.
- `backend/app/templates/admin/retailers/ads.html` — **New:** Campaign list table, purchase form with ad type toggle/duration/checkout.
- `backend/app/templates/admin/ads/manage.html` — **New:** Campaign management with status filters, approve actions, pending counts.
- `backend/app/templates/admin/ads/analytics.html` — **New:** Analytics dashboard with stat cards, progress bars, bar chart, top retailers table with CTR color-coding, quick actions panel. Data loaded async via JS.
- `backend/app/templates/admin/base.html` — Added Banking (sidebar), Ad Campaigns expandable section with Manage + Analytics sub-links.

#### Storefront
- `backend/app/routers/web.py` — Homepage & marketplace routes changed from `_require_customer()` to `_get_current_customer()` (guests see ad banners without login). Queries active `AdCampaign` records. Impression tracking: increments `impressions` on each page load.
- `backend/app/templates/web/index.html` — Glassmorphic ad banner carousel (up to 3 ads) below hero section with gradient overlay, hover effects, linked shop/product cards.
- `backend/app/templates/web/marketplace.html` — Glassmorphic ad cards in 3-column grid above product listing with gradient overlay, hover-lift, and CTA buttons.

#### Test Suites
- `backend/tests/test_advertising.py` — **New:** 35 tests across 6 classes covering AdCampaign model (creation, relationships, status transitions, metrics, schema constraints), PaymentProvider interface (all 3 providers implement contract, split_config, factory), API endpoints (pricing, vendor validation, campaign listing), banking API, ad analytics, and banking model defaults.
- `backend/tests/test_payouts_and_ads.py` — **New:** 25 tests across 5 classes covering bank setup + subaccount provisioning (mocked _resolve_bank_account_name + create_subaccount with DB persistence verification), split payment calculation matrix (standard/custom/zero/rounding/multi-retailer), ad campaign initialization (PRODUCT/SHOP ads with mocked PaymentService, edge cases for missing data), Paystack webhook ad detection (PENDING→PAID transition with signature verification mock), Flutterwave webhook ad detection (PENDING→PAID with verif-hash mock, all event types).

**112 tests pass (106 passed + 6 xfailed)** (external API keys required for Paystack/Flutterwave integration tests)

---

### 2026-05-30: Chat Moderation System with Image Upload

**Scope:** Live product chat moderation with image support, admin moderation panel, and premium chat UI.

**Files Changed:**

#### Models & Migration
- `backend/app/models.py` — Extended `ProductChatMessage` with `image_url` (String 500), `is_flagged` (Boolean), `is_hidden` (Boolean). Created new `ChatModeration` model (message_id FK, status PENDING/APPROVED/REJECTED, reason, notes, reviewed_by FK, timestamps).
- `backend/migrations/006_chat_moderation.py` — **New:** ALTER TABLE for 3 new columns + CREATE TABLE for `chat_moderation` with indexes. Dual SQLite/PostgreSQL support.
- `backend/app/database.py` — Added `ProductChatMessage` and `ChatModeration` imports to `init_db()`.

#### API Changes
- `backend/app/routers/web_api.py` — `GET /api/products/{id}/chat` now filters hidden messages, returns `image_url` and `is_flagged`. `POST /api/products/{id}/chat` accepts multipart form with image upload (5MB max, stored in `static/uploads/chat/`), falls back to JSON body. WebSocket broadcasts include `image_url`.
- `backend/app/routers/admin_api.py` — Added `POST /api/admin/chat-moderate/{id}` for flag/hide/unhide/delete moderation actions with audit logging.

#### Templates
- `backend/app/templates/web/product-detail.html` — Replaced basic chat + reviews section with premium live chat UI: gradient send button, image attachment with preview/remove, connection status indicator, flagged message badges, image lightbox, empty state, hover timestamps.
- `backend/app/templates/admin/chat-moderation.html` — **New:** Admin moderation panel with stats (total/flagged/hidden/pending), filterable table, flag/hide/unhide/delete actions.
- `backend/app/templates/admin/sidebar.html` — Added "Chat Moderation" link under new "Community" section.

---

### 2026-05-30: Promotional Ads System with Pricing & Provider Settings

**Scope:** Full promotional ads system with 6 event types, per-day pricing, provider configuration, and admin settings page.

**Files Changed:**

#### Models
- `backend/app/models.py` — Extended `PromoAd.ad_subtype` to support 6 event types: `PROMO`, `FLASH_SALE`, `SUPER_SALE`, `HOT_WEEK`, `FESTIVAL`, `SEASONAL_SALE`. Added `PROMO_AD_SUBTYPES` dict with labels, icons, colors. Widened column from `String(20)` to `String(30)`.

#### API
- `backend/app/routers/admin_api.py` — Added `PROMO_PRICING` dict with per-day pricing for each promo type. Added `AD_PROVIDERS` dict (Internal, Google Ads, Meta Ads). Added `GET /api/admin/ads/settings` and `POST /api/admin/ads/settings` endpoints for full settings CRUD. Updated `create_promo_ad` to accept new subtypes.
- `backend/app/routers/admin.py` — Added `GET /admin/ads/settings` route for ads pricing & provider settings page. Updated `retailer_ads` route to fetch and pass `promo_ads` to template.

#### Templates
- `backend/app/templates/admin/ads/settings.html` — **New:** Ads Pricing & Provider settings page with ad provider selector (Internal/Google/Meta), campaign pricing editor, promotional ads pricing editor (per-day rates), general settings (auto-approve, max duration, min budget, promo type toggles).
- `backend/app/templates/admin/retailers/ads.html` — Added "Promotional Ads" section with 6 quick-create cards (Flash Sale, Hot Week, Festival, Seasonal, Super Sale, General), promo ad grid with status/type badges, create modal with event type, banner format (poster/flyer), dates.
- `backend/app/templates/admin/sidebar.html` — Added "Ads Pricing" link under System section.

## Key Architectural Decisions

1. **Templates use raw Jinja2 Environment** (not Starlette `Jinja2Templates`) to avoid compatibility issues with Starlette 1.0.0
2. **Database engine is lazily initialized** (PEP 562 `__getattr__`) to prevent import-time crashes when DB is unreachable
3. **Auth module refactored** into `app.core.security` with backward-compatible shim at `app.auth` — all existing import paths unchanged
4. **Cookies use unified helpers** (`set_auth_cookie`, `delete_auth_cookie`) with `secure_cookies` setting that defaults to `False` for local HTTP dev
5. **CORS** auto-includes `site_base_url` to prevent accidental misconfiguration
6. **Production validation** runs at startup (not debug mode) — logs warnings for misconfigured settings
7. **`utcnow()` returns naive datetime** — avoids offset-naive/aware comparison errors with SQLAlchemy `DateTime` columns while not triggering Python's `datetime.utcnow()` deprecation warning
8. **Payment providers use abstraction layer** — `payment_provider.py` defines a common interface, both Paystack and Flutterwave implement it, and the factory picks the right one from env config
9. **Flutterwave webhook uses `verif-hash` static comparison** — unlike Paystack's HMAC-SHA512, Flutterwave sends a pre-configured hash token that must match `flutterwave_encryption_key`
10. **Abandoned carts** cleaned up on startup (items older than 30 days)
