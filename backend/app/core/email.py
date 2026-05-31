"""
Async Email Engine — non-blocking SMTP dispatcher with DB-driven configuration.

Resolution order:
  1. SystemSetting database keys (dynamic, hot-reloadable)
  2. Environment variables (fallback)
  3. Console stdout dump (dev fallback when no credentials)

All SMTP parameters are resolved per-send from live DB sessions,
eliminating startup-bound configuration coupling.
"""
import sys
import asyncio
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger("forgestore.email.async")


def _get_db_smtp_config() -> dict:
    """
    Dynamically resolve SMTP configuration from SystemSetting table.
    Each call opens a short-lived session to guarantee fresh values.
    """
    try:
        from app.database import SessionLocal
        from app.models import Settings as SettingsModel

        db = SessionLocal()
        try:
            keys = [
                "smtp_host", "smtp_port", "smtp_user", "smtp_password",
                "from_email", "mail_console_fallback",
            ]
            rows = db.query(SettingsModel).filter(
                SettingsModel.key.in_(keys)
            ).all()
            config = {r.key: r.value for r in rows}
        finally:
            db.close()
    except Exception as exc:
        logger.debug("DB SMTP lookup failed, using env fallback: %s", exc)
        config = {}

    # Resolve port safely
    raw_port = config.get("smtp_port", "") or "587"
    try:
        port = int(raw_port)
    except (ValueError, TypeError):
        port = 587

    # Environment fallbacks
    from app.config import get_settings
    env = get_settings()

    return {
        "host": config.get("smtp_host", "") or env.smtp_host or "",
        "port": port,
        "user": config.get("smtp_user", "") or env.smtp_user or "",
        "password": config.get("smtp_password", "") or env.smtp_password or "",
        "from_email": config.get("from_email", "") or env.from_email or "noreply@forgestore.com",
        "console_fallback": (config.get("mail_console_fallback", "") or "").lower() in ("true", "1", "yes"),
    }


def _console_dump(to_email: str, subject: str, html_content: str, tag: str = "DEV FALLBACK"):
    """Write email content to stdout as a last-resort fallback."""
    separator = "=" * 64
    _safe_print(f"\n{separator}")
    _safe_print(f"  [EMAIL {tag}] To: {to_email}")
    _safe_print(f"  [SUBJECT] {subject}")
    _safe_print(f"{separator}")
    # Truncate very long bodies for terminal readability
    if len(html_content) > 2000:
        _safe_print(f"  {html_content[:2000]}")
        _safe_print(f"  ... ({len(html_content) - 2000} chars truncated)")
    else:
        _safe_print(f"  {html_content}")
    _safe_print(f"{separator}\n")
    sys.stdout.flush()


def _safe_print(text: str):
    try:
        print(text)
    except UnicodeEncodeError:
        safe = text.encode("ascii", "replace").decode("ascii")
        print(safe)


async def send_platform_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_fallback: Optional[str] = None,
    from_email_override: Optional[str] = None,
) -> bool:
    """
    Asynchronously transmit email via runtime database SMTP parameters.

    - If console_fallback is enabled or credentials are missing → stdout dump
    - If Brevo API key exists → send via Brevo (preferred, no IP auth issues)
    - Otherwise → aiosmtplib with STARTTLS

    Returns True on success (including console fallback), False on hard failure.
    """
    smtp = _get_db_smtp_config()

    # Console fallback gate
    if smtp["console_fallback"] or (not smtp["user"] or not smtp["password"]):
        _console_dump(to_email, subject, html_content, tag="DEV FALLBACK")
        logger.info("Email routed to console fallback: %s -> %s", subject, to_email)
        return True

    # Try Brevo API first (no IP authorization issues)
    from app.config import get_settings
    env_settings = get_settings()
    if env_settings.brevo_api_key:
        try:
            result = await asyncio.to_thread(
                _send_via_brevo_sync,
                to_email, subject, html_content, smtp["from_email"],
                env_settings.brevo_api_key,
                env_settings.site_name or "ForgeStore",
            )
            if result:
                return True
            logger.warning("Brevo API failed, falling back to async SMTP")
        except Exception as exc:
            logger.warning("Brevo dispatch error: %s", exc)

    # Async SMTP dispatch via aiosmtplib
    from_email = from_email_override or smtp["from_email"]
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.attach(MIMEText(
        text_fallback or html_content.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n\n"),
        "plain",
    ))
    message.attach(MIMEText(html_content, "html"))

    try:
        import aiosmtplib
        use_tls = smtp["port"] == 465
        start_tls = smtp["port"] == 587
        await aiosmtplib.send(
            message,
            hostname=smtp["host"],
            port=smtp["port"],
            username=smtp["user"],
            password=smtp["password"],
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=15,
        )
        logger.info("Async email sent: %s -> %s", subject, to_email)
        return True
    except ImportError:
        logger.error("aiosmtplib not installed — pip install aiosmtplib")
        _console_dump(to_email, subject, html_content, tag="CRITICAL FALLBACK (aiosmtplib missing)")
        return True
    except Exception as exc:
        logger.error("SMTP failure for %s: %s", to_email, exc)
        _console_dump(to_email, subject, html_content, tag=f"CRITICAL FALLBACK ({exc})")
        return False


def _send_via_brevo_sync(
    to_email: str, subject: str, html_body: str,
    from_email: str, api_key: str, from_name: str,
) -> bool:
    """Synchronous Brevo API call (run in thread)."""
    try:
        import brevo_python
        from brevo_python.rest import ApiException

        configuration = brevo_python.Configuration()
        configuration.api_key["api-key"] = api_key
        api_instance = brevo_python.TransactionalEmailsApi(brevo_python.ApiClient(configuration))

        send_email = brevo_python.SendSmtpEmail(
            sender={"name": from_name, "email": from_email},
            to=[{"email": to_email}],
            subject=subject,
            html_content=html_body,
        )
        api_instance.send_transac_email(send_email)
        logger.info("Email sent via Brevo: %s -> %s", subject, to_email)
        return True
    except ImportError:
        logger.error("brevo-python not installed")
        return False
    except ApiException as exc:
        logger.error("Brevo API error: %s", exc)
        return False
    except Exception as exc:
        logger.error("Brevo unexpected error: %s", exc)
        return False


def dispatch_email_background(
    to_email: str,
    subject: str,
    html_content: str,
    text_fallback: Optional[str] = None,
) -> None:
    """
    Non-blocking email dispatch — schedules the async send on the running
    event loop without blocking the calling router thread.

    Usage from synchronous router code:
        dispatch_email_background(to, subj, html)

    Usage from async router code:
        asyncio.create_task(send_platform_email(to, subj, html))
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(send_platform_email(to_email, subject, html_content, text_fallback))
    except RuntimeError:
        # No running event loop — spawn a new thread
        import threading

        def _run():
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(
                    send_platform_email(to_email, subject, html_content, text_fallback)
                )
                new_loop.close()
            except Exception as exc:
                logger.error("Background email thread failed: %s", exc)

        threading.Thread(target=_run, daemon=True).start()
