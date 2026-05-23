# 🔥 ForgeStore

A full-featured e-commerce platform built with **FastAPI** (Python) featuring a storefront, admin dashboard, payment integration with Paystack, and transactional email system.

## 🚀 Quick Start

```bash
# 1. Navigate to backend
cd backend

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
# Copy .env and fill in your settings (Paystack, SMTP, etc.)

# 4. Seed the database
python seed.py

# 5. Start the server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open **http://localhost:8000** in your browser.

## 🔑 Default Admin Login

| Email                 | Password   |
|-----------------------|------------|
| admin@forgestore.com  | admin123   |

## 🧭 Site Map

### Customer Storefront (`/shop`)
- **Home** — `/shop` — Product showcase with featured collections
- **Marketplace** — `/shop/marketplace` — Browse all products with search & filter
- **Product Detail** — `/shop/product/{slug}` — Product info, reviews, add to cart
- **Cart** — `/shop/cart` — Manage cart items, proceed to checkout
- **Checkout** — `/shop/checkout` — Pay with Paystack or Cash on Delivery
- **Sign Up** — `/shop/signup` — Create a customer account
- **Login** — `/shop/login` — Sign in as a customer
- **My Orders** — `/shop/account/orders` — View order history
- **Wishlist** — `/shop/wishlist` — Saved items

### Admin Panel (`/admin`)
- **Dashboard** — `/admin/dashboard` — Sales analytics & stats
- **Orders** — `/admin/orders` — Manage all orders (update status, delete)
- **Products** — `/admin/products` — CRUD for products
- **Categories** — `/admin/categories` — Manage categories
- **Customers** — `/admin/customers` — View registered users
- **Settings** — `/admin/settings` — Site configuration (AI, email, etc.)

## 💳 Payment Integration (Paystack)

Add your Paystack secret key to `.env`:

```env
PAYSTACK_SECRET_KEY=sk_live_xxxx
```

**Webhook URL** (set in Paystack Dashboard → Settings → Webhooks):
```
http://yourdomain.com/api/paystack/webhook
```

**Callback URL** (configured per-transaction, but set a fallback):
```
http://yourdomain.com/shop/checkout
```

## 📧 Email Configuration

For real transactional emails, add SMTP credentials to `.env`:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=noreply@yourdomain.com
```

Without SMTP, emails print to the console for development.

## 📦 Tech Stack

- **Framework**: FastAPI (Python)
- **Database**: SQLite (dev) / PostgreSQL (production)
- **Template Engine**: Jinja2 with Tailwind CSS
- **Auth**: JWT tokens with httpOnly cookies
- **Payments**: Paystack API
- **Rate Limiting**: slowapi

## 🌐 Deployment Checklist

1. [ ] Set `DATABASE_URL` to PostgreSQL in `.env`
2. [ ] Set `SECRET_KEY` to a strong random value
3. [ ] Set `SITE_BASE_URL` to your production domain
4. [ ] Add `PAYSTACK_SECRET_KEY`
5. [ ] Configure SMTP credentials
6. [ ] Set `app.main:app` behind a production server (gunicorn + uvicorn workers)
7. [ ] Configure Paystack webhook to point to your domain

## 📋 Tests

```bash
cd backend
python -m pytest tests/ -v
```
