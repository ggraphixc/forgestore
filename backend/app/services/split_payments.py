"""
Split-Payment Engine — automated Paystack subaccount routing for multi-vendor carts.

Evaluates item distributions across vendors, calculates platform commissions,
and returns structured Paystack transaction initialization payloads with
split configuration for direct gateway-level fund routing.
"""
import os
import logging
import uuid
from typing import Optional

import httpx

logger = logging.getLogger("app.payments")

PAYSTACK_API_BASE = "https://api.paystack.co"


async def build_paystack_split_payload(
    db: Session,
    email: str,
    order_reference: str,
    total_amount_kobo: int,
    items_by_vendor: dict,
) -> tuple[str, dict, dict]:
    """Build Paystack split transaction initialization payload.

    Evaluates item distributions across multi-tenant vendors, calculates
    platform commissions, and returns (url, headers, payload) ready for
    Paystack transaction/initialize endpoint.

    Args:
        db: Database session
        customer_email: Customer email address
        order_reference: Unique order reference string
        total_amount_kobo: Total cart amount in kobo (NGN minor units)
        items_by_vendor: Dict mapping vendor_id -> subtotal in kobo

    Returns:
        Tuple of (api_url, headers_dict, payload_dict)
    """
    from sqlalchemy.orm import Session as _Session
    from app.models import Settings as SettingsModel, Retailer

    paystack_secret = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
    site_base_url = os.getenv("SITE_BASE_URL", "https://forgestore1.onrender.com").rstrip("/")

    # 1. Fetch platform commission percentage (default 10%)
    commission_setting = db.query(SettingsModel).filter(
        SettingsModel.key == "market_commission_percentage"
    ).first()
    commission_pct = float(commission_setting.value) if commission_setting else 10.0

    subaccounts_split = []

    # 2. Iterate through vendors to allocate sub-total with commission deduction
    for vendor_id, vendor_subtotal_kobo in items_by_vendor.items():
        if not vendor_id or vendor_id == "__unassigned__":
            logger.warning("Skipping unassigned vendor subtotal ₦%.2f — routing to platform escrow", vendor_subtotal_kobo / 100)
            continue

        vendor_record = db.query(Retailer).filter(Retailer.id == vendor_id).first()

        if vendor_record and getattr(vendor_record, "paystack_subaccount_code", None):
            commission_deduction = int(vendor_subtotal_kobo * (commission_pct / 100.0))
            vendor_share = vendor_subtotal_kobo - commission_deduction

            subaccounts_split.append({
                "subaccount": vendor_record.paystack_subaccount_code,
                "share": vendor_share,
            })
            logger.info(
                "Split vendor=%s gross_kobo=%d commission_kobo=%d net_kobo=%d",
                vendor_id, vendor_subtotal_kobo, commission_deduction, vendor_share,
            )
        else:
            logger.warning(
                "Vendor %s has no Paystack subaccount. Routing subtotal ₦%.2f to primary platform escrow.",
                vendor_id, vendor_subtotal_kobo / 100,
            )

    # 3. Compile the Paystack Transaction initialization dictionary
    url = f"{PAYSTACK_API_BASE}/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {paystack_secret}",
        "Content-Type": "application/json",
    }

    payload = {
        "email": email,
        "amount": total_amount_kobo,
        "reference": order_reference,
        "callback_url": f"{site_base_url}/api/payments/paystack/callback",
    }

    # Attach split configuration only when subaccounts were resolved
    if subaccounts_split:
        payload["split"] = {
            "type": "flat",
            "bearer_type": "all",
            "subaccounts": subaccounts_split,
        }

    return url, headers, payload


def calculate_vendor_splits_sync(
    db,
    fulfillments: list[dict],
    platform_commission_pct: float = 10.0,
) -> list[dict]:
    """Synchronous split calculation for use outside async contexts.

    Args:
        db: Database session
        fulfillments: List of dicts with retailer_id, total_amount keys
        platform_commission_pct: Fallback commission percentage

    Returns:
        List of split dicts with subaccount_code, share_kobo, commission, net_amount
    """
    from app.models import Retailer, Settings as SettingsModel

    # Resolve commission from DB if not provided
    setting = db.query(SettingsModel).filter(
        SettingsModel.key == "market_commission_percentage"
    ).first()
    if setting:
        try:
            platform_commission_pct = float(setting.value)
        except (ValueError, TypeError):
            pass

    splits = []
    for fd in fulfillments:
        retailer_id = fd.get("retailer_id")
        if not retailer_id:
            continue

        retailer = db.query(Retailer).filter(Retailer.id == retailer_id).first()
        if not retailer or not retailer.paystack_subaccount_code:
            logger.warning("Vendor %s has no subaccount code, skipping", retailer_id)
            continue

        gross = fd["total_amount"]
        rate = retailer.commission_rate or platform_commission_pct
        commission = round(gross * rate / 100, 2)
        net = round(gross - commission, 2)

        splits.append({
            "retailer_id": retailer_id,
            "subaccount_code": retailer.paystack_subaccount_code,
            "gross_amount": gross,
            "commission": commission,
            "net_amount": net,
            "share_kobo": int(round(net * 100)),
        })

    return splits


def create_transfer_recipient_sync(
    name: str,
    bank_code: str,
    account_number: str,
    currency: str = "NGN",
) -> dict:
    """Create a Paystack transfer recipient (synchronous)."""
    import requests

    secret = os.getenv("PAYSTACK_SECRET_KEY", "")
    if not secret:
        return {"success": False, "message": "Paystack not configured"}

    payload = {
        "type": "nuban",
        "name": name,
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": currency,
    }
    try:
        resp = requests.post(
            f"{PAYSTACK_API_BASE}/transferrecipient",
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status"):
            return {"success": True, "recipient_code": data["data"]["recipient_code"]}
        return {"success": False, "message": data.get("message", "Recipient creation failed")}
    except Exception as exc:
        logger.error("Paystack recipient creation error: %s", exc)
        return {"success": False, "message": str(exc)}


def initiate_transfer_sync(
    recipient_code: str,
    amount_kobo: int,
    reason: str = "Vendor payout",
    currency: str = "NGN",
) -> dict:
    """Initiate a Paystack transfer (synchronous)."""
    import requests

    secret = os.getenv("PAYSTACK_SECRET_KEY", "")
    if not secret:
        return {"success": False, "message": "Paystack not configured"}

    payload = {
        "source": "balance",
        "amount": amount_kobo,
        "recipient": recipient_code,
        "reason": reason,
        "currency": currency,
    }
    try:
        resp = requests.post(
            f"{PAYSTACK_API_BASE}/transfer",
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status"):
            return {
                "success": True,
                "transfer_code": data["data"].get("transfer_code", ""),
                "status": data["data"].get("status", "pending"),
            }
        return {"success": False, "message": data.get("message", "Transfer failed")}
    except Exception as exc:
        logger.error("Paystack transfer error: %s", exc)
        return {"success": False, "message": str(exc)}
