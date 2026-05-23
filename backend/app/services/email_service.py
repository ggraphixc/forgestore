"""
Email service for sending transactional emails.
Uses SMTP with environment-based configuration. Falls back to console printing.

SMTP configuration is resolved from three sources (highest priority first):
1. Admin Settings panel (DB settings table)
2. .env file (via pydantic-settings)
3. Hard-coded defaults
"""
import smtplib
import logging
import re
import hashlib
import hmac
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.config import get_settings

logger = logging.getLogger("forgestore.email")

settings = get_settings()


def _safe_print(text: str):
    """Print text safely, handling UnicodeEncodeError on Windows terminals."""
    try:
        print(text)
    except UnicodeEncodeError:
        safe = text.encode("ascii", "replace").decode("ascii")
        print(safe)


def _get_smtp_config() -> dict:
    """
    Resolve SMTP configuration by checking DB settings first,
    then falling back to .env / pydantic-settings values.
    Uses a single batched DB query instead of 5 separate queries.
    """
    db_config = {}
    try:
        from app.database import SessionLocal
        from app.models import Settings as SettingsModel
        db = SessionLocal()
        try:
            keys = ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "from_email"]
            rows = db.query(SettingsModel).filter(
                SettingsModel.key.in_(keys)
            ).all()
            db_config = {r.key: r.value for r in rows}
        finally:
            db.close()
    except Exception:
        pass

    # Resolve port safely (handle non-numeric values)
    raw_port = db_config.get("smtp_port", "") or str(settings.smtp_port) or "587"
    try:
        port = int(raw_port)
    except (ValueError, TypeError):
        port = 587

    config = {
        "host": db_config.get("smtp_host", "") or settings.smtp_host or "",
        "port": port,
        "user": db_config.get("smtp_user", "") or settings.smtp_user or "",
        "password": db_config.get("smtp_password", "") or settings.smtp_password or "",
        "from_email": db_config.get("from_email", "") or settings.from_email or "noreply@forgestore.com",
    }
    return config


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> bool:
    """
    Send an email via SMTP. Falls back to console printing if SMTP is not configured.
    SMTP settings are resolved from the Admin Settings panel first, then .env.
    Returns True if sent successfully (or to console), False on error.
    """
    smtp = _get_smtp_config()
    smtp_host = smtp["host"]
    smtp_port = smtp["port"]
    smtp_user = smtp["user"]
    smtp_password = smtp["password"]
    from_email = smtp["from_email"]

    # If SMTP is not configured, print to console
    if not smtp_host or not smtp_port:
        base_url = settings.site_base_url.rstrip("/")
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  [EMAIL] TO: {to_email}")
        _safe_print(f"  [SUBJECT] {subject}")
        _safe_print(f"{'='*60}")
        _safe_print(f"  {html_body}")
        _safe_print(f"{'='*60}")
        _safe_print(f"  -- SMTP not configured --")
        _safe_print(f"  To send real emails, configure SMTP in:")
        _safe_print(f"  Admin > Settings > Developer Settings")
        _safe_print(f"  Or add to your .env file:")
        _safe_print(f"  SMTP_HOST=smtp.gmail.com")
        _safe_print(f"  SMTP_PORT=587")
        _safe_print(f"  SMTP_USER=your@email.com")
        _safe_print(f"  SMTP_PASSWORD=your-app-password")
        _safe_print(f"  FROM_EMAIL=noreply@forgestore.com")
        _safe_print(f"{'='*60}\n")
        logger.info(f"Email simulated (no SMTP configured): {subject} -> {to_email}")
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject

        # Attach plain text
        msg.attach(MIMEText(text_body or html_body.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n\n"), "plain"))

        # Attach HTML
        msg.attach(MIMEText(html_body, "html"))

        # Send via SMTP
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())

        logger.info(f"Email sent: {subject} -> {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  EMAIL FAILED TO SEND TO: {to_email}")
        _safe_print(f"  SUBJECT: {subject}")
        _safe_print(f"  ERROR: {e}")
        _safe_print(f"{'='*60}")
        _safe_print(f"  {html_body}")
        _safe_print(f"{'='*60}\n")
        return False


def send_password_reset_email(to_email: str, reset_link: str) -> bool:
    """Send a password reset email."""
    subject = "Reset Your ForgeStore Password"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; background: #fafaf9; border-radius: 16px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background: #1c1917; color: white; font-weight: 800; font-size: 20px; padding: 10px 18px; border-radius: 12px;">
                ForgeStore
            </div>
        </div>
        <h1 style="font-size: 22px; font-weight: 700; color: #1c1917; margin-bottom: 8px; text-align: center;">Reset Your Password</h1>
        <p style="font-size: 14px; color: #57534e; line-height: 1.6; text-align: center; margin-bottom: 24px;">
            Click the button below to set a new password. This link expires in 1 hour.
        </p>
        <div style="text-align: center; margin-bottom: 28px;">
            <a href="{reset_link}" style="display: inline-block; padding: 14px 32px; background: #1c1917; color: white; text-decoration: none; font-weight: 700; font-size: 14px; border-radius: 12px;">
                Reset Password
            </a>
        </div>
        <p style="font-size: 12px; color: #a8a29e; text-align: center;">
            If you didn't request a password reset, you can safely ignore this email.
            <br>
            <a href="{reset_link}" style="color: #a8a29e;">{reset_link}</a>
        </p>
    </div>
    """
    return send_email(to_email, subject, html)


def send_order_confirmation_email(to_email: str, order_number: str, customer_name: str) -> bool:
    """Send an order confirmation email."""
    subject = f"Order Confirmed — {order_number}"
    base_url = settings.site_base_url.rstrip("/")
    orders_link = f"{base_url}/shop/account/orders"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; background: #fafaf9; border-radius: 16px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background: #1c1917; color: white; font-weight: 800; font-size: 20px; padding: 10px 18px; border-radius: 12px;">
                ForgeStore
            </div>
        </div>
        <h1 style="font-size: 22px; font-weight: 700; color: #1c1917; margin-bottom: 8px; text-align: center;">Order Confirmed!</h1>
        <p style="font-size: 14px; color: #57534e; text-align: center;">Hi <strong>{customer_name}</strong>,</p>
        <p style="font-size: 14px; color: #57534e; line-height: 1.6; text-align: center; margin-bottom: 20px;">
            Your order <strong>{order_number}</strong> has been placed successfully.
            We'll notify you when it ships.
        </p>
        <div style="text-align: center; margin-bottom: 28px;">
            <a href="{orders_link}" style="display: inline-block; padding: 14px 32px; background: #1c1917; color: white; text-decoration: none; font-weight: 700; font-size: 14px; border-radius: 12px;">
                View My Orders
            </a>
        </div>
        <p style="font-size: 12px; color: #a8a29e; text-align: center;">
            Thank you for shopping at ForgeStore!<br>
            <span style="color: #78716c;">Questions? Reply to this email.</span>
        </p>
    </div>
    """
    return send_email(to_email, subject, html)


def send_welcome_email(to_email: str, customer_name: str) -> bool:
    """Send a welcome email to new users after signup."""
    subject = f"Welcome to {settings.site_name or 'ForgeStore'}!"
    base_url = settings.site_base_url.rstrip("/")
    shop_link = f"{base_url}/shop"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; background: #fafaf9; border-radius: 16px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background: #1c1917; color: white; font-weight: 800; font-size: 20px; padding: 10px 18px; border-radius: 12px;">
                {settings.site_name or 'ForgeStore'}
            </div>
        </div>
        <h1 style="font-size: 22px; font-weight: 700; color: #1c1917; margin-bottom: 8px; text-align: center;">Welcome to the Workshop! ✨</h1>
        <p style="font-size: 14px; color: #57534e; text-align: center;">Hi <strong>{customer_name}</strong>,</p>
        <p style="font-size: 14px; color: #57534e; line-height: 1.6; text-align: center; margin-bottom: 20px;">
            Thank you for creating an account at {settings.site_name or 'ForgeStore'}.
            You now have access to exclusive collections, a personal wishlist, and fast checkout.
        </p>
        <div style="text-align: center; margin-bottom: 24px;">
            <a href="{shop_link}" style="display: inline-block; padding: 14px 32px; background: #1c1917; color: white; text-decoration: none; font-weight: 700; font-size: 14px; border-radius: 12px;">
                Start Shopping
            </a>
        </div>
        <div style="background: #f5f5f4; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
            <p style="font-size: 13px; color: #57534e; margin: 0 0 8px 0; font-weight: 600;">What you can do now:</p>
            <ul style="font-size: 13px; color: #78716c; margin: 0; padding-left: 18px; line-height: 1.8;">
                <li>Browse our marketplace of handcrafted goods</li>
                <li>Save favourites to your wishlist</li>
                <li>Track your orders in real time</li>
                <li>Get exclusive artisan updates</li>
            </ul>
        </div>
        <p style="font-size: 12px; color: #a8a29e; text-align: center; margin: 0;">
            Questions? Reply to this email or visit our Help Center.
        </p>
    </div>
    """
    return send_email(to_email, subject, html)


def send_newsletter_confirmation_email(to_email: str, confirm_url: str) -> bool:
    """Send a newsletter subscription confirmation email with a link to confirm."""
    subject = f"Confirm your newsletter subscription — {settings.site_name or 'ForgeStore'}"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; background: #fafaf9; border-radius: 16px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background: #1c1917; color: white; font-weight: 800; font-size: 20px; padding: 10px 18px; border-radius: 12px;">
                {settings.site_name or 'ForgeStore'}
            </div>
        </div>
        <h1 style="font-size: 22px; font-weight: 700; color: #1c1917; margin-bottom: 8px; text-align: center;">Almost there! 📨</h1>
        <p style="font-size: 14px; color: #57534e; line-height: 1.6; text-align: center; margin-bottom: 20px;">
            You (or someone) signed up for the {settings.site_name or 'ForgeStore'} newsletter with this email address.
            Click the button below to confirm your subscription.
        </p>
        <div style="text-align: center; margin-bottom: 24px;">
            <a href="{confirm_url}" style="display: inline-block; padding: 14px 32px; background: #1c1917; color: white; text-decoration: none; font-weight: 700; font-size: 14px; border-radius: 12px;">
                Confirm Subscription
            </a>
        </div>
        <p style="font-size: 12px; color: #a8a29e; text-align: center;">
            If you didn't sign up, you can safely ignore this email.
            <br>
            <a href="{confirm_url}" style="color: #a8a29e;">{confirm_url}</a>
        </p>
    </div>
    """
    return send_email(to_email, subject, html)


def _wrap_links_for_tracking(html_body: str, campaign_id: str, subscriber_id: str, base_url: str) -> str:
    """Wrap all <a href="..."> links in the email to go through the tracking redirect.
    Uses a simple regex to find href attributes.
    """
    def _replace_link(match):
        full = match.group(0)
        url = match.group(1)
        # Don't wrap unsubscribe links or hash-only links
        if url.startswith("#") or "unsubscribe" in url.lower():
            return full
        # Build tracking URL
        sig = hmac.new(
            settings.secret_key.encode() if settings.secret_key else b"forgestore",
            f"{campaign_id}:{subscriber_id}:{url}".encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        from urllib.parse import quote
        tracking_url = f"{base_url}/api/newsletter/track/{campaign_id}/{subscriber_id}?url={quote(url)}&sig={sig}"
        return full.replace(url, tracking_url)

    return re.sub(r'href="([^"]+)"', _replace_link, html_body)


def _tracking_pixel(campaign_id: str, subscriber_id: str, base_url: str) -> str:
    """Generate a 1x1 transparent tracking pixel for open tracking."""
    return f'<img src="{base_url}/api/newsletter/open/{campaign_id}/{subscriber_id}" alt="" width="1" height="1" style="display:none;" />'


def send_newsletter_broadcast(
    to_email: str,
    subject: str,
    html_body: str,
    unsubscribe_url: str = "",
    campaign_id: str = "",
    subscriber_id: str = "",
) -> bool:
    """Send a broadcast/campaign email to a subscriber.
    Appends tracking pixel, wraps links for click tracking, and adds unsubscribe footer.
    """
    base_url = settings.site_base_url.rstrip("/")

    # Wrap links for click tracking
    if campaign_id and subscriber_id:
        html_body = _wrap_links_for_tracking(html_body, campaign_id, subscriber_id, base_url)

    # Add tracking pixel
    tracking_pixel = ""
    if campaign_id and subscriber_id:
        tracking_pixel = _tracking_pixel(campaign_id, subscriber_id, base_url)

    unsubscribe_html = ""
    if unsubscribe_url:
        unsubscribe_html = f"""
        <div style="margin-top: 32px; padding-top: 20px; border-top: 1px solid #e7e5e4; font-size: 11px; color: #a8a29e; text-align: center;">
            <p style="margin: 0 0 6px 0;">You're receiving this because you subscribed to {settings.site_name or 'ForgeStore'} newsletters.</p>
            <a href="{unsubscribe_url}" style="color: #a8a29e; text-decoration: underline;">Unsubscribe instantly</a>
        </div>
        """

    full_html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; background: #fafaf9; border-radius: 16px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background: #1c1917; color: white; font-weight: 800; font-size: 20px; padding: 10px 18px; border-radius: 12px;">
                {settings.site_name or 'ForgeStore'}
            </div>
        </div>
        {html_body}
        {tracking_pixel}
        {unsubscribe_html}
    </div>
    """
    return send_email(to_email, subject, full_html)


def send_order_status_email(to_email: str, order_number: str, customer_name: str, status: str) -> bool:
    """Send an email when order status changes."""
    status_emoji = {
        "PAID": "✅",
        "PROCESSING": "🔧",
        "SHIPPED": "📦",
        "DELIVERED": "🎉",
        "CANCELLED": "❌",
    }
    emoji = status_emoji.get(status, "📋")
    subject = f"Order {status.title()} — {order_number}"
    base_url = settings.site_base_url.rstrip("/")
    orders_link = f"{base_url}/shop/account/orders"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; background: #fafaf9; border-radius: 16px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background: #1c1917; color: white; font-weight: 800; font-size: 20px; padding: 10px 18px; border-radius: 12px;">
                ForgeStore
            </div>
        </div>
        <h1 style="font-size: 22px; font-weight: 700; color: #1c1917; margin-bottom: 8px; text-align: center;">
            {emoji} Order {status.title()}!
        </h1>
        <p style="font-size: 14px; color: #57534e; text-align: center;">Hi <strong>{customer_name}</strong>,</p>
        <p style="font-size: 14px; color: #57534e; line-height: 1.6; text-align: center; margin-bottom: 20px;">
            Your order <strong>{order_number}</strong> has been updated to <strong>{status}</strong>.
        </p>
        <div style="text-align: center; margin-bottom: 28px;">
            <a href="{orders_link}" style="display: inline-block; padding: 14px 32px; background: #1c1917; color: white; text-decoration: none; font-weight: 700; font-size: 14px; border-radius: 12px;">
                View My Orders
            </a>
        </div>
        <p style="font-size: 12px; color: #a8a29e; text-align: center;">
            Thank you for shopping at ForgeStore!<br>
            <span style="color: #78716c;">Questions? Reply to this email.</span>
        </p>
    </div>
    """
    return send_email(to_email, subject, html)
