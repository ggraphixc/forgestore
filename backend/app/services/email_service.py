"""
Email Service — transactional email dispatch via async engine + Jinja2 templates.

All functions are non-blocking wrappers that delegate to app.core.email.
Templates are resolved via the raw Jinja2 Environment in templates_shared.py.
"""
import logging
import hashlib
import hmac
from typing import Optional
from urllib.parse import quote

from app.config import get_settings

logger = logging.getLogger("forgestore.email")
settings = get_settings()


def _render_email_template(template_name: str, context: dict) -> str:
    """Render an email template using the raw Jinja2 Environment."""
    from app.templates_shared import env
    template = env.get_template(f"email/{template_name}")
    return template.render(**context)


def _base_context(**kwargs) -> dict:
    """Build base template context with site-wide defaults and email branding."""
    ctx = {
        "site_name": settings.site_name or "ForgeStore",
        "site_tagline": settings.site_tagline or "",
        "base_url": settings.site_base_url.rstrip("/"),
        # Email branding defaults
        "email_header_color": "#f59e0b",
        "email_button_color": "#f59e0b",
        "email_footer_text": "",
        "email_logo_url": "",
        **kwargs,
    }
    # Override with DB settings if available
    try:
        from app.database import SessionLocal
        from app.models import Settings as SettingsModel
        db = SessionLocal()
        db_keys = [
            "email_header_color", "email_button_color",
            "email_footer_text", "email_logo_url",
            "site_name", "site_tagline",
        ]
        for key in db_keys:
            setting = db.query(SettingsModel).filter(SettingsModel.key == key).first()
            if setting and setting.value:
                ctx[key] = setting.value
        db.close()
    except Exception:
        pass
    return ctx


def _dispatch(to_email: str, subject: str, template_name: str, context: dict) -> bool:
    """Render template and dispatch via async engine (non-blocking from sync callers)."""
    try:
        html = _render_email_template(template_name, _base_context(**context))
    except Exception as exc:
        logger.error("Template render failed for %s: %s", template_name, exc)
        html = f"<p>{context.get('heading', subject)}</p><p>{context.get('subtitle', '')}</p>"

    from app.core.email import dispatch_email_background
    dispatch_email_background(to_email, subject, html)
    return True


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API — each function is a thin non-blocking wrapper
# ═══════════════════════════════════════════════════════════════════


def send_order_confirmation_email(
    to_email: str,
    order_number: str,
    customer_name: str,
    vendor_sections: Optional[list] = None,
    items_table: Optional[list] = None,
    summary_lines: Optional[list] = None,
) -> bool:
    """Send order confirmation email (async background dispatch)."""
    return _dispatch(
        to_email,
        f"Order Confirmed — {order_number}",
        "order_confirmation.html",
        {
            "heading": "Order Confirmed!",
            "subtitle": f"Thank you, {customer_name}. Your order has been placed successfully.",
            "icon": {"emoji": "✅", "bg": "#f0fdf4"},
            "cta_url": f"{settings.site_base_url.rstrip('/')}/shop/account/orders",
            "cta_label": "View My Orders",
            "customer_name": customer_name,
            "order_number": order_number,
            "vendor_sections": vendor_sections or [],
            "items_table": items_table or [],
            "summary_lines": summary_lines or [],
        },
    )


def send_vendor_new_order_email(
    to_email: str,
    vendor_name: str,
    order_number: str,
    items: list,
    net_payout: float,
    commission: float,
    commission_pct: float,
) -> bool:
    """Send new order notification to vendor (async background dispatch)."""
    return _dispatch(
        to_email,
        f"New Order — {order_number}",
        "vendor_new_order.html",
        {
            "heading": "New Order Received!",
            "subtitle": f"A customer has placed an order with your shop.",
            "icon": {"emoji": "🔔", "bg": "#fef3c7"},
            "vendor_name": vendor_name,
            "order_number": order_number,
            "items": items,
            "net_payout": net_payout,
            "commission": commission,
            "commission_pct": commission_pct,
        },
    )


def send_order_status_email(
    to_email: str,
    order_number: str,
    customer_name: str,
    status: str,
    tracking_number: Optional[str] = None,
) -> bool:
    """Send order status update email (async background dispatch)."""
    status_map = {
        "PAID": {
            "emoji": "✅", "label": "Payment Confirmed",
            "bg": "#f0fdf4", "border": "#bbf7d0", "color": "#166534",
            "icon_bg": "#f0fdf4",
        },
        "PROCESSING": {
            "emoji": "🔧", "label": "Being Prepared",
            "bg": "#eff6ff", "border": "#bfdbfe", "color": "#1e40af",
            "icon_bg": "#eff6ff",
        },
        "SHIPPED": {
            "emoji": "📦", "label": "Shipped",
            "bg": "#fef3c7", "border": "#fde68a", "color": "#92400e",
            "icon_bg": "#fef3c7",
        },
        "DELIVERED": {
            "emoji": "🎉", "label": "Delivered",
            "bg": "#f0fdf4", "border": "#bbf7d0", "color": "#166534",
            "icon_bg": "#f0fdf4",
        },
        "CANCELLED": {
            "emoji": "❌", "label": "Cancelled",
            "bg": "#fef2f2", "border": "#fecaca", "color": "#991b1b",
            "icon_bg": "#fef2f2",
        },
    }
    s = status_map.get(status, {
        "emoji": "📋", "label": status.title(),
        "bg": "#f5f5f4", "border": "#e7e5e4", "color": "#57534e",
        "icon_bg": "#f5f5f4",
    })

    # Build status timeline for common flows
    timeline = None
    if status in ("PAID", "PROCESSING", "SHIPPED", "DELIVERED"):
        steps = [
            {"icon": "✓", "label": "Order Placed", "active": True},
            {"icon": "✓", "label": "Payment Confirmed", "active": status in ("PROCESSING", "SHIPPED", "DELIVERED")},
            {"icon": "→", "label": "Processing", "active": status in ("SHIPPED", "DELIVERED")},
            {"icon": "→", "label": "Shipped", "active": status == "DELIVERED"},
            {"icon": "○", "label": "Delivered", "active": False},
        ]
        timeline = steps[:({"PAID": 2, "PROCESSING": 3, "SHIPPED": 4, "DELIVERED": 5}.get(status, 2))]

    return _dispatch(
        to_email,
        f"Order {status.title()} — {order_number}",
        "order_status.html",
        {
            "heading": f"{s['emoji']} {s['label']}!",
            "subtitle": f"Order {order_number} has been updated.",
            "icon": {"emoji": s["emoji"], "bg": s["icon_bg"]},
            "status_banner": {"text": s["label"], "bg": s["bg"], "border": s["border"], "color": s["color"]},
            "status_bg": s["bg"],
            "status_border": s["border"],
            "status_color": s["color"],
            "status_label": s["label"],
            "status_timeline": timeline,
            "cta_url": f"{settings.site_base_url.rstrip('/')}/shop/account/orders",
            "cta_label": "View My Orders",
            "customer_name": customer_name,
            "order_number": order_number,
            "status": status,
            "tracking_number": tracking_number or "",
        },
    )


def send_password_reset_email(to_email: str, reset_link: str) -> bool:
    """Send password reset email (async background dispatch)."""
    return _dispatch(
        to_email,
        "Reset Your ForgeStore Password",
        "password_reset.html",
        {
            "heading": "Reset Your Password",
            "subtitle": "We received a request to reset your password.",
            "icon": {"emoji": "🔒", "bg": "#fef2f2"},
            "cta_url": reset_link,
            "cta_label": "Set New Password",
            "footer_text": "If you didn't request a password reset, you can safely ignore this email.",
        },
    )


def send_welcome_email(to_email: str, customer_name: str) -> bool:
    """Send welcome email (async background dispatch)."""
    return _dispatch(
        to_email,
        f"Welcome to {settings.site_name or 'ForgeStore'}!",
        "welcome.html",
        {
            "heading": f"Welcome, {customer_name}!",
            "subtitle": f"Your {settings.site_name or 'ForgeStore'} account is ready. Here's what you can do:",
            "icon": {"emoji": "👋", "bg": "#fef3c7"},
            "cta_url": f"{settings.site_base_url.rstrip('/')}/shop",
            "cta_label": "Start Shopping",
            "customer_name": customer_name,
        },
    )


def send_newsletter_confirmation_email(to_email: str, confirm_url: str) -> bool:
    """Send newsletter confirmation email (async background dispatch)."""
    return _dispatch(
        to_email,
        f"Confirm your newsletter subscription — {settings.site_name or 'ForgeStore'}",
        "newsletter_confirm.html",
        {
            "heading": "Almost There!",
            "subtitle": "",
            "icon": {"emoji": "✉️", "bg": "#eff6ff"},
            "cta_url": confirm_url,
            "cta_label": "Confirm Subscription",
            "footer_text": "If you didn't sign up, you can safely ignore this email.",
        },
    )


def send_payout_email(
    to_email: str,
    retailer_name: str,
    total_amount: float,
    earning_count: int,
) -> bool:
    """Send payout processed email (async background dispatch)."""
    return _dispatch(
        to_email,
        f"Payout Processed — {settings.site_name or 'ForgeStore'}",
        "payout_processed.html",
        {
            "heading": "Payout Sent!",
            "subtitle": f"Hi {retailer_name}, your earnings have been processed.",
            "icon": {"emoji": "💸", "bg": "#f0fdf4"},
            "amount": total_amount,
            "earning_count": earning_count,
            "customer_name": retailer_name,
            "show_divider": False,
        },
    )


def send_newsletter_broadcast(
    to_email: str,
    subject: str,
    html_body: str,
    unsubscribe_url: str = "",
    campaign_id: str = "",
    subscriber_id: str = "",
) -> bool:
    """Send broadcast email with tracking pixel and link wrapping."""
    base_url = settings.site_base_url.rstrip("/")

    # Wrap links for click tracking
    if campaign_id and subscriber_id:
        html_body = _wrap_links_for_tracking(html_body, campaign_id, subscriber_id, base_url)

    # Add tracking pixel
    tracking_pixel = ""
    if campaign_id and subscriber_id:
        tracking_pixel = f'<img src="{base_url}/api/newsletter/open/{campaign_id}/{subscriber_id}" alt="" width="1" height="1" style="display:none;" />'

    unsubscribe_html = ""
    if unsubscribe_url:
        unsubscribe_html = f"""
        <div style="margin-top:32px;padding-top:20px;border-top:1px solid #f5f5f4;font-size:11px;color:#a8a29e;text-align:center;">
          <p style="margin:0 0 6px 0;">You're receiving this because you subscribed to {settings.site_name or 'ForgeStore'} newsletters.</p>
          <a href="{unsubscribe_url}" style="color:#a8a29e;text-decoration:underline;">Unsubscribe instantly</a>
        </div>
        """

    full_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
    <body style="margin:0;padding:0;background:#faf9f7;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#faf9f7;padding:40px 20px;">
    <tr><td align="center">
    <table width="580" cellpadding="0" cellspacing="0" style="max-width:580px;width:100%;background:#ffffff;border-radius:20px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.06);">
      <tr><td style="background:linear-gradient(135deg,#1c1917 0%,#292524 50%,#44403c 100%);padding:36px 40px 32px;text-align:center;">
        <span style="color:#ffffff;font-size:24px;font-weight:800;letter-spacing:-0.5px;">{settings.site_name or 'ForgeStore'}</span>
        <div style="margin:20px auto 0;width:48px;height:3px;background:linear-gradient(90deg,#f59e0b,#d97706);border-radius:2px;"></div>
      </td></tr>
      <tr><td style="padding:40px;">
        {html_body}
        {tracking_pixel}
        {unsubscribe_html}
      </td></tr>
      <tr><td style="padding:28px 40px 36px;text-align:center;">
        <p style="font-size:11px;color:#d6d3d1;margin:0;">&copy; 2026 {settings.site_name or 'ForgeStore'}. All rights reserved.</p>
      </td></tr>
    </table>
    </td></tr>
    </table>
    </body>
    </html>
    """
    return _dispatch_raw(to_email, subject, full_html)


def _dispatch_raw(to_email: str, subject: str, html: str) -> bool:
    """Dispatch pre-rendered HTML via async engine."""
    from app.core.email import dispatch_email_background
    dispatch_email_background(to_email, subject, html)
    return True


def _wrap_links_for_tracking(html_body: str, campaign_id: str, subscriber_id: str, base_url: str) -> str:
    """Wrap <a href> links for click tracking."""
    import re

    def _replace_link(match):
        full = match.group(0)
        url = match.group(1)
        if url.startswith("#") or "unsubscribe" in url.lower():
            return full
        sig = hmac.new(
            settings.secret_key.encode() if settings.secret_key else b"forgestore",
            f"{campaign_id}:{subscriber_id}:{url}".encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        tracking_url = f"{base_url}/api/newsletter/track/{campaign_id}/{subscriber_id}?url={quote(url)}&sig={sig}"
        return full.replace(url, tracking_url)

    return re.sub(r'href="([^"]+)"', _replace_link, html_body)
