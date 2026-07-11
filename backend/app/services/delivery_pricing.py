"""
Dynamic Delivery Pricing — distance + demand multiplier + weight calculator.
Calculates delivery fees based on Haversine distance between origin/destination,
current demand multiplier (peak hours, holidays), package weight, and zone pricing.
Zone rates and multipliers are read from admin DB settings (with hardcoded fallbacks).
"""
import math
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger("forgestore.delivery_pricing")


@dataclass
class PricingBreakdown:
    base_fee: float
    distance_km: float
    distance_fee: float
    weight_fee: float
    demand_multiplier: float
    demand_fee: float
    total_fee: float
    zone: str
    estimated_hours: float
    breakdown: dict


# ─── Nigerian Zone Pricing (Lagos-centric) ─────────────────────────────────
# Default zone rates — overridden by DB setting 'delivery_zone_rates' when set.

_DEFAULT_ZONE_RATES = {
    "same_state": {"base": 1000, "per_km": 50, "per_kg": 100, "hours": 4},
    "neighboring": {"base": 1500, "per_km": 80, "per_kg": 150, "hours": 24},
    "regional": {"base": 2500, "per_km": 120, "per_kg": 200, "hours": 48},
    "interstate": {"base": 4000, "per_km": 150, "per_kg": 250, "hours": 72},
}

_STATE_ZONES = {
    "lagos": "same_state",
    "abuja": "neighboring",
    "fct": "neighboring",
    "ogun": "neighboring",
    "oyo": "regional",
    "rivers": "regional",
    "kaduna": "regional",
    "kano": "interstate",
    "borno": "interstate",
    "enugu": "regional",
    "anambra": "regional",
    "delta": "regional",
    "edo": "regional",
}


def _get_zone_rates() -> dict:
    """Load zone rates from DB setting, falling back to defaults."""
    try:
        from app.config import get_db_setting
        raw = get_db_setting("delivery_zone_rates", "")
        if raw:
            parsed = json.loads(raw)
            # Merge with defaults so any missing zone gets the hardcoded value
            merged = dict(_DEFAULT_ZONE_RATES)
            merged.update(parsed)
            return merged
    except Exception as e:
        logger.warning(f"Failed to load delivery_zone_rates from DB: {e}")
    return dict(_DEFAULT_ZONE_RATES)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_demand_multiplier(dt: datetime = None) -> float:
    if dt is None:
        dt = datetime.now(timezone.utc)
    hour = dt.hour
    month = dt.month
    day = dt.day

    # Load multipliers from DB settings (with hardcoded defaults)
    try:
        from app.config import get_db_setting
        peak = float(get_db_setting("delivery_demand_peak_multiplier", "1.3"))
        late_night = float(get_db_setting("delivery_demand_late_night_multiplier", "1.5"))
        holiday = float(get_db_setting("delivery_demand_holiday_multiplier", "1.4"))
        weekend = float(get_db_setting("delivery_demand_weekend_multiplier", "1.1"))
    except Exception:
        peak, late_night, holiday, weekend = 1.3, 1.5, 1.4, 1.1

    multiplier = 1.0

    # Peak hours: 7-10am and 4-7pm
    if hour in (7, 8, 9, 16, 17, 18):
        multiplier = peak
    # Late night: 10pm-6am
    elif hour >= 22 or hour < 6:
        multiplier = late_night
    # Off-peak: 11am-3pm
    else:
        multiplier = 1.0

    # Holiday surcharge (Dec 20-26, Dec 31-Jan 2)
    if (month == 12 and 20 <= day <= 26) or (month == 12 and day == 31) or (month == 1 and day <= 2):
        multiplier *= holiday

    # Weekend slight premium
    if dt.weekday() >= 5:
        multiplier *= weekend

    return round(multiplier, 2)


def _detect_zone(origin: str, destination: str) -> str:
    origin_lower = origin.lower()
    dest_lower = destination.lower()

    for state, zone in _STATE_ZONES.items():
        if state in origin_lower:
            origin_zone = zone
            break
    else:
        origin_zone = "regional"

    for state, zone in _STATE_ZONES.items():
        if state in dest_lower:
            dest_zone = zone
            break
    else:
        dest_zone = "regional"

    if origin_zone == "same_state" and dest_zone == "same_state":
        return "same_state"
    if origin_zone in ("same_state", "neighboring") and dest_zone in ("same_state", "neighboring"):
        return "neighboring"
    if "interstate" in (origin_zone, dest_zone):
        return "interstate"
    return "regional"


def calculate_delivery_fee(
    origin: str = "",
    destination: str = "",
    weight_kg: float = 0.0,
    origin_lat: float = None,
    origin_lng: float = None,
    dest_lat: float = None,
    dest_lng: float = None,
    demand_multiplier: float = None,
    now: datetime = None,
) -> PricingBreakdown:
    """Calculate delivery fee based on distance, weight, demand, and zone."""
    zone = _detect_zone(origin, destination)
    zone_rates = _get_zone_rates()
    rates = zone_rates.get(zone, zone_rates.get("regional", {"base": 2500, "per_km": 120, "per_kg": 200, "hours": 48}))

    # Distance
    if origin_lat and origin_lng and dest_lat and dest_lng:
        distance_km = _haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
    else:
        distance_km = 0.0

    base_fee = rates["base"]
    distance_fee = round(distance_km * rates["per_km"], 2)
    weight_fee = round(max(0, weight_kg - 1) * rates["per_kg"], 2)

    if demand_multiplier is None:
        demand_multiplier = _get_demand_multiplier(now)
    demand_fee = round((base_fee + distance_fee + weight_fee) * (demand_multiplier - 1.0), 2)

    total = round(base_fee + distance_fee + weight_fee + demand_fee, 2)

    return PricingBreakdown(
        base_fee=base_fee,
        distance_km=round(distance_km, 2),
        distance_fee=distance_fee,
        weight_fee=weight_fee,
        demand_multiplier=demand_multiplier,
        demand_fee=demand_fee,
        total_fee=total,
        zone=zone,
        estimated_hours=rates["hours"],
        breakdown={
            "base": base_fee, "distance": distance_fee, "weight": weight_fee,
            "demand": demand_fee, "zone": zone, "multiplier": demand_multiplier,
        },
    )


def calculate_return_fee(
    original_fee: float = 0.0,
    weight_kg: float = 0.0,
    distance_km: float = 0.0,
) -> float:
    """Calculate return shipping fee — configurable ratio of original or flat rate."""
    try:
        from app.config import get_db_setting
        ratio = float(get_db_setting("delivery_return_fee_ratio", "0.6"))
        flat_fee = float(get_db_setting("delivery_return_flat_fee", "1500"))
    except Exception:
        ratio, flat_fee = 0.6, 1500.0
    if original_fee > 0:
        return round(original_fee * ratio, 2)
    return max(flat_fee, round(distance_km * 80 + max(0, weight_kg - 1) * 150, 2))
