"""
3PL Integration Service — Abstract provider layer for GIG Logistics, Kwik, ShapShap.
Each provider implements: create_shipment, track_shipment, cancel_shipment, get_quote.
All providers run in MOCK mode by default (env var or DB setting controls live vs mock).
"""
import os
import uuid
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

import httpx

logger = logging.getLogger("forgestore.three_pl")


# ─── Data Classes ───────────────────────────────────────────────────────────

@dataclass
class ShipmentQuote:
    provider: str
    service_type: str
    amount: float
    currency: str = "NGN"
    estimated_days: int = 0
    estimated_hours: float = 0.0
    description: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class ShipmentResult:
    provider: str
    tracking_number: str
    shipment_id: str
    status: str = "CREATED"
    estimated_delivery: str = ""
    cost: float = 0.0
    raw: dict = field(default_factory=dict)


@dataclass
class TrackingEvent:
    status: str
    location: str = ""
    description: str = ""
    timestamp: str = ""


@dataclass
class TrackingResult:
    provider: str
    tracking_number: str
    current_status: str
    events: list = field(default_factory=list)
    estimated_delivery: str = ""
    raw: dict = field(default_factory=dict)


# ─── Abstract Provider ──────────────────────────────────────────────────────

class ThreePLProvider(ABC):
    name: str = "base"
    base_url: str = ""
    sandbox_url: str = ""

    def __init__(self, api_key: str = "", sandbox: bool = True):
        self.api_key = api_key
        self.sandbox = sandbox
        self._base = self.sandbox_url if sandbox else self.base_url

    @abstractmethod
    async def create_shipment(self, origin: str, destination: str, weight_kg: float = 0.0,
                               dimensions: dict = None, recipient_name: str = "",
                               recipient_phone: str = "", recipient_email: str = "",
                               description: str = "", cod_amount: float = 0.0,
                               metadata: dict = None) -> ShipmentResult: ...

    @abstractmethod
    async def track_shipment(self, tracking_number: str) -> TrackingResult: ...

    @abstractmethod
    async def cancel_shipment(self, tracking_number: str, reason: str = "") -> dict: ...

    @abstractmethod
    async def get_quote(self, origin: str, destination: str, weight_kg: float = 0.0,
                         dimensions: dict = None) -> ShipmentQuote: ...

    @abstractmethod
    async def test_connection(self) -> dict: ...


# ─── Mock Provider ──────────────────────────────────────────────────────────

class MockProvider(ThreePLProvider):
    name = "mock"

    async def create_shipment(self, origin="", destination="", weight_kg=0.0,
                               dimensions=None, recipient_name="", recipient_phone="",
                               recipient_email="", description="", cod_amount=0.0,
                               metadata=None) -> ShipmentResult:
        tracking = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
        return ShipmentResult(
            provider=self.name, tracking_number=tracking, shipment_id=str(uuid.uuid4()),
            status="CREATED", estimated_delivery="2026-07-15T18:00:00Z", cost=2500.0,
            raw={"mock": True, "origin": origin, "destination": destination},
        )

    async def track_shipment(self, tracking_number: str) -> TrackingResult:
        return TrackingResult(
            provider=self.name, tracking_number=tracking_number, current_status="IN_TRANSIT",
            events=[
                {"status": "PICKED_UP", "location": "Lagos Hub", "description": "Package picked up", "timestamp": "2026-07-10T10:00:00Z"},
                {"status": "IN_TRANSIT", "location": "Abuja Hub", "description": "In transit", "timestamp": "2026-07-11T14:00:00Z"},
            ],
            estimated_delivery="2026-07-15T18:00:00Z", raw={"mock": True},
        )

    async def cancel_shipment(self, tracking_number: str, reason: str = "") -> dict:
        return {"ok": True, "status": "CANCELLED", "tracking_number": tracking_number}

    async def get_quote(self, origin="", destination="", weight_kg=0.0, dimensions=None) -> ShipmentQuote:
        base = 1500.0
        if weight_kg > 5:
            base += (weight_kg - 5) * 200
        return ShipmentQuote(
            provider=self.name, service_type="standard", amount=base,
            estimated_days=3, estimated_hours=72, description="Mock standard delivery",
        )

    async def test_connection(self) -> dict:
        return {"ok": True, "message": "Mock provider active", "provider": self.name}


# ─── GIG Logistics ──────────────────────────────────────────────────────────

class GIGLogisticsProvider(ThreePLProvider):
    name = "gig"

    def __init__(self, api_key: str = "", sandbox: bool = True):
        from app.config import get_db_setting
        db_key = get_db_setting("gig_api_key", "")
        db_base = get_db_setting("gig_base_url", "https://api.gigl.com/api/v1")
        db_sandbox = get_db_setting("gig_sandbox_url", "https://sandbox.gigl.com/api/v1")
        self.base_url = db_base
        self.sandbox_url = db_sandbox
        super().__init__(api_key=db_key or api_key, sandbox=sandbox)

    async def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self._base}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if method == "GET":
                    r = await client.get(url, headers=headers, params=data or {})
                else:
                    r = await client.post(url, headers=headers, json=data or {})
                return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def create_shipment(self, origin="", destination="", weight_kg=0.0,
                               dimensions=None, recipient_name="", recipient_phone="",
                               recipient_email="", description="", cod_amount=0.0,
                               metadata=None) -> ShipmentResult:
        payload = {"origin": origin, "destination": destination, "recipient_name": recipient_name,
                    "recipient_phone": recipient_phone, "description": description, "weight": weight_kg, "cod_amount": cod_amount}
        resp = await self._request("POST", "/shipments", payload)
        if "error" in resp:
            return ShipmentResult(provider=self.name, tracking_number="", shipment_id="", status="ERROR", raw=resp)
        d = resp.get("data", resp)
        return ShipmentResult(provider=self.name, tracking_number=d.get("tracking_number", ""),
                               shipment_id=d.get("id", ""), status=d.get("status", "CREATED"),
                               estimated_delivery=d.get("estimated_delivery", ""),
                               cost=float(d.get("cost", 0)), raw=resp)

    async def track_shipment(self, tracking_number: str) -> TrackingResult:
        resp = await self._request("GET", f"/shipments/{tracking_number}/track")
        if "error" in resp:
            return TrackingResult(provider=self.name, tracking_number=tracking_number, current_status="ERROR", raw=resp)
        d = resp.get("data", resp)
        events = [{"status": e.get("status", ""), "location": e.get("location", ""),
                    "description": e.get("description", ""), "timestamp": e.get("timestamp", "")}
                   for e in d.get("events", [])]
        return TrackingResult(provider=self.name, tracking_number=tracking_number,
                               current_status=d.get("current_status", "UNKNOWN"), events=events,
                               estimated_delivery=d.get("estimated_delivery", ""), raw=resp)

    async def cancel_shipment(self, tracking_number: str, reason: str = "") -> dict:
        return await self._request("POST", f"/shipments/{tracking_number}/cancel", {"reason": reason})

    async def get_quote(self, origin="", destination="", weight_kg=0.0, dimensions=None) -> ShipmentQuote:
        resp = await self._request("POST", "/shipments/quote", {"origin": origin, "destination": destination, "weight": weight_kg})
        if "error" in resp:
            return ShipmentQuote(provider=self.name, service_type="standard", amount=0, description=resp["error"])
        d = resp.get("data", resp)
        return ShipmentQuote(provider=self.name, service_type=d.get("service_type", "standard"),
                              amount=float(d.get("amount", 0)), estimated_days=d.get("estimated_days", 0), raw=resp)

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self._base}/health", headers={"Authorization": f"Bearer {self.api_key}"})
                return {"ok": r.status_code == 200, "status_code": r.status_code, "provider": self.name}
        except Exception as e:
            return {"ok": False, "error": str(e), "provider": self.name}


# ─── Kwik Delivery ──────────────────────────────────────────────────────────

class KwikDeliveryProvider(ThreePLProvider):
    name = "kwik"

    def __init__(self, api_key: str = "", sandbox: bool = True):
        from app.config import get_db_setting
        db_key = get_db_setting("kwik_api_key", "")
        db_base = get_db_setting("kwik_base_url", "https://api.kwik.delivery/v1")
        db_sandbox = get_db_setting("kwik_sandbox_url", "https://sandbox.kwik.delivery/v1")
        self.base_url = db_base
        self.sandbox_url = db_sandbox
        super().__init__(api_key=db_key or api_key, sandbox=sandbox)

    async def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self._base}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if method == "GET":
                    r = await client.get(url, headers=headers, params=data or {})
                else:
                    r = await client.post(url, headers=headers, json=data or {})
                return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def create_shipment(self, origin="", destination="", weight_kg=0.0,
                               dimensions=None, recipient_name="", recipient_phone="",
                               recipient_email="", description="", cod_amount=0.0,
                               metadata=None) -> ShipmentResult:
        payload = {"pickup_address": origin, "delivery_address": destination,
                    "recipient_name": recipient_name, "recipient_phone": recipient_phone,
                    "item_description": description, "item_weight": weight_kg, "cod_amount": cod_amount}
        resp = await self._request("POST", "/orders", payload)
        if "error" in resp:
            return ShipmentResult(provider=self.name, tracking_number="", shipment_id="", status="ERROR", raw=resp)
        d = resp.get("data", resp)
        return ShipmentResult(provider=self.name,
                               tracking_number=d.get("order_id", d.get("tracking_number", "")),
                               shipment_id=d.get("id", d.get("order_id", "")),
                               status=d.get("status", "CREATED"),
                               estimated_delivery=d.get("estimated_delivery", ""),
                               cost=float(d.get("total_cost", d.get("cost", 0))), raw=resp)

    async def track_shipment(self, tracking_number: str) -> TrackingResult:
        resp = await self._request("GET", f"/orders/{tracking_number}")
        if "error" in resp:
            return TrackingResult(provider=self.name, tracking_number=tracking_number, current_status="ERROR", raw=resp)
        d = resp.get("data", resp)
        events = [{"status": e.get("status", ""), "location": e.get("location", ""),
                    "description": e.get("description", ""), "timestamp": e.get("timestamp", "")}
                   for e in d.get("status_history", d.get("events", []))]
        return TrackingResult(provider=self.name, tracking_number=tracking_number,
                               current_status=d.get("status", "UNKNOWN"), events=events,
                               estimated_delivery=d.get("estimated_delivery", ""), raw=resp)

    async def cancel_shipment(self, tracking_number: str, reason: str = "") -> dict:
        return await self._request("POST", f"/orders/{tracking_number}/cancel", {"reason": reason})

    async def get_quote(self, origin="", destination="", weight_kg=0.0, dimensions=None) -> ShipmentQuote:
        resp = await self._request("POST", "/orders/quote", {"pickup_address": origin, "delivery_address": destination, "weight": weight_kg})
        if "error" in resp:
            return ShipmentQuote(provider=self.name, service_type="standard", amount=0, description=resp["error"])
        d = resp.get("data", resp)
        return ShipmentQuote(provider=self.name, service_type=d.get("service_type", "standard"),
                              amount=float(d.get("amount", d.get("total_cost", 0))),
                              estimated_days=d.get("estimated_days", 0), raw=resp)

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self._base}/health", headers={"Authorization": f"Bearer {self.api_key}"})
                return {"ok": r.status_code == 200, "status_code": r.status_code, "provider": self.name}
        except Exception as e:
            return {"ok": False, "error": str(e), "provider": self.name}


# ─── ShapShap ───────────────────────────────────────────────────────────────

class ShapShapProvider(ThreePLProvider):
    name = "shapshap"

    def __init__(self, api_key: str = "", sandbox: bool = True):
        from app.config import get_db_setting
        db_key = get_db_setting("shapshap_api_key", "")
        db_base = get_db_setting("shapshap_base_url", "https://api.shapshap.com/v1")
        db_sandbox = get_db_setting("shapshap_sandbox_url", "https://sandbox.shapshap.com/v1")
        self.base_url = db_base
        self.sandbox_url = db_sandbox
        super().__init__(api_key=db_key or api_key, sandbox=sandbox)

    async def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self._base}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if method == "GET":
                    r = await client.get(url, headers=headers, params=data or {})
                else:
                    r = await client.post(url, headers=headers, json=data or {})
                return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def create_shipment(self, origin="", destination="", weight_kg=0.0,
                               dimensions=None, recipient_name="", recipient_phone="",
                               recipient_email="", description="", cod_amount=0.0,
                               metadata=None) -> ShipmentResult:
        payload = {"pickup": origin, "dropoff": destination, "recipient_name": recipient_name,
                    "recipient_phone": recipient_phone, "description": description,
                    "weight": weight_kg, "cod_amount": cod_amount}
        resp = await self._request("POST", "/shipments", payload)
        if "error" in resp:
            return ShipmentResult(provider=self.name, tracking_number="", shipment_id="", status="ERROR", raw=resp)
        d = resp.get("data", resp)
        return ShipmentResult(provider=self.name, tracking_number=d.get("tracking_number", d.get("waybill", "")),
                               shipment_id=d.get("id", ""), status=d.get("status", "CREATED"),
                               estimated_delivery=d.get("estimated_delivery", ""),
                               cost=float(d.get("cost", d.get("price", 0))), raw=resp)

    async def track_shipment(self, tracking_number: str) -> TrackingResult:
        resp = await self._request("GET", f"/shipments/{tracking_number}")
        if "error" in resp:
            return TrackingResult(provider=self.name, tracking_number=tracking_number, current_status="ERROR", raw=resp)
        d = resp.get("data", resp)
        events = [{"status": e.get("status", ""), "location": e.get("location", ""),
                    "description": e.get("description", ""), "timestamp": e.get("timestamp", "")}
                   for e in d.get("events", d.get("tracking", []))]
        return TrackingResult(provider=self.name, tracking_number=tracking_number,
                               current_status=d.get("status", "UNKNOWN"), events=events,
                               estimated_delivery=d.get("estimated_delivery", ""), raw=resp)

    async def cancel_shipment(self, tracking_number: str, reason: str = "") -> dict:
        return await self._request("POST", f"/shipments/{tracking_number}/cancel", {"reason": reason})

    async def get_quote(self, origin="", destination="", weight_kg=0.0, dimensions=None) -> ShipmentQuote:
        resp = await self._request("POST", "/shipments/quote", {"pickup": origin, "dropoff": destination, "weight": weight_kg})
        if "error" in resp:
            return ShipmentQuote(provider=self.name, service_type="standard", amount=0, description=resp["error"])
        d = resp.get("data", resp)
        return ShipmentQuote(provider=self.name, service_type=d.get("service_type", "standard"),
                              amount=float(d.get("amount", d.get("price", 0))),
                              estimated_days=d.get("estimated_days", 0), raw=resp)

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self._base}/health", headers={"Authorization": f"Bearer {self.api_key}"})
                return {"ok": r.status_code == 200, "status_code": r.status_code, "provider": self.name}
        except Exception as e:
            return {"ok": False, "error": str(e), "provider": self.name}


# ─── Provider Registry ──────────────────────────────────────────────────────

_PROVIDERS = {
    "mock": MockProvider,
    "gig": GIGLogisticsProvider,
    "kwik": KwikDeliveryProvider,
    "shapshap": ShapShapProvider,
}


def get_3pl_provider(name: str = None, api_key: str = "", sandbox: bool = None) -> ThreePLProvider:
    """Factory: returns the requested provider (defaults to DB/ env config)."""
    from app.config import get_db_setting
    if sandbox is None:
        sandbox_val = get_db_setting("three_pl_sandbox", os.getenv("THREE_PL_SANDBOX", "true"))
        sandbox = sandbox_val.lower() in ("true", "1", "t")
    if not name:
        name = get_db_setting("three_pl_provider", os.getenv("THREE_PL_PROVIDER", "mock"))
    cls = _PROVIDERS.get(name, MockProvider)
    return cls(api_key=api_key, sandbox=sandbox)


def list_providers() -> list:
    return [{"id": k, "name": cls.__name__} for k, cls in _PROVIDERS.items() if k != "mock"]
