# ForgeStore

Full-stack e-commerce marketplace with AI-powered features, multi-vendor support, and logistics management.

## Tech Stack

- **Backend**: Python 3.14, FastAPI, SQLAlchemy, PostgreSQL (Neon), Redis
- **Frontend**: Jinja2 templates, Tailwind CSS, vanilla JavaScript
- **Payments**: Paystack
- **Storage**: Cloudinary (images), Redis (caching)
- **AI**: OpenAI GPT, OpenCode Zen (MiMo v2.5)
- **Notifications**: WhatsApp Business API, Email (SMTP), SMS
- **Deployment**: Render (Docker)

## Features

- Multi-vendor marketplace with vendor portal
- Admin dashboard with moderation, analytics, settings
- Logistics portal with driver management, route optimization, COD collection
- AI-powered product recommendations, chatbot, search, and content moderation
- Real-time notifications (WhatsApp, email, SMS)
- Dynamic pricing, coupon system, vendor promotions
- Product comparison, wishlist sharing, cookie consent
- Dark mode across all portals
- SEO optimization (meta tags, sitemap, JSON-LD)
- CDN support for static assets
- Redis caching for performance

## Project Structure

```
forgestore/
├── backend/
│   ├── app/
│   │   ├── models.py          # SQLAlchemy models (User, Product, Order, etc.)
│   │   ├── main.py            # FastAPI app, middleware, startup
│   │   ├── config.py          # Pydantic settings, env vars
│   │   ├── database.py        # DB session, migrations
│   │   ├── templates_shared.py # Jinja2 env, global context
│   │   ├── routers/
│   │   │   ├── web.py         # Public pages (homepage, marketplace, product detail)
│   │   │   ├── web_api.py     # Public API (cart, wishlist, compare, reviews)
│   │   │   ├── auth.py        # Authentication (signup, login, profile)
│   │   │   ├── admin.py       # Admin portal pages
│   │   │   ├── admin_api.py   # Admin API (settings, catalog, moderation)
│   │   │   ├── vendor_portal.py # Vendor portal pages
│   │   │   ├── vendor_api.py  # Vendor API (products, orders, analytics)
│   │   │   ├── logistics_portal.py # Logistics/driver portal
│   │   │   └── orders.py      # Order processing, webhooks
│   │   ├── services/
│   │   │   ├── ai_service.py   # AI chat, recommendations, moderation
│   │   │   ├── email_service.py # Email templates, sending
│   │   │   ├── notifications.py # WhatsApp, multi-channel notifications
│   │   │   ├── logistics_ai.py # Route optimization, demand forecasting
│   │   │   └── analytics_service.py # Vendor analytics
│   │   ├── core/
│   │   │   ├── cache.py       # Redis caching layer
│   │   │   ├── seo.py         # SEO helpers, sitemap, JSON-LD
│   │   │   ├── slug.py        # Auto-slug generation
│   │   │   ├── image_compressor.py # Image compression before upload
│   │   │   └── cloudinary_upload.py # Cloudinary integration
│   │   └── templates/         # Jinja2 templates (web, admin, vendor, logistics)
│   ├── tests/                 # pytest test suite
│   ├── requirements.txt
│   └── Dockerfile
├── render.yaml                # Render deployment config
└── README.md                  # This file
```

## Getting Started

### Prerequisites

- Python 3.14+
- PostgreSQL (or SQLite for development)
- Redis (optional - falls back to in-memory cache)
- Cloudinary account (for image storage)

### Local Development

```bash
# Clone the repo
git clone https://github.com/ggraphixc/forgestore.git
cd forgestore/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your DATABASE_URL, REDIS_URL, etc.

# Run migrations and start
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes (production) |
| `REDIS_URL` | Redis connection string | No (fallback: in-memory) |
| `SECRET_KEY` | JWT secret key | Yes |
| `PAYSTACK_SECRET_KEY` | Paystack payment integration | Yes |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name | No |
| `CLOUDINARY_API_KEY` | Cloudinary API key | No |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret | No |
| `OPENAI_API_KEY` | OpenAI API key for AI features | No |
| `WHATSAPP_ACCESS_TOKEN` | WhatsApp Business API token | No |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp phone number ID | No |
| `SECURE_COOKIES` | Set to `true` for HTTPS | Yes (production) |

## Deployment

Deployed on Render using Docker:

- `render.yaml` defines the service configuration
- `gunicorn` with `uvicorn` workers
- PostgreSQL on Neon (serverless)
- Redis for caching (optional)
- Cloudinary for image storage

## Testing

```bash
cd backend
python -m pytest tests/ -v
```

## API Documentation

Once running, visit:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
