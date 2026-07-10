"""Logistics Portal — isolated router for LOGISTICS role users."""
import json
import math
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models import (
    AdminUser, Shipment, ShipmentEvent, DeliveryAgent, Order,
    OrderItem, Product, Retailer, AdminRole, PickupPoint, PickupInventory
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
    unassigned_count = db.query(func.count(Shipment.id)).filter(Shipment.delivery_agent_id.is_(None), Shipment.status == "PENDING").scalar() or 0
    platform_fulfilled = db.query(func.count(Order.id)).filter(Order.fulfillment_mode == "PLATFORM", Order.status.in_(["PAID", "PROCESSING"])).scalar() or 0

    cod_shipments = db.query(Shipment).join(Order).filter(
        Order.payment_method == "cod",
        Shipment.status.in_(["PENDING", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"])
    ).all()
    cod_pending_count = len(cod_shipments)
    cod_pending_total = sum(s.order.total_amount for s in cod_shipments if s.order)

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
        "unassigned_count": unassigned_count,
        "platform_fulfilled": platform_fulfilled,
        "cod_pending_count": cod_pending_count,
        "cod_pending_total": cod_pending_total,
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


@router.get("/logistics/notifications", response_class=HTMLResponse)
def logistics_notifications(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect
    return render_template("logistics/notifications.html", {
        "request": request, "admin": admin,
        "has_permission": has_permission,
    })


@router.get("/logistics/shipments/{shipment_id}", response_class=HTMLResponse)
def logistics_shipment_detail(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        return RedirectResponse(url="/logistics/shipments", status_code=302)

    events = db.query(ShipmentEvent).filter(
        ShipmentEvent.shipment_id == shipment.id
    ).order_by(ShipmentEvent.timestamp.desc()).all()

    available_drivers = db.query(DeliveryAgent).filter(
        DeliveryAgent.status == "AVAILABLE"
    ).all()

    return render_template("logistics/shipment_detail.html", {
        "request": request,
        "admin": admin,
        "shipment": shipment,
        "events": events,
        "available_drivers": available_drivers,
        "has_permission": has_permission,
    })


@router.post("/logistics/shipments/{shipment_id}/status")
async def logistics_update_shipment_status(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    form = await request.form()
    status = form.get("status", "")
    location = form.get("location", "")
    description = form.get("description", "")

    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if shipment:
        old_status = shipment.status
        shipment.status = status
        if status == "DELIVERED":
            shipment.actual_delivery = utcnow()

        event = ShipmentEvent(
            shipment_id=shipment.id,
            status=status,
            location=location or None,
            description=description or None,
        )
        db.add(event)
        db.commit()
        log_admin_action(db, admin, "update", "shipment", shipment.id, f"Status {old_status} -> {status}")

        # Automated customer/vendor notifications
        try:
            from app.services.shipment_service import ShipmentService
            svc = ShipmentService(db)
            await svc._send_status_notifications(shipment, old_status, status)
        except Exception:
            logger.warning("Failed to send status notifications for shipment %s", shipment_id)

    return RedirectResponse(url=f"/logistics/shipments/{shipment_id}", status_code=302)


@router.post("/logistics/shipments/{shipment_id}/unassign")
async def logistics_unassign_driver(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if shipment:
        shipment.delivery_agent_id = None
        db.commit()
        log_admin_action(db, admin, "update", "shipment", shipment.id, "Unassigned driver")

    return RedirectResponse(url=f"/logistics/shipments/{shipment_id}", status_code=302)


@router.post("/logistics/drivers/{driver_id}/status")
async def logistics_toggle_driver_status(driver_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    form = await request.form()
    new_status = form.get("status", "AVAILABLE")

    driver = db.query(DeliveryAgent).filter(DeliveryAgent.id == driver_id).first()
    if driver:
        driver.status = new_status
        db.commit()
        log_admin_action(db, admin, "update", "delivery_agent", driver.id, f"Status → {new_status}")

    return RedirectResponse(url="/logistics/drivers", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2: SMART TOOLS
# ─────────────────────────────────────────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lng points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _estimate_drive_minutes(distance_km):
    """Rough city drive estimate: 25 km/h average."""
    return max(5, int(distance_km / 25 * 60))


# ─── LIVE MAP ────────────────────────────────────────────────────────────────

@router.get("/logistics/live-map", response_class=HTMLResponse)
def logistics_live_map(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    drivers = db.query(DeliveryAgent).all()
    driver_data = []
    for d in drivers:
        driver_data.append({
            "id": d.id,
            "name": d.name,
            "vehicle": f"{d.vehicle_type or ''} {d.vehicle_number or ''}".strip() or "On foot",
            "status": d.status,
            "rating": round(d.rating, 1),
            "lat": d.current_latitude,
            "lng": d.current_longitude,
            "last_update": d.last_location_update.strftime("%b %d, %H:%M") if d.last_location_update else "No data",
        })

    return render_template("logistics/live_map.html", {
        "request": request,
        "admin": admin,
        "drivers_json": json.dumps(driver_data),
        "has_permission": has_permission,
    })


@router.get("/logistics/api/drivers/locations")
def logistics_api_driver_locations(request: Request, db: Session = Depends(get_db)):
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    drivers = db.query(DeliveryAgent).all()
    data = []
    for d in drivers:
        data.append({
            "id": d.id,
            "name": d.name,
            "vehicle": f"{d.vehicle_type or ''} {d.vehicle_number or ''}".strip() or "On foot",
            "status": d.status,
            "rating": round(d.rating, 1),
            "lat": d.current_latitude,
            "lng": d.current_longitude,
            "last_update": d.last_location_update.strftime("%b %d, %H:%M") if d.last_location_update else "No data",
        })
    return JSONResponse(data)


# ─── ROUTE OPTIMIZER ─────────────────────────────────────────────────────────

@router.get("/logistics/tools/route-optimizer", response_class=HTMLResponse)
def logistics_route_optimizer(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    drivers = db.query(DeliveryAgent).order_by(DeliveryAgent.name).all()
    selected_driver = None
    optimized_route = None

    driver_id = request.query_params.get("driver_id")
    if driver_id:
        selected_driver = db.query(DeliveryAgent).filter(DeliveryAgent.id == driver_id).first()
        if selected_driver:
            shipments = db.query(Shipment).filter(
                Shipment.delivery_agent_id == selected_driver.id,
                Shipment.status.in_(["PENDING", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"])
            ).all()

            stops = []
            for s in shipments:
                dest = s.destination or ""
                order = s.order
                order_num = order.order_number if order else "N/A"
                lat = None
                lng = None
                if order and order.shipping_address:
                    lat = order.shipping_address.get("latitude")
                    lng = order.shipping_address.get("longitude")
                stops.append({
                    "shipment_id": s.id,
                    "tracking_number": s.tracking_number,
                    "order_number": order_num,
                    "destination": dest,
                    "lat": float(lat) if lat else None,
                    "lng": float(lng) if lng else None,
                    "distance_km": 0.0,
                    "eta_minutes": 0,
                })

            driver_lat = selected_driver.current_latitude or 6.5244
            driver_lng = selected_driver.current_longitude or 3.3792
            current_lat, current_lng = driver_lat, driver_lng
            ordered = []
            remaining = list(stops)
            while remaining:
                best_idx = 0
                best_dist = float("inf")
                for i, s in enumerate(remaining):
                    if s["lat"] is not None and s["lng"] is not None:
                        dist = _haversine_km(current_lat, current_lng, s["lat"], s["lng"])
                    else:
                        dist = 50.0
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = i
                stop = remaining.pop(best_idx)
                stop["distance_km"] = best_dist if best_dist < 50 else 0
                stop["eta_minutes"] = _estimate_drive_minutes(stop["distance_km"]) if stop["distance_km"] > 0 else 0
                ordered.append(stop)
                if stop["lat"] is not None and stop["lng"] is not None:
                    current_lat, current_lng = stop["lat"], stop["lng"]

            total_dist = sum(s["distance_km"] for s in ordered)
            total_eta = sum(s["eta_minutes"] for s in ordered)
            optimized_route = {
                "stops": ordered,
                "total_stops": len(ordered),
                "total_distance_km": total_dist,
                "total_eta_minutes": total_eta,
            }

    return render_template("logistics/route_optimizer.html", {
        "request": request,
        "admin": admin,
        "drivers": drivers,
        "selected_driver": selected_driver,
        "optimized_route": optimized_route,
        "has_permission": has_permission,
    })


# ─── DELIVERY PHOTO PROOF ────────────────────────────────────────────────────

@router.post("/logistics/shipments/{shipment_id}/proof")
async def logistics_upload_proof(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    form = await request.form()
    photo = form.get("proof_photo")

    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if shipment and photo:
        from app.core.cloudinary_upload import is_cloudinary_configured, upload_to_cloudinary
        from app.core.image_compressor import compress_image

        contents = await photo.read()
        compressed = compress_image(contents, max_size_bytes=200000)

        if is_cloudinary_configured():
            url = upload_to_cloudinary(compressed, folder="forgestore/proofs")
        else:
            import base64
            url = f"data:image/jpeg;base64,{base64.b64encode(compressed).decode()}"

        shipment.proof_photo_url = url
        shipment.status = "DELIVERED"
        shipment.actual_delivery = utcnow()

        event = ShipmentEvent(
            shipment_id=shipment.id,
            status="DELIVERED",
            description="Delivery completed with photo proof",
        )
        db.add(event)
        db.commit()
        log_admin_action(db, admin, "update", "shipment", shipment.id, "Uploaded delivery proof")

    return RedirectResponse(url=f"/logistics/shipments/{shipment_id}", status_code=302)


# ─── PERFORMANCE DASHBOARD ───────────────────────────────────────────────────

@router.get("/logistics/tools/performance", response_class=HTMLResponse)
def logistics_performance(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    agents = db.query(DeliveryAgent).order_by(desc(DeliveryAgent.rating)).all()

    driver_stats = []
    for d in agents:
        delivered = db.query(Shipment).filter(
            Shipment.delivery_agent_id == d.id,
            Shipment.status == "DELIVERED"
        ).all()
        failed = db.query(Shipment).filter(
            Shipment.delivery_agent_id == d.id,
            Shipment.status.in_(["FAILED", "RETURNED"])
        ).count()
        total = d.total_deliveries or 0
        success_count = len(delivered)
        avg_hours = 0.0
        if delivered:
            times = []
            for s in delivered:
                if s.actual_delivery and s.created_at:
                    delta = (s.actual_delivery - s.created_at).total_seconds() / 3600
                    times.append(delta)
            avg_hours = sum(times) / len(times) if times else 0.0

        driver_stats.append({
            "id": d.id,
            "name": d.name,
            "vehicle_type": d.vehicle_type,
            "vehicle_number": d.vehicle_number,
            "rating": d.rating,
            "total_deliveries": total,
            "success_count": success_count,
            "failed_count": failed,
            "avg_hours": avg_hours,
        })

    total_deliveries = sum(d["total_deliveries"] for d in driver_stats)
    total_success = sum(d["success_count"] for d in driver_stats)
    avg_rating = sum(d["rating"] for d in driver_stats) / len(driver_stats) if driver_stats else 0
    avg_delivery_hours = sum(d["avg_hours"] for d in driver_stats) / len(driver_stats) if driver_stats else 0
    success_rate = (total_success / total_deliveries * 100) if total_deliveries > 0 else 0

    driver_stats.sort(key=lambda x: (x["rating"] * 0.5 + (x["success_count"] / max(x["total_deliveries"], 1) * 100) * 0.5), reverse=True)

    return render_template("logistics/performance.html", {
        "request": request,
        "admin": admin,
        "drivers": driver_stats,
        "stats": {
            "avg_rating": avg_rating,
            "avg_delivery_hours": avg_delivery_hours,
            "success_rate": success_rate,
            "total_deliveries": total_deliveries,
        },
        "has_permission": has_permission,
    })


# ─── PICKUP POINTS ───────────────────────────────────────────────────────────

@router.get("/logistics/pickup-points", response_class=HTMLResponse)
def logistics_pickup_points(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    points = db.query(PickupPoint).order_by(desc(PickupPoint.created_at)).all()

    return render_template("logistics/pickup_points.html", {
        "request": request,
        "admin": admin,
        "points": points,
        "has_permission": has_permission,
    })


@router.post("/logistics/pickup-points/new")
async def logistics_pickup_point_new(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    form = await request.form()
    point = PickupPoint(
        name=form.get("name", ""),
        address=form.get("address", ""),
        latitude=float(form["latitude"]) if form.get("latitude") else None,
        longitude=float(form["longitude"]) if form.get("longitude") else None,
        phone=form.get("phone", ""),
        operating_hours=form.get("operating_hours", ""),
        is_active=True,
    )
    db.add(point)
    db.commit()
    log_admin_action(db, admin, "create", "pickup_point", point.id, f"Created pickup point '{point.name}'")

    return RedirectResponse(url="/logistics/pickup-points", status_code=302)


@router.get("/logistics/pickup-points/{point_id}/edit", response_class=HTMLResponse)
def logistics_pickup_point_edit(point_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    point = db.query(PickupPoint).filter(PickupPoint.id == point_id).first()
    if not point:
        return RedirectResponse(url="/logistics/pickup-points", status_code=302)

    return render_template("logistics/pickup_point_edit.html", {
        "request": request,
        "admin": admin,
        "point": point,
        "has_permission": has_permission,
    })


@router.post("/logistics/pickup-points/{point_id}/update")
async def logistics_pickup_point_update(point_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    form = await request.form()
    point = db.query(PickupPoint).filter(PickupPoint.id == point_id).first()
    if point:
        point.name = form.get("name", point.name)
        point.address = form.get("address", point.address)
        point.latitude = float(form["latitude"]) if form.get("latitude") else point.latitude
        point.longitude = float(form["longitude"]) if form.get("longitude") else point.longitude
        point.phone = form.get("phone", point.phone)
        point.operating_hours = form.get("operating_hours", point.operating_hours)
        db.commit()
        log_admin_action(db, admin, "update", "pickup_point", point.id, f"Updated pickup point '{point.name}'")

    return RedirectResponse(url=f"/logistics/pickup-points/{point_id}/edit", status_code=302)


@router.post("/logistics/pickup-points/{point_id}/toggle")
async def logistics_pickup_point_toggle(point_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    point = db.query(PickupPoint).filter(PickupPoint.id == point_id).first()
    if point:
        point.is_active = not point.is_active
        db.commit()
        log_admin_action(db, admin, "update", "pickup_point", point.id, f"{'Activated' if point.is_active else 'Deactivated'}")

    return RedirectResponse(url="/logistics/pickup-points", status_code=302)


@router.post("/logistics/pickup-points/{point_id}/inventory/add")
async def logistics_pickup_inventory_add(point_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    form = await request.form()
    product_id = form.get("product_id", "")
    quantity = int(form.get("quantity", 1))

    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        existing = db.query(PickupInventory).filter(
            PickupInventory.pickup_point_id == point_id,
            PickupInventory.product_id == product_id
        ).first()
        if existing:
            existing.quantity += quantity
        else:
            inv = PickupInventory(
                pickup_point_id=point_id,
                product_id=product_id,
                quantity=quantity,
                reserved=0,
            )
            db.add(inv)
        db.commit()

    return RedirectResponse(url=f"/logistics/pickup-points/{point_id}/edit", status_code=302)


@router.post("/logistics/pickup-points/{point_id}/inventory/{inv_id}/remove")
async def logistics_pickup_inventory_remove(point_id: str, inv_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    inv = db.query(PickupInventory).filter(PickupInventory.id == inv_id).first()
    if inv:
        db.delete(inv)
        db.commit()

    return RedirectResponse(url=f"/logistics/pickup-points/{point_id}/edit", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# SMART STRATEGY: AUTO-ASSIGN, BATCH, PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/logistics/api/auto-assign/{shipment_id}")
def logistics_auto_assign(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    """Auto-assign the nearest available driver to a shipment using GPS proximity."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        return JSONResponse({"error": "shipment not found"}, status_code=404)

    order = shipment.order
    dest_lat = None
    dest_lng = None
    if order and order.shipping_address:
        dest_lat = order.shipping_address.get("latitude")
        dest_lng = order.shipping_address.get("longitude")

    if dest_lat is None or dest_lng is None:
        return JSONResponse({"error": "no destination coordinates available"}, status_code=400)

    available = db.query(DeliveryAgent).filter(DeliveryAgent.status == "AVAILABLE").all()
    if not available:
        return JSONResponse({"error": "no available drivers"}, status_code=400)

    best_driver = None
    best_score = -1
    for d in available:
        if d.current_latitude and d.current_longitude:
            dist = _haversine_km(d.current_latitude, d.current_longitude, float(dest_lat), float(dest_lng))
            proximity_score = max(0, 100 - dist)
        else:
            proximity_score = 50

        perf = d.performance_score or 0
        combined = proximity_score * 0.6 + perf * 0.4

        if combined > best_score:
            best_score = combined
            best_driver = d

    if not best_driver:
        return JSONResponse({"error": "no suitable driver found"}, status_code=400)

    shipment.delivery_agent_id = best_driver.id
    shipment.status = "PICKED_UP"
    event = ShipmentEvent(
        shipment_id=shipment.id,
        status="PICKED_UP",
        description=f"Auto-assigned to {best_driver.name} (score: {best_score:.1f})",
    )
    db.add(event)
    db.commit()
    log_admin_action(db, admin, "update", "shipment", shipment.id, f"Auto-assigned to {best_driver.name}")

    return JSONResponse({"ok": True, "driver": best_driver.name, "score": round(best_score, 1)})


@router.post("/logistics/api/batch-assign")
def logistics_batch_assign(request: Request, db: Session = Depends(get_db)):
    """Batch-assign shipments to drivers using nearest-neighbor grouping."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    unassigned = db.query(Shipment).filter(
        Shipment.delivery_agent_id.is_(None),
        Shipment.status.in_(["PENDING", "PICKED_UP"])
    ).all()

    candidates = []
    for s in unassigned:
        order = s.order
        if order and order.shipping_address:
            lat = order.shipping_address.get("latitude")
            lng = order.shipping_address.get("longitude")
            if lat and lng:
                candidates.append({"shipment": s, "lat": float(lat), "lng": float(lng)})

    if not candidates:
        return JSONResponse({"ok": True, "assigned": 0, "message": "no assignable shipments"})

    available = db.query(DeliveryAgent).filter(DeliveryAgent.status == "AVAILABLE").all()
    if not available:
        return JSONResponse({"ok": True, "assigned": 0, "message": "no available drivers"})

    available.sort(key=lambda d: d.performance_score or 0, reverse=True)

    assigned_count = 0
    used_shipments = set()

    for driver in available:
        if driver.current_latitude is None or driver.current_longitude is None:
            continue

        remaining = [c for c in candidates if c["shipment"].id not in used_shipments]
        if not remaining:
            break

        best = min(remaining, key=lambda c: _haversine_km(
            driver.current_latitude, driver.current_longitude, c["lat"], c["lng"]
        ))
        dist = _haversine_km(driver.current_latitude, driver.current_longitude, best["lat"], best["lng"])

        if dist <= 30:
            best["shipment"].delivery_agent_id = driver.id
            best["shipment"].status = "PICKED_UP"
            event = ShipmentEvent(
                shipment_id=best["shipment"].id,
                status="PICKED_UP",
                description=f"Batch-assigned to {driver.name} ({dist:.1f}km away)",
            )
            db.add(event)
            used_shipments.add(best["shipment"].id)
            assigned_count += 1
            driver.status = "BUSY"

    db.commit()
    return JSONResponse({"ok": True, "assigned": assigned_count})


@router.post("/logistics/api/recalculate-performance")
def logistics_recalculate_performance(request: Request, db: Session = Depends(get_db)):
    """Recalculate performance scores for all drivers."""
    admin = get_current_user_from_cookie(request, db)
    if not admin:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    agents = db.query(DeliveryAgent).all()
    for d in agents:
        total = d.total_deliveries or 0
        if total == 0:
            d.performance_score = 0
            continue

        delivered = db.query(Shipment).filter(
            Shipment.delivery_agent_id == d.id,
            Shipment.status == "DELIVERED"
        ).count()

        delivered_shipments = db.query(Shipment).filter(
            Shipment.delivery_agent_id == d.id,
            Shipment.status == "DELIVERED"
        ).all()
        hours_list = []
        for s in delivered_shipments:
            if s.actual_delivery and s.created_at:
                h = (s.actual_delivery - s.created_at).total_seconds() / 3600
                hours_list.append(h)
        avg_hours = sum(hours_list) / len(hours_list) if hours_list else 24.0

        d.successful_deliveries = delivered
        d.avg_delivery_hours = avg_hours

        success_rate = (delivered / total * 100) if total > 0 else 0
        rating_score = (d.rating / 5.0 * 100) if d.rating else 50
        speed_score = max(0, 100 - (avg_hours * 5))

        d.performance_score = (
            success_rate * 0.4 +
            rating_score * 0.3 +
            speed_score * 0.3
        )

    db.commit()
    return JSONResponse({"ok": True, "drivers": len(agents)})


@router.get("/logistics/tools/batch-assign", response_class=HTMLResponse)
def logistics_batch_assign_page(request: Request, db: Session = Depends(get_db)):
    """Batch assignment dashboard."""
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    unassigned = db.query(Shipment).filter(
        Shipment.delivery_agent_id.is_(None),
        Shipment.status.in_(["PENDING", "PICKED_UP"])
    ).all()

    available = db.query(DeliveryAgent).filter(DeliveryAgent.status == "AVAILABLE").all()

    groups = []
    used = set()
    for s in unassigned:
        if s.id in used:
            continue
        order = s.order
        if not order or not order.shipping_address:
            continue
        lat = order.shipping_address.get("latitude")
        lng = order.shipping_address.get("longitude")
        if not lat or not lng:
            continue

        group = {"center_lat": float(lat), "center_lng": float(lng), "shipments": [s]}
        used.add(s.id)

        for s2 in unassigned:
            if s2.id in used:
                continue
            o2 = s2.order
            if not o2 or not o2.shipping_address:
                continue
            lat2 = o2.shipping_address.get("latitude")
            lng2 = o2.shipping_address.get("longitude")
            if not lat2 or not lng2:
                continue

            dist = _haversine_km(float(lat), float(lng), float(lat2), float(lng2))
            if dist <= 5:
                group["shipments"].append(s2)
                used.add(s2.id)

        if len(group["shipments"]) >= 2:
            groups.append(group)

    return render_template("logistics/batch_assign.html", {
        "request": request,
        "admin": admin,
        "unassigned_count": len(unassigned),
        "available_drivers": len(available),
        "groups": groups,
        "has_permission": has_permission,
    })


# ==============================================================================
# RETURNS LOGISTICS
# ==============================================================================

@router.get("/logistics/returns", response_class=HTMLResponse)
def logistics_returns(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    from app.models import ReturnRequest
    status_filter = request.query_params.get("status", "")
    q = db.query(ReturnRequest).order_by(desc(ReturnRequest.created_at))
    if status_filter:
        q = q.filter(ReturnRequest.status == status_filter)
    returns = q.limit(100).all()

    pending = db.query(func.count(ReturnRequest.id)).filter(ReturnRequest.status == "PENDING").scalar() or 0
    in_transit = db.query(func.count(ReturnRequest.id)).filter(ReturnRequest.status.in_(["APPROVED", "PICKUP_SCHEDULED", "IN_TRANSIT"])).scalar() or 0
    received = db.query(func.count(ReturnRequest.id)).filter(ReturnRequest.status == "RECEIVED").scalar() or 0

    return render_template("logistics/returns.html", {
        "request": request, "admin": admin, "returns": returns,
        "pending": pending, "in_transit_returns": in_transit, "received": received,
        "status_filter": status_filter, "has_permission": has_permission,
    })


@router.get("/logistics/returns/{return_id}", response_class=HTMLResponse)
def logistics_return_detail(return_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    from app.models import ReturnRequest, ReturnEvent
    rr = db.query(ReturnRequest).filter(ReturnRequest.id == return_id).first()
    if not rr:
        return RedirectResponse(url="/logistics/returns", status_code=302)

    events = db.query(ReturnEvent).filter(ReturnEvent.return_id == rr.id).order_by(ReturnEvent.created_at).all()
    from app.models import DeliveryAgent
    available_drivers = db.query(DeliveryAgent).filter(DeliveryAgent.status == "AVAILABLE").all()

    return render_template("logistics/return_detail.html", {
        "request": request, "admin": admin, "rr": rr, "events": events,
        "available_drivers": available_drivers, "has_permission": has_permission,
    })


@router.post("/logistics/returns/{return_id}/status")
async def logistics_update_return_status(return_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    from app.models import ReturnRequest, ReturnEvent
    form = await request.form()
    new_status = form.get("status", "")
    notes = form.get("notes", "")

    rr = db.query(ReturnRequest).filter(ReturnRequest.id == return_id).first()
    if not rr:
        return RedirectResponse(url="/logistics/returns", status_code=302)

    old_status = rr.status
    rr.status = new_status
    if new_status == "RECEIVED":
        rr.received_date = utcnow()
    if notes:
        rr.resolution_notes = notes

    event = ReturnEvent(return_id=rr.id, status=new_status, description=notes or f"Status {old_status} -> {new_status}", created_by=admin.email if admin else None)
    db.add(event)
    db.commit()
    log_admin_action(db, admin, "update", "return_request", rr.id, f"Return status {old_status} -> {new_status}")

    return RedirectResponse(url=f"/logistics/returns/{return_id}", status_code=302)


@router.post("/logistics/returns/{return_id}/assign")
async def logistics_assign_return(return_id: str, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    from app.models import ReturnRequest, ReturnEvent
    form = await request.form()
    agent_id = form.get("agent_id", "")

    rr = db.query(ReturnRequest).filter(ReturnRequest.id == return_id).first()
    if rr:
        rr.return_carrier = "internal"
        rr.status = "PICKUP_SCHEDULED"
        event = ReturnEvent(return_id=rr.id, status="PICKUP_SCHEDULED", description=f"Driver assigned for return pickup", created_by=admin.email if admin else None)
        db.add(event)
        db.commit()

    return RedirectResponse(url=f"/logistics/returns/{return_id}", status_code=302)


# ==============================================================================
# DYNAMIC PRICING
# ==============================================================================

@router.get("/logistics/pricing", response_class=HTMLResponse)
def logistics_pricing(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    return render_template("logistics/pricing.html", {
        "request": request, "admin": admin, "has_permission": has_permission,
    })


@router.get("/logistics/api/quote")
async def logistics_get_quote(request: Request):
    origin = request.query_params.get("origin", "")
    destination = request.query_params.get("destination", "")
    weight = float(request.query_params.get("weight", 0))

    from app.services.delivery_pricing import calculate_delivery_fee
    result = calculate_delivery_fee(origin=origin, destination=destination, weight_kg=weight)

    return JSONResponse({
        "base_fee": result.base_fee,
        "distance_km": result.distance_km,
        "distance_fee": result.distance_fee,
        "weight_fee": result.weight_fee,
        "demand_multiplier": result.demand_multiplier,
        "demand_fee": result.demand_fee,
        "total_fee": result.total_fee,
        "zone": result.zone,
        "estimated_hours": result.estimated_hours,
    })


# ==============================================================================
# 3PL INTEGRATION
# ==============================================================================

@router.get("/logistics/3pl", response_class=HTMLResponse)
def logistics_3pl_settings(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return redirect

    from app.models import Settings
    settings = {}
    for s in db.query(Settings).all():
        settings[s.key] = s.value

    from app.services.three_pl_service import list_providers
    providers = list_providers()

    return render_template("logistics/3pl_settings.html", {
        "request": request, "admin": admin, "settings": settings,
        "providers": providers, "has_permission": has_permission,
    })


@router.post("/logistics/api/3pl/test")
async def logistics_3pl_test(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    provider_name = body.get("provider", "mock")
    api_key = body.get("api_key", "")

    from app.services.three_pl_service import get_3pl_provider
    provider = get_3pl_provider(provider_name, api_key=api_key, sandbox=True)
    result = await provider.test_connection()
    return JSONResponse(result)


@router.post("/logistics/api/3pl/save")
async def logistics_3pl_save(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    from app.models import Settings
    for key in ["3pl_provider", "3pl_api_key", "3pl_sandbox"]:
        val = body.get(key)
        if val is not None:
            setting = db.query(Settings).filter(Settings.key == key).first()
            if setting:
                setting.value = str(val)
            else:
                db.add(Settings(key=key, value=str(val)))
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/logistics/api/3pl/create-shipment")
async def logistics_3pl_create_shipment(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_logistics(request, db)
    if redirect:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    from app.models import Settings
    settings = {s.key: s.value for s in db.query(Settings).all()}

    from app.services.three_pl_service import get_3pl_provider
    provider = get_3pl_provider(
        settings.get("3pl_provider", "mock"),
        api_key=settings.get("3pl_api_key", ""),
        sandbox=settings.get("3pl_sandbox", "true") == "true",
    )
    result = await provider.create_shipment(
        origin=body.get("origin", ""),
        destination=body.get("destination", ""),
        weight_kg=float(body.get("weight_kg", 0)),
        recipient_name=body.get("recipient_name", ""),
        recipient_phone=body.get("recipient_phone", ""),
        description=body.get("description", ""),
        cod_amount=float(body.get("cod_amount", 0)),
    )
    return JSONResponse({
        "ok": result.status != "ERROR",
        "tracking_number": result.tracking_number,
        "shipment_id": result.shipment_id,
        "status": result.status,
        "cost": result.cost,
        "estimated_delivery": result.estimated_delivery,
        "provider": result.provider,
        "raw": result.raw,
    })
