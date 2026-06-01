"""
Async Email Engine — Brevo HTTP API v3 dispatcher with verified sender.

Resolution order:
  1. Environment variables (BREVO_API_KEY, MAIL_FROM_EMAIL, MAIL_CONSOLE_FALLBACK)
  2. Console stdout dump (dev fallback when no API key or fallback enabled)

All email transmission is performed via HTTPS POST to Brevo's transactional
email endpoint — no raw SMTP ports, no STARTTLS negotiation.
"""
import os
import sys
import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger("forgestore.email")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _console_dump(to_email: str, subject: str, html_content: str, tag: str = "DEV FALLBACK"):
    """Write email content to stdout as a last-resort fallback."""
    separator = "=" * 64
    _safe_print(f"\n{separator}")
    _safe_print(f"  [EMAIL {tag}] To: {to_email}")
    _safe_print(f"  [SUBJECT] {subject}")
    _safe_print(f"{separator}")
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


def _resolve_config() -> dict:
    """Resolve email configuration from env vars via Pydantic settings."""
    from app.config import get_settings
    env = get_settings()
    return {
        "api_key": env.brevo_api_key,
        "from_email": env.mail_from_email,
        "console_fallback": env.mail_console_fallback,
        "site_name": env.site_name or "ForgeStore",
    }


async def send_platform_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_fallback: Optional[str] = None,
    from_email_override: Optional[str] = None,
) -> bool:
    """
    Asynchronously transmit email via Brevo HTTP API v3.

    - If console_fallback is enabled or API key is missing -> stdout dump
    - Otherwise -> HTTPS POST to Brevo transactional endpoint

    Returns True on success (including console fallback), False on hard failure.
    """
    cfg = _resolve_config()

    if cfg["console_fallback"] or not cfg["api_key"]:
        _console_dump(to_email, subject, html_content, tag="DEV FALLBACK")
        logger.info("Email routed to console fallback: %s -> %s", subject, to_email)
        return True

    from_email = from_email_override or cfg["from_email"]

    payload = {
        "sender": {
            "name": cfg["site_name"],
            "email": from_email,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }

    headers = {
        "api-key": cfg["api_key"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(BREVO_API_URL, headers=headers, json=payload)

            if response.status_code in (200, 201, 202):
                logger.info("Email sent via Brevo HTTP API: %s -> %s", subject, to_email)
                return True

            logger.error(
                "Brevo API rejected request (HTTP %d): %s",
                response.status_code,
                response.text,
            )
            _console_dump(
                to_email, subject, html_content,
                tag=f"BREVO REJECTION HTTP {response.status_code}",
            )
            return False

    except Exception as exc:
        logger.error("Brevo HTTP API connection failed: %s", exc)
        _console_dump(to_email, subject, html_content, tag=f"HTTP CONNECTION FAILURE ({exc})")
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
