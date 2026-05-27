"""API router for Real-time Order Tracking — System 1"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.shipment_service import ShipmentService, TrackingService, DeliveryService

router = APIRouter(prefix="/api/orders", tags=["tracking"])


@router.get("/{order_id}/tracking")
def get_order_tracking(order_id: str, db: Session = Depends(get_db)):
    """Get tracking information for all shipments in an order."""
    shipment_service = ShipmentService(db)
    shipments = shipment_service.get_order_shipments(order_id)
    return {"shipments": [s.id for s in shipments], "count": len(shipments)}


@router.get("/tracking/{tracking_number}")
def get_tracking_by_number(tracking_number: str, db: Session = Depends(get_db)):
    """Get tracking info by tracking number."""
    tracking = TrackingService(db)
    info = tracking.get_tracking_info(tracking_number)
    if not info:
        raise HTTPException(status_code=404, detail="Tracking number not found")
    return info
