"""SEO helpers: meta tags, structured data (JSON-LD), sitemap.xml generation.

Usage in templates:
    render_template("page.html", seo=seo_context(request, product=p))

In Jinja2:
    {{ seo.title }}
    {{ seo.description }}
    {{ seo.og_image }}
    {{ seo.json_ld | safe }}
"""
import json
from typing import Optional
from app.config import get_settings, get_db_setting


def _site_name() -> str:
    return get_db_setting("site_name", "ForgeStore")


def _base_url() -> str:
    return get_settings().site_base_url.rstrip("/")


def _currency() -> str:
    return get_db_setting("currency", "NGN")


def seo_context(
    request=None,
    title: str = "",
    description: str = "",
    image: str = "",
    url: str = "",
    product=None,
    organization=None,
    breadcrumbs=None,
    page_type: str = "website",
) -> dict:
    """Build SEO context dict for a template."""
    settings = get_settings()
    site_name = _site_name()
    base_url = _base_url()

    if not title:
        title = site_name
    elif site_name not in title:
        title = f"{title} | {site_name}"

    if not description:
        description = get_db_setting("site_tagline", "Your One-Stop Marketplace")

    if not image:
        image = f"{base_url}/static/images/og-default.png"

    if not url and request:
        url = f"{base_url}{request.url.path}"

    # Product JSON-LD
    json_ld = None
    if product:
        json_ld = _product_json_ld(product, base_url, site_name)

    # Organization JSON-LD
    if organization and not json_ld:
        json_ld = _organization_json_ld(base_url, site_name)

    # BreadcrumbList JSON-LD
    if breadcrumbs and not json_ld:
        json_ld = _breadcrumb_json_ld(breadcrumbs, base_url)

    # Website JSON-LD (default)
    if not json_ld:
        json_ld = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": site_name,
            "url": base_url,
            "potentialAction": {
                "@type": "SearchAction",
                "target": f"{base_url}/shop?search={{search_term_string}}",
                "query-input": "required name=search_term_string",
            },
        }

    return {
        "title": title,
        "description": description,
        "og_title": title,
        "og_description": description,
        "og_image": image,
        "og_url": url,
        "og_site_name": site_name,
        "twitter_card": "summary_large_image",
        "json_ld": json.dumps(json_ld, ensure_ascii=False) if json_ld else "",
        "canonical_url": url,
        "robots": "index, follow",
    }


def _product_json_ld(product, base_url: str, site_name: str) -> dict:
    """Generate Product schema.org JSON-LD."""
    images = getattr(product, "images", None) or []
    price = getattr(product, "discount_price", None) or getattr(product, "price", 0)
    currency = _currency()

    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": getattr(product, "name", ""),
        "description": getattr(product, "description", "")[:500] if getattr(product, "description", None) else "",
        "url": f"{base_url}/product/{getattr(product, 'slug', '')}",
        "brand": {"@type": "Brand", "name": getattr(product, "brand", "") or site_name},
    }

    if images:
        ld["image"] = images if isinstance(images, list) else [images]

    rating = getattr(product, "rating", 0)
    review_count = getattr(product, "review_count", 0)
    if rating > 0 and review_count > 0:
        ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": round(rating, 1),
            "reviewCount": review_count,
        }

    ld["offers"] = {
        "@type": "Offer",
        "price": round(price, 2),
        "priceCurrency": currency,
        "availability": "https://schema.org/InStock" if getattr(product, "inventory", 0) > 0 else "https://schema.org/OutOfStock",
        "seller": {"@type": "Organization", "name": site_name},
    }

    return ld


def _organization_json_ld(base_url: str, site_name: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": site_name,
        "url": base_url,
        "logo": f"{base_url}/static/images/logo.png",
    }


def _breadcrumb_json_ld(breadcrumbs: list[dict], base_url: str) -> dict:
    """breadcrumbs: [{"name": "Home", "url": "/"}, {"name": "Shoes", "url": "/category/shoes"}]"""
    items = []
    for i, crumb in enumerate(breadcrumbs, 1):
        items.append({
            "@type": "ListItem",
            "position": i,
            "name": crumb["name"],
            "item": f"{base_url}{crumb['url']}" if crumb.get("url") else "",
        })
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }


def generate_sitemap(db) -> str:
    """Generate sitemap.xml content."""
    from app.models import Product, Category, Retailer

    base_url = _base_url()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    # Homepage
    lines.append(f"  <url><loc>{base_url}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>")
    lines.append(f"  <url><loc>{base_url}/shop</loc><changefreq>daily</changefreq><priority>0.9</priority></url>")

    # Categories
    categories = db.query(Category).all()
    for cat in categories:
        lines.append(f"  <url><loc>{base_url}/category/{cat.slug}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>")

    # Approved products
    products = db.query(Product).filter(Product.status == "APPROVED").all()
    for p in products:
        lines.append(f"  <url><loc>{base_url}/product/{p.slug}</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>")

    # Vendor pages
    retailers = db.query(Retailer).filter(Retailer.status == "ACTIVE").all()
    for r in retailers:
        lines.append(f"  <url><loc>{base_url}/vendor/{r.slug}</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>")

    lines.append("</urlset>")
    return "\n".join(lines)
