"""Logistics Portal — isolated router for LOGISTICS role users."""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models import (
    AdminUser, Shipment, ShipmentEvent, DeliveryAgent, Order,
    OrderItem, Product, Retailer, AdminRole
)
from app.auth import get_current_user_from_cookie, has_permission, AdminRole as AR, log_admin_action
from app.templates_shared import render_template
from app.utils import utcnow

router = APIRouter(tags=["logistics-portal"])


def _require_logistics(request: Request, db: Session):
    """Verify the current user has LOGISTICS role."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return None, RedirectResponse(url="/admin/login", status_code=302)
    role_val = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if role_val != "LOGISTICS" and role_val != AR.LOGISTICS.value:
        if role_val == "RETAILER":
            return admin, RedirectResponse(url="/vendor/dashboard", status_code=302)
        return admin, RedirectResponse(url="/admin/dashboard", status_code=302)
    return admin, None


@router.get("/logistics/dashboard", response_class=HTMLResponse)
def logistics_dashboard(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    total_shipments = db.query(func.count(Shipment.id)).scalar() or 0
    pending_shipments = db.query(func.count(Shipment.id)).filter(Shipment.status == "PENDING").scalar() or 0
    in_transit = db.query(func.count(Shipment.id)).filter(Shipment.status == "IN_TRANSIT").scalar() or 0
    delivered = db.query(func.count(Shipment.id)).filter(Shipment.status == "DELIVERED").scalar() or 0
    total_agents = db.query(func.count(DeliveryAgent.id)).scalar() or 0
    available_agents = db.query(func.count(DeliveryAgent.id)).filter(DeliveryAgent.status == "AVAILABLE").scalar() or 0

    recent_shipments = db.query(Shipment).order_by(desc(Shipment.created_at)).limit(10).all()

    return render_template("logistics/dashboard.html", {
        "request": request,
        "admin": admin,
        "total_shipments": total_shipments,
        "pending_shipments": pending_shipments,
        "in_transit": in_transit,
        "delivered": delivered,
        "total_agents": total_agents,
        "available_agents": available_agents,
        "recent_shipments": recent_shipments,
        "has_permission": has_permission,
    })


@router.get("/logistics/shipments", response_class=HTMLResponse)
def logistics_shipments(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    shipments = db.query(Shipment).order_by(desc(Shipment.created_at)).all()
    agents = {a.id: a.name for a in db.query(DeliveryAgent).all()}

    return render_template("logistics/shipments.html", {
        "request": request,
        "admin": admin,
        "shipments": shipments,
        "agents": agents,
        "has_permission": has_permission,
    })


@router.get("/logistics/drivers", response_class=HTMLResponse)
def logistics_drivers(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    drivers = db.query(DeliveryAgent).order_by(desc(DeliveryAgent.created_at)).all()

    return render_template("logistics/drivers.html", {
        "request": request,
        "admin": admin,
        "drivers": drivers,
        "has_permission": has_permission,
    })


@router.post("/logistics/drivers/new")
async def logistics_driver_new(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    form = await request.form()
    agent = DeliveryAgent(
        name=form.get("name", ""),
        phone=form.get("phone", ""),
        email=form.get("email", ""),
        vehicle_type=form.get("vehicle_type", ""),
        vehicle_number=form.get("vehicle_number", ""),
        status="AVAILABLE",
    )
    db.add(agent)
    db.commit()
    log_admin_action(db, admin, "create", "delivery_agent", agent.id, f"Created driver '{agent.name}'")

    return RedirectResponse(url="/logistics/drivers", status_code=302)


@router.post("/logistics/shipments/{shipment_id}/assign")
async def logistics_assign_driver(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    form = await request.form()
    agent_id = form.get("agent_id", "")
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if shipment and agent_id:
        shipment.delivery_agent_id = agent_id
        db.commit()

    return RedirectResponse(url="/logistics/shipments", status_code=302)
