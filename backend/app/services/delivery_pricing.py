"""
Dynamic Delivery Pricing — distance + demand multiplier + weight calculator.
Calculates delivery fees based on Haversine distance between origin/destination,
current demand multiplier (peak hours, holidays), package weight, and zone pricing.
"""
import math
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

_ZONE_RATES = {
    "same_state": {"base": 1000, "per_km": 50, "per_kg": 100, "hours": 4},
    "neighboring": {"base": 1500, "per_km": 80, "per_kg": 150, "hours": 24},
    "regional": {"base": 2500, "per_km": 120, "per_kg": 200, "hours": 48},
    "interstate": {"base": 4000, "per_km": 150, "per_kg": 250, "hours": 72},
}


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

    multiplier = 1.0

    # Peak hours: 7-10am and 4-7pm = 1.3x
    if hour in (7, 8, 9, 16, 17, 18):
        multiplier = 1.3
    # Late night: 10pm-6am = 1.5x
    elif hour >= 22 or hour < 6:
        multiplier = 1.5
    # Off-peak: 11am-3pm = 1.0x
    else:
        multiplier = 1.0

    # Holiday surcharge (Dec 20-26, Dec 31-Jan 2)
    if (month == 12 and 20 <= day <= 26) or (month == 12 and day == 31) or (month == 1 and day <= 2):
        multiplier *= 1.4

    # Weekend slight premium
    if dt.weekday() >= 5:
        multiplier *= 1.1

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
    rates = _ZONE_RATES[zone]

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
    """Calculate return shipping fee — 60% of original or flat rate."""
    if original_fee > 0:
        return round(original_fee * 0.6, 2)
    return max(1500.0, round(distance_km * 80 + max(0, weight_kg - 1) * 150, 2))
