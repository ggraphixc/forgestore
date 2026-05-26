# ForgeStore — Full Project Knowledge File

> **Generated:** May 26, 2026  
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
11. [Paystack Payment Integration](#11-paystack-payment-integration)
12. [AI / Auto-Generated Content](#12-ai--auto-generated-content)
13. [Testing](#13-testing)
14. [Deployment](#14-deployment)
15. [Scripts & Utilities](#15-scripts--utilities)

---

## 1. Project Overview

ForgeStore is a full-featured e-commerce marketplace platform. It supports:

- **Multi-vendor / multi-retailer** product catalog
- **Shopping cart** (token-based, no login required)
- **Order management** with Paystack payment gateway
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
│   │   │   └── paystack_webhook.py   # /api/paystack/webhook
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── email_service.py      # SMTP + Brevo transactional email
│   │   │   ├── ai_service.py         # AI content generation + settings defs
│   │   │   └── paystack_service.py   # Paystack API integration
│   │   ├── templates/
│   │   │   ├── base.html             # Global base template
│   │   │   ├── admin/                # Admin panel templates
│   │   │   │   ├── base.html         # Admin layout (sidebar, header, dark mode)
│   │   │   │   ├── login.html        # Admin login
│   │   │   │   ├── dashboard.html    # Analytics dashboard
│   │   │   │   └── me.html           # Admin profile page (view + edit)
│   │   │   └── web/                  # Storefront templates
│   │   │       ├── base.html         # Storefront layout
│   │   │       ├── index.html        # Homepage
│   │   │       ├── login.html        # Customer login
│   │   │       ├── signup.html       # Customer signup
│   │   │       └── reset-password.html
│   │   └── static/
│   │       ├── css/
│   │       │   ├── input.css         # Tailwind source + custom components
│   │       │   └── output.css        # Compiled Tailwind (gitignored usually)
│   │       └── img/
│   │           └── placeholder.svg
│   ├── tests/
│   │   ├── conftest.py               # Pytest fixtures, temp SQLite DB
│   │   ├── test_*.py                 # Various test files
│   │   ├── test_newsletter.py
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
| `debug` | `False` | `DEBUG` | Debug mode |
| `secure_cookies` | `False` | `SECURE_COOKIES` | Set `secure=True` on cookies (HTTPS) |
| `cors_origins` | `http://127.0.0.1:8000,http://localhost:8000` | `CORS_ORIGINS` | Comma-separated CORS origins |

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

### Tables

| Table | Key Columns | Relationships |
|---|---|---|
| **retailer** | id (UUID), name, slug (unique), bio, logo_url, banner_url, location, primary_color, status, rating, review_count, created_at, updated_at | → products: `Retailer.products` |
| **category** | id (UUID), name (unique), slug (unique), description, image, created_at, updated_at | → products: `Category.products` |
| **product** | id (UUID), slug (unique), name, brand, description, price, discount_price, images (JSON), category_id (FK), retailer_id (FK), sub_category, inventory, vendor_id, specifications (JSON), rating, review_count, is_new_arrival, is_flagship, created_at, updated_at | → category, retailer, order_items, reviews |
| **user** (customer) | id (UUID), email (unique), name, password (hashed, nullable OAuth), created_at, updated_at | → orders, reviews |
| **order** | id (UUID), order_number (unique), status (OrderStatus enum), total_amount, shipping_address (JSON), customer_id (FK), created_at, updated_at | → customer (User), items (OrderItem) |
| **order_item** | id (UUID), quantity, price, product_id (FK), order_id (FK), created_at, updated_at | → product, order |
| **review** | id (UUID), product_id (FK), user_id (FK nullable), author, rating, title, content, helpful, created_at, updated_at | → product, user |
| **admin_user** | id (UUID), email (unique), password, name, role (AdminRole enum), vendor_id (nullable), created_at | (standalone admin auth) |
| **wishlist_item** | id (UUID), token (indexed), product_id (FK), created_at | → product |
| **cart_item** | id (UUID), cart_token (indexed), product_id (FK), quantity, created_at | → product |
| **admin_audit_log** | id (UUID), admin_id (FK nullable), admin_email, action (indexed), resource_type, resource_id, details (Text), ip_address, created_at | (audit trail) |
| **password_reset_token** | id (UUID), user_id (FK), token (unique, indexed), used (bool), expires_at, created_at | (password reset flow) |
| **admin_notification** | id (UUID), type (indexed), title, message, link, read (bool), created_at | (in-app notifications) |
| **newsletter_subscriber** | id (UUID), email (unique), confirmed (bool), confirm_token, confirm_expires_at, unsubscribe_token, tags (JSON), preferences (JSON), created_at | → BroadcastEvent |
| **broadcast_campaign** | id (UUID), subject, content, tag_filter, status, scheduled_at, sent_at, total_recipients, sent_count, opened_count, clicked_count, unsubscribed_count, template_id (FK), created_by (FK), created_at, updated_at | → template (BroadcastTemplate) |
| **broadcast_event** | id (UUID), campaign_id (FK), subscriber_id (FK), event_type (sent/opened/clicked/unsubscribed/bounced), extra_data (JSON), timestamp | → campaign, subscriber |
| **broadcast_template** | id (UUID), name, subject, content, created_by (FK), created_at, updated_at | → campaigns |
| **settings** | id (UUID), key (unique), value (Text), category, setting_type, label, description, options (JSON), updated_at | (key-value store) |

### Database Initialization

In `backend/app/database.py`:

- Engine and SessionLocal are **lazily initialized** (PEP 562 `__getattr__`) — prevents import-time crashes
- `get_db()` — FastAPI dependency yielding a session per request
- `init_db()` — Creates all tables at startup
- SQLite: `PRAGMA foreign_keys=ON` enabled on connect
- `postgres://` URLs are auto-normalized to `postgresql://`

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

Comprehensive REST API for admin panel operations:

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/products` | List products (search, filter, paginate) |
| POST | `/api/admin/products` | Create product |
| GET | `/api/admin/products/{id}` | Get single product |
| PUT | `/api/admin/products/{id}` | Update product |
| DELETE | `/api/admin/products/{id}` | Delete product |
| GET | `/api/admin/categories` | List categories |
| POST | `/api/admin/categories` | Create category |
| PUT | `/api/admin/categories/{id}` | Update category |
| DELETE | `/api/admin/categories/{id}` | Delete category |
| GET | `/api/admin/retailers` | List retailers |
| POST | `/api/admin/retailers` | Create retailer |
| PUT | `/api/admin/retailers/{id}` | Update retailer |
| GET | `/api/admin/orders` | List orders |
| GET | `/api/admin/orders/{id}` | Get order detail |
| PUT | `/api/admin/orders/{id}/status` | Update order status |
| GET | `/api/admin/analytics` | Dashboard stats (revenue, counts, chart data) |
| GET | `/api/admin/analytics/sales` | Sales chart data |
| GET | `/api/admin/analytics/top-products` | Top products list |
| GET | `/api/admin/customers` | List customers |
| GET | `/api/admin/admin-users` | List admin users |
| POST | `/api/admin/admin-users` | Create admin user |
| PUT | `/api/admin/admin-users/{id}` | Update admin user |
| DELETE | `/api/admin/admin-users/{id}` | Delete admin user |
| GET | `/api/admin/settings` | Get all settings (categorized) |
| PUT | `/api/admin/settings` | Update settings |
| POST | `/api/admin/settings/regenerate` | Re-generate default settings |
| POST | `/api/admin/upload` | File upload endpoint |
| GET | `/api/admin/newsletter/subscribers` | List subscribers |
| GET | `/api/admin/newsletter/campaigns` | List campaigns |
| POST | `/api/admin/newsletter/campaigns` | Create/send campaign |
| GET | `/api/admin/newsletter/templates` | List templates |
| POST | `/api/admin/newsletter/templates` | Create template |
| GET | `/api/admin/broadcast/campaigns/{id}/stats` | Campaign analytics |
| GET | `/api/admin/profile` | Get admin profile |
| POST | `/api/admin/profile` | Update admin profile |

### Web/Storefront API Router (`/api`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/products` | Product listing (search, filter by category/retailer/sale, sort, paginate) |
| GET | `/api/products/{slug}` | Single product detail (includes retailer info) |
| GET | `/api/products/{slug}/reviews` | Product reviews |
| POST | `/api/products/{slug}/reviews` | Submit review |
| GET | `/api/categories` | All categories |
| GET | `/api/retailers` | All retailers |
| GET | `/api/cart` | Get cart contents (by cart_token cookie) |
| POST | `/api/cart/add` | Add item to cart |
| POST | `/api/cart/update` | Update cart item quantity |
| POST | `/api/cart/remove` | Remove item from cart |
| POST | `/api/checkout` | Create order (captures customer info) |
| POST | `/api/payments/initialize` | Initialize Paystack payment |
| GET | `/api/payments/verify/{reference}` | Verify payment status |
| GET | `/api/wishlist` | Get wishlist (by token cookie) |
| POST | `/api/wishlist/add` | Add to wishlist |
| POST | `/api/wishlist/remove` | Remove from wishlist |
| GET | `/api/new-arrivals` | New arrival products |
| GET | `/api/flagship` | Flagship products |
| GET | `/api/ai-recommendations` | AI-powered product recommendations |
| POST | `/api/newsletter/subscribe` | Subscribe to newsletter |
| GET | `/api/newsletter/confirm` | Confirm subscription |
| POST | `/api/auth/reset-password` | Request password reset |
| POST | `/api/auth/reset-password/confirm` | Reset password with token |
| GET | `/api/search` | Global search across products |

### Paystack Webhook (`/api`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/paystack/webhook` | Receives Paystack `charge.success` callbacks — marks order PAID, decrements inventory, sends email |
| GET | `/api/payments/verify/{reference}` | Verifies payment by order reference |

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
| GET | `/forgot-password` | `web/reset-password.html` | Password reset form |
| GET | `/shop/newsletter/confirm/{token}` | redirect | Confirms newsletter subscription |

### Web Templates (`backend/app/templates/web/`)

- **`base.html`** — Storefront layout: navbar, mobile menu, footer, cart count badge
- **`index.html`** — Hero section with gradient blobs, new arrivals grid, featured products, categories grid, newsletter CTA
- **`login.html`** — Glass card login form with decorative dots pattern
- **`signup.html`** — Glass card signup with password strength indicator
- **`reset-password.html`** — Password reset with strength indicator

### Template Rendering

Uses raw Jinja2 `Environment` (not Starlette's `Jinja2Templates` to avoid compatibility issues with Starlette 1.0.0):

```python
from app.templates_shared import render_template
return render_template("admin/dashboard.html", {"admin": admin, ...})
```

---

## 8. Admin Routes & Templates

All admin page routes in `backend/app/routers/admin.py`.

| Method | Path | Template | Description |
|---|---|---|---|
| GET | `/admin/login` | `admin/login.html` | Admin login page |
| POST | `/admin/login` | — | Redirects after login |
| GET | `/admin/dashboard` | `admin/dashboard.html` | Analytics dashboard (protected) |
| GET | `/admin/products` | `admin/products.html` | Product management |
| GET | `/admin/products/new` | `admin/product-new.html` | New product form |
| GET | `/admin/products/{id}/edit` | `admin/product-edit.html` | Edit product |
| GET | `/admin/categories` | `admin/categories.html` | Category management |
| GET | `/admin/categories/{id}/edit` | `admin/category-edit.html` | Edit category |
| GET | `/admin/retailers` | `admin/retailers.html` | Retailer management |
| GET | `/admin/retailers/{slug}` | `admin/retailer-detail.html` | Retailer detail |
| GET | `/admin/orders` | `admin/orders.html` | Order listing |
| GET | `/admin/orders/{id}` | `admin/order-detail.html` | Order detail |
| GET | `/admin/customers` | `admin/customers.html` | Customer listing |
| GET | `/admin/admin-users` | `admin/admin-users.html` | Admin user management |
| GET | `/admin/settings` | `admin/settings.html` | Site settings |
| GET | `/admin/newsletter` | `admin/newsletter.html` | Newsletter campaigns |
| GET | `/admin/newsletter/subscribers` | `admin/subscribers.html` | Subscriber list |
| GET | `/admin/me` | `admin/me.html` | Admin profile (view + edit name/password) |
| POST | `/admin/me` | — | Update profile (name, password) |

### Admin Templates (`backend/app/templates/admin/`)

- **`base.html`** — Admin layout: collapsible sidebar (w-80/w-72), top header, search overlay, dark mode toggle
- **`login.html`** — Clean login page
- **`dashboard.html`** — Stats cards (products, orders, revenue, customers), charts, recent orders
- **`me.html`** — Profile page: avatar card with gradient header, role badge, account age, account details table, permissions grid, edit form (name, password change)

### Sidebar Navigation Structure

```
├── Dashboard           /admin/dashboard
├── Catalog             /admin/products
├── Categories          /admin/categories
├── Retailers           /admin/retailers
├── Orders              /admin/orders
├── Customers           /admin/customers
├── Admin Users         /admin/admin-users
├── Settings            /admin/settings
├── Newsletter          /admin/newsletter
├── Profile (bottom)    /admin/me
└── Logout
```

Sidebar is collapsible to 72px width with smooth transition. On mobile, it overlays as `position: fixed`.

---

## 9. Frontend / UI

### Tailwind CSS

- **Config:** `backend/tailwind.config.js`
- **Source:** `backend/app/static/css/input.css`
- **Build:** `npx tailwindcss -i app/static/css/input.css -o app/static/css/output.css --content "app/templates/**/*.html"`
- **Dark mode:** `class` strategy (toggle via JS in admin base.html)

### Design System (Custom CSS Components in `input.css`)

**Glassmorphism:**
- `.glass` — semi-transparent white/stone with backdrop-blur
- `.glass-strong` — more opaque variant
- `.glass-dark` — dark glass variant

**Buttons:**
- `.btn-forge` — Primary action (stone-900 bg, amber-500 shadow)
- `.btn-outline` — Outlined variant
- `.btn-ghost` — Subtle text button
- `.btn-amber` — Amber call-to-action with glow
- `.btn-glass` — Glassmorphism button for dark backgrounds

**Cards:**
- `.card-artisan` — White/stone rounded card with hover effect
- `.card-product` — Product grid card with shadow elevation
- `.card-stat` — Statistics card for dashboard
- `.card-glass` — Glassmorphism card with hover glow

**Badges:** `.badge`, `.badge-amber`, `.badge-emerald`, `.badge-blue`, `.badge-red`, `.badge-stone`, `.badge-glass`

**Form Inputs:** `.input-forge`, `.select-forge`

**Layout Helpers:**
- `.section-divider` — Section separator with amber gradient line
- `.forge-divider` — Thin amber gradient divider
- `.dots-pattern` — Decorative dot background
- `.bg-grid` — Grid pattern background
- `.grain-overlay` — SVG noise grain overlay

**Animations:**
- `.reveal`, `.reveal-left`, `.reveal-right`, `.reveal-scale` — Scroll-triggered reveals (JS: IntersectionObserver)
- `.blob-morph` — Morphing blob shape for hero sections
- `.skeleton-shimmer` — Loading skeleton animation
- `@keyframes morph` — 8s blob animation
- `@keyframes shimmer` — 2s loading shimmer

**Password Strength:** `.pw-strength-bar`, `.pw-strength-text` — with `.weak`, `.medium`, `.strong` states

**Sidebar Collapse:** `.sidebar-collapsed` — shrinks sidebar to 72px, hides labels, centers icons. Smooth CSS transition.

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
- Created on: payment received, new order, low inventory, etc.
- Displayed in admin sidebar as a bell icon with count

### Newsletter / Broadcast System

- **Subscribers:** `newsletter_subscriber` table with double opt-in (confirm token)
- **Campaigns:** `broadcast_campaign` with status tracking (scheduled → sending → sent)
- **Events:** `broadcast_event` per subscriber (sent, opened, clicked, unsubscribed)
- **Templates:** `broadcast_template` for reusable content

---

## 11. Paystack Payment Integration

### Service (`backend/app/services/paystack_service.py`)

- **`initialize_payment(email, amount, order_id, callback_url, metadata)`** — Creates Paystack transaction
  - Returns: `{ success, authorization_url, access_code, reference }`
- **`verify_payment(reference)`** — Verifies transaction status
  - Returns: `{ success, paid, status, amount, currency, gateway_response }`
- **`verify_webhook_signature(signature, body)`** — HMAC-SHA512 verification
  - Uses `PAYSTACK_SECRET_KEY` to validate webhook authenticity

### Flow

1. Checkout → `POST /api/payments/initialize` → Paystack authorization URL
2. Customer pays → Paystack redirects to callback URL
3. Paystack sends `POST /api/paystack/webhook` with `charge.success` event
4. Webhook: verifies signature, marks order PAID, decrements inventory, sends admin notification + customer email
5. Frontend can also poll `GET /api/payments/verify/{reference}`

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

All 34 tests currently pass.

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
- **Sensitive env vars** (marked `sync: false` — must be set in Render dashboard): DATABASE_URL, SECRET_KEY, SITE_BASE_URL, CORS_ORIGINS, PAYSTACK_*, SMTP_*, FROM_EMAIL

### Environment Variables for Production

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `SECRET_KEY` | ✅ | Generate with `secrets.token_urlsafe(64)` |
| `SITE_BASE_URL` | ✅ | Public URL of the site |
| `CORS_ORIGINS` | ✅ | Frontend URLs |
| `PAYSTACK_SECRET_KEY` | ✅ | From Paystack dashboard |
| `PAYSTACK_PUBLIC_KEY` | ✅ | From Paystack dashboard |
| `SMTP_HOST` | ❌ | For transactional emails (or use Brevo) |
| `SMTP_USER` | ❌ | |
| `SMTP_PASSWORD` | ❌ | |
| `FROM_EMAIL` | ❌ | |
| `BREVO_API_KEY` | ❌ | Alternative to SMTP |
| `DEBUG` | ❌ | Set `false` in production |
| `SECURE_COOKIES` | ❌ | Set `true` in production (HTTPS) |

### Common Deployment Error: Missing Imports

If deployment fails with `NameError: name 'XXX' is not defined`, it's usually a missing import in a file. Fix by adding the missing import and redeploying.

---

## 15. Scripts & Utilities

### `backend/seed.py`

Seeds the database with demo data:
- Admin user (admin@forgestore.com / admin123)
- Sample categories, retailers, products
- Test customer users
- Sample orders and reviews
- Site settings
- Run: `python seed.py`

### `backend/seed_settings.py`

Seeds/updates site settings from `SETTINGS_DEFINITIONS`. Creates new columns on existing `settings` table if missing.
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

## Key Architectural Decisions

1. **Templates use raw Jinja2 Environment** (not Starlette `Jinja2Templates`) to avoid compatibility issues with Starlette 1.0.0
2. **Database engine is lazily initialized** (PEP 562 `__getattr__`) to prevent import-time crashes when DB is unreachable
3. **Auth module refactored** into `app.core.security` with backward-compatible shim at `app.auth` — all existing import paths unchanged
4. **Cookies use unified helpers** (`set_auth_cookie`, `delete_auth_cookie`) with `secure_cookies` setting that defaults to `False` for local HTTP dev
5. **CORS** auto-includes `site_base_url` to prevent accidental misconfiguration
6. **Production validation** runs at startup (not debug mode) — logs warnings for misconfigured settings
7. **Abandoned carts** cleaned up on startup (items older than 30 days)
8. **Sidebar** uses `fixed lg:relative` to fix mobile overflow (was conflicting `fixed` + `relative`)
9. **Password strength** is client-side JS (signup + reset-password forms)
