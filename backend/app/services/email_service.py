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
    """Build base template context with site-wide defaults."""
    return {
        "site_name": settings.site_name or "ForgeStore",
        "site_tagline": settings.site_tagline or "",
        "base_url": settings.site_base_url.rstrip("/"),
        **kwargs,
    }


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
    body_html = f"""
    <p style="font-size:14px;color:#57534e;text-align:center;margin:0 0 20px;">Hi <strong>{customer_name}</strong>,</p>
    <p style="font-size:14px;color:#57534e;line-height:1.6;text-align:center;margin:0 0 20px;">
      Your order <strong>{order_number}</strong> has been placed successfully.
      We'll notify you when each vendor begins fulfillment.
    </p>
    """
    if vendor_sections:
        body_html += f'<p style="font-size:12px;color:#78716c;text-align:center;margin:0 0 4px;">This order includes items from {len(vendor_sections)} vendor(s):</p>'

    return _dispatch(
        to_email,
        f"Order Confirmed — {order_number}",
        "order_confirmation.html",
        {
            "heading": "Order Confirmed!",
            "subtitle": f"Order {order_number}",
            "body_html": body_html,
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
    body_html = f"""
    <p style="font-size:14px;color:#57534e;text-align:center;margin:0 0 20px;">Hi <strong>{vendor_name}</strong>,</p>
    <p style="font-size:14px;color:#57534e;line-height:1.6;text-align:center;margin:0 0 20px;">
      You have a new order to fulfill! Order <strong>{order_number}</strong>.
    </p>
    """
    return _dispatch(
        to_email,
        f"New Order — {order_number}",
        "vendor_new_order.html",
        {
            "heading": "New Order Received",
            "subtitle": f"Order {order_number}",
            "body_html": body_html,
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
    status_emoji = {"PAID": "✅", "PROCESSING": "🔧", "SHIPPED": "📦", "DELIVERED": "🎉", "CANCELLED": "❌"}
    emoji = status_emoji.get(status, "📋")

    body_html = f"""
    <p style="font-size:14px;color:#57534e;text-align:center;margin:0 0 20px;">Hi <strong>{customer_name}</strong>,</p>
    <p style="font-size:14px;color:#57534e;line-height:1.6;text-align:center;margin:0 0 20px;">
      Your order <strong>{order_number}</strong> has been updated to <strong>{status}</strong>.
    </p>
    """
    if tracking_number:
        body_html += f"""
        <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:16px;margin:16px 0;text-align:center;">
          <p style="font-size:12px;color:#166534;margin:0;font-weight:600;">Tracking Number</p>
          <p style="font-size:16px;color:#14532d;margin:4px 0 0;font-weight:800;font-family:monospace;">{tracking_number}</p>
        </div>
        """

    return _dispatch(
        to_email,
        f"Order {status.title()} — {order_number}",
        "order_status.html",
        {
            "heading": f"{emoji} Order {status.title()}!",
            "subtitle": f"Order {order_number}",
            "body_html": body_html,
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
    body_html = f"""
    <p style="font-size:14px;color:#57534e;line-height:1.6;text-align:center;margin:0 0 20px;">
      Click the button below to set a new password. This link expires in 1 hour.
    </p>
    """
    return _dispatch(
        to_email,
        "Reset Your ForgeStore Password",
        "password_reset.html",
        {
            "heading": "Reset Your Password",
            "body_html": body_html,
            "cta_url": reset_link,
            "cta_label": "Reset Password",
            "footer_text": "If you didn't request a password reset, you can safely ignore this email.",
        },
    )


def send_welcome_email(to_email: str, customer_name: str) -> bool:
    """Send welcome email (async background dispatch)."""
    body_html = f"""
    <p style="font-size:14px;color:#57534e;text-align:center;margin:0 0 20px;">Hi <strong>{customer_name}</strong>,</p>
    <p style="font-size:14px;color:#57534e;line-height:1.6;text-align:center;margin:0 0 20px;">
      Welcome to <strong>{settings.site_name or 'ForgeStore'}</strong>! Your account is ready.
    </p>
    <div style="background:#f5f5f4;border-radius:12px;padding:20px;margin:20px 0;">
      <p style="font-size:13px;color:#57534e;margin:0 0 8px;font-weight:600;">What you can do now:</p>
      <ul style="font-size:13px;color:#78716c;margin:0;padding-left:18px;line-height:1.8;">
        <li>Browse our multi-vendor marketplace</li>
        <li>Save favourites to your wishlist</li>
        <li>Track your orders in real time</li>
        <li>Share products and earn referral points</li>
      </ul>
    </div>
    """
    return _dispatch(
        to_email,
        f"Welcome to {settings.site_name or 'ForgeStore'}!",
        "welcome.html",
        {
            "heading": "Welcome to the Workshop!",
            "body_html": body_html,
            "cta_url": f"{settings.site_base_url.rstrip('/')}/shop",
            "cta_label": "Start Shopping",
            "customer_name": customer_name,
        },
    )


def send_newsletter_confirmation_email(to_email: str, confirm_url: str) -> bool:
    """Send newsletter confirmation email (async background dispatch)."""
    body_html = f"""
    <p style="font-size:14px;color:#57534e;line-height:1.6;text-align:center;margin:0 0 20px;">
      You (or someone) signed up for the newsletter with this email.
      Click the button below to confirm your subscription.
    </p>
    """
    return _dispatch(
        to_email,
        f"Confirm your newsletter subscription — {settings.site_name or 'ForgeStore'}",
        "newsletter_confirm.html",
        {
            "heading": "Almost there!",
            "body_html": body_html,
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
    body_html = f"""
    <p style="font-size:14px;color:#57534e;text-align:center;margin:0 0 20px;">Hi <strong>{retailer_name}</strong>,</p>
    <p style="font-size:14px;color:#57534e;line-height:1.6;text-align:center;margin:0 0 20px;">
      Your payout of <strong>₦{total_amount:,.2f}</strong> has been processed.
    </p>
    <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:20px;margin:20px 0;text-align:center;">
      <p style="font-size:11px;color:#166534;margin:0;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Amount Paid</p>
      <p style="font-size:28px;font-weight:800;color:#14532d;margin:8px 0 0;">₦{total_amount:,.2f}</p>
      <p style="font-size:12px;color:#a8a29e;margin:8px 0 0;">{earning_count} earning(s) included</p>
    </div>
    """
    return _dispatch(
        to_email,
        f"Payout Processed — {settings.site_name or 'ForgeStore'}",
        "payout_processed.html",
        {
            "heading": "Payout Processed!",
            "body_html": body_html,
            "amount": total_amount,
            "earning_count": earning_count,
            "customer_name": retailer_name,
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
        <div style="margin-top:32px;padding-top:20px;border-top:1px solid #e7e5e4;font-size:11px;color:#a8a29e;text-align:center;">
          <p style="margin:0 0 6px 0;">You're receiving this because you subscribed to {settings.site_name or 'ForgeStore'} newsletters.</p>
          <a href="{unsubscribe_url}" style="color:#a8a29e;text-decoration:underline;">Unsubscribe instantly</a>
        </div>
        """

    full_html = f"""
    <div style="font-family:'Helvetica Neue',Arial,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px;background:#fafaf9;border-radius:16px;">
      <div style="text-align:center;margin-bottom:24px;">
        <div style="display:inline-block;background:#1c1917;color:white;font-weight:800;font-size:20px;padding:10px 18px;border-radius:12px;">
          {settings.site_name or 'ForgeStore'}
        </div>
      </div>
      {html_body}
      {tracking_pixel}
      {unsubscribe_html}
    </div>
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
