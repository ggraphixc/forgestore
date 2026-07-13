"""Real-time Order Tracking System — System 1"""
import logging
import uuid
from datetime import timedelta
from typing import Optional
from sqlalchemy.orm import Session

from app.models import Shipment, ShipmentEvent, DeliveryAgent, DeliveryLocationLog, Order
from app.utils import utcnow
from app.core.websocket_manager import ws_manager

logger = logging.getLogger("forgestore.shipment")


class ShipmentService:
    """Manages shipment creation, tracking, and status updates."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _generate_tracking_number() -> str:
        """Generate a unique tracking number."""
        import uuid
        return f"FS-{uuid.uuid4().hex[:10].upper()}"

    def create_shipment(
        self,
        order_id: str,
        carrier: Optional[str] = None,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        weight_kg: Optional[float] = None,
        notes: Optional[str] = None,
        estimated_delivery_days: int = 5,
        delivery_agent_id: Optional[str] = None,
    ) -> Shipment:
        """Create a new shipment for an order."""
        tracking_number = self._generate_tracking_number()
        estimated_delivery = utcnow() + timedelta(days=estimated_delivery_days)

        shipment = Shipment(
            order_id=order_id,
            tracking_number=tracking_number,
            carrier=carrier,
            status="PENDING",
            estimated_delivery=estimated_delivery,
            origin=origin,
            destination=destination,
            weight_kg=weight_kg,
            notes=notes,
            delivery_agent_id=delivery_agent_id,
        )
        self.db.add(shipment)
        self.db.commit()
        self.db.refresh(shipment)

        # Create initial event
        self.add_event(shipment.id, "PENDING", description="Shipment created and pending pickup")

        # Broadcast via WebSocket
        try:
            order = self.db.query(Order).filter(Order.id == order_id).first()
            if order:
                import asyncio
                asyncio.ensure_future(ws_manager.broadcast_order_update(order_id, {
                    "type": "shipment.created",
                    "shipment_id": shipment.id,
                    "tracking_number": tracking_number,
                    "status": "PENDING",
                }))
        except Exception:
            logger.warning("Failed to broadcast shipment creation", exc_info=True)

        return shipment

    def add_event(
        self,
        shipment_id: str,
        status: str,
        location: Optional[str] = None,
        description: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> ShipmentEvent:
        """Add a tracking event to a shipment."""
        event = ShipmentEvent(
            shipment_id=shipment_id,
            status=status,
            location=location,
            description=description,
            latitude=latitude,
            longitude=longitude,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)

        # Update shipment status
        self.db.query(Shipment).filter(Shipment.id == shipment_id).update({"status": status})
        self.db.commit()

        return event

    def update_status(self, shipment_id: str, status: str, description: Optional[str] = None) -> Shipment:
        """Update shipment status with automatic event logging + customer notifications."""
        shipment = self.db.query(Shipment).filter(Shipment.id == shipment_id).first()
        if not shipment:
            raise ValueError(f"Shipment {shipment_id} not found")

        old_status = shipment.status
        shipment.status = status

        if status == "DELIVERED":
            shipment.actual_delivery = utcnow()

        self.db.commit()

        self.add_event(shipment_id, status, description=description or f"Status changed from {old_status} to {status}")

        # Broadcast via WebSocket
        try:
            import asyncio
            asyncio.ensure_future(ws_manager.broadcast_order_update(shipment.order_id, {
                "type": "shipment.status_update",
                "shipment_id": shipment.id,
                "tracking_number": shipment.tracking_number,
                "status": status,
                "old_status": old_status,
            }))
            asyncio.ensure_future(ws_manager.broadcast(
                f"shipment:{shipment.id}",
                {"type": "status_update", "status": status, "old_status": old_status, "description": description or ""}
            ))
        except Exception:
            logger.warning("Failed to broadcast shipment status update", exc_info=True)

        # Automated customer/vendor notifications on status change
        try:
            asyncio.ensure_future(self._send_status_notifications(shipment, old_status, status))
        except Exception:
            logger.warning("Failed to send status notifications", exc_info=True)

        # Dispatch outbound webhook for status change
        try:
            from app.core.webhooks import notify_order_status_changed
            order = self.db.query(Order).filter(Order.id == shipment.order_id).first()
            if order:
                notify_order_status_changed(order, old_status, status)
        except Exception:
            pass

        return shipment

    async def _send_status_notifications(self, shipment, old_status: str, new_status: str):
        """Send WhatsApp + email notifications to customer + vendor on shipment status changes."""
        from app.core.notifications import send_whatsapp_message
        from app.services.email_service import send_order_status_email
        from app.models import User, OrderItem, Retailer
        from app.services.delivery_pricing import calculate_delivery_fee

        order = self.db.query(Order).filter(Order.id == shipment.order_id).first()
        if not order:
            return

        # Customer info
        customer = self.db.query(User).filter(User.id == order.customer_id).first()
        customer_phone = getattr(customer, "phone", None)
        customer_email = getattr(customer, "email", None)

        # Status message mapping
        status_messages = {
            "PICKED_UP": f"Hi! Your order #{order.order_number} has been picked up for delivery. Tracking: {shipment.tracking_number}",
            "IN_TRANSIT": f"Your order #{order.order_number} is on its way! Tracking: {shipment.tracking_number}. Estimated delivery: {shipment.estimated_delivery or 'within 2-3 days'}.",
            "OUT_FOR_DELIVERY": f"Great news! Your order #{order.order_number} is out for delivery today. Please keep your phone handy.",
            "DELIVERED": f"Your order #{order.order_number} has been delivered successfully! Thank you for shopping with us.",
            "RETURNED": f"Your order #{order.order_number} return has been initiated. Our logistics team will contact you shortly.",
            "CANCELLED": f"Your order #{order.order_number} has been cancelled. If you have questions, please contact support.",
        }

        msg = status_messages.get(new_status)

        # WhatsApp to customer
        if msg and customer_phone:
            try:
                await send_whatsapp_message(customer_phone, msg)
            except Exception:
                logger.warning("Failed to send WhatsApp to customer %s", customer_phone)

        # Email to customer
        if customer_email:
            try:
                send_order_status_email(
                    to_email=customer_email,
                    order_number=order.order_number,
                    status=new_status,
                    tracking_number=shipment.tracking_number,
                    estimated_delivery=shipment.estimated_delivery,
                )
            except Exception:
                logger.warning("Failed to send email to customer %s", customer_email)

        # SMS to customer
        if msg and customer_phone:
            try:
                from app.core.sms import send_sms
                send_sms(customer_phone, msg)
            except Exception:
                pass

        # Notify vendor (WhatsApp + email)
        items = self.db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        for item in items:
            product = item.product
            if product and product.retailer_id:
                retailer = self.db.query(Retailer).filter(Retailer.id == product.retailer_id).first()
                if retailer:
                    if retailer.phone:
                        vendor_msg = f"Order #{order.order_number} status updated: {new_status}. Tracking: {shipment.tracking_number}"
                        try:
                            await send_whatsapp_message(retailer.phone, vendor_msg)
                        except Exception:
                            logger.warning("Failed to send WhatsApp to vendor %s", retailer.phone)
                    if retailer.email:
                        try:
                            from app.services.email_service import send_vendor_new_order_email
                            send_vendor_new_order_email(
                                to_email=retailer.email,
                                order_number=order.order_number,
                                customer_name=customer.name if customer else "Customer",
                                total_amount=order.total_amount,
                            )
                        except Exception:
                            logger.warning("Failed to send email to vendor %s", retailer.email)

    def assign_delivery_agent(self, shipment_id: str, agent_id: str) -> Shipment:
        """Assign a delivery agent to a shipment."""
        shipment = self.db.query(Shipment).filter(Shipment.id == shipment_id).first()
        if not shipment:
            raise ValueError(f"Shipment {shipment_id} not found")

        shipment.delivery_agent_id = agent_id
        self.db.commit()
        self.db.refresh(shipment)

        self.add_event(shipment_id, shipment.status, description=f"Delivery agent assigned")
        return shipment

    def get_shipment(self, tracking_number: str = None, shipment_id: str = None) -> Optional[Shipment]:
        """Get shipment by tracking number or ID."""
        if tracking_number:
            return self.db.query(Shipment).filter(Shipment.tracking_number == tracking_number).first()
        if shipment_id:
            return self.db.query(Shipment).filter(Shipment.id == shipment_id).first()
        return None

    def get_order_shipments(self, order_id: str) -> list[Shipment]:
        """Get all shipments for an order."""
        return self.db.query(Shipment).filter(Shipment.order_id == order_id).all()

    def get_tracking_timeline(self, shipment_id: str) -> list[ShipmentEvent]:
        """Get the full tracking timeline for a shipment."""
        return self.db.query(ShipmentEvent).filter(
            ShipmentEvent.shipment_id == shipment_id
        ).order_by(ShipmentEvent.timestamp.asc()).all()


class TrackingService:
    """Provides customer-facing tracking information."""

    def __init__(self, db: Session):
        self.db = db

    def get_tracking_info(self, tracking_number: str) -> Optional[dict]:
        """Get comprehensive tracking information for a shipment."""
        shipment = self.db.query(Shipment).filter(
            Shipment.tracking_number == tracking_number
        ).first()
        if not shipment:
            return None

        events = self.db.query(ShipmentEvent).filter(
            ShipmentEvent.shipment_id == shipment.id
        ).order_by(ShipmentEvent.timestamp.asc()).all()

        agent = None
        if shipment.delivery_agent_id:
            agent = self.db.query(DeliveryAgent).filter(
                DeliveryAgent.id == shipment.delivery_agent_id
            ).first()

        return {
            "tracking_number": shipment.tracking_number,
            "carrier": shipment.carrier,
            "status": shipment.status,
            "estimated_delivery": shipment.estimated_delivery.isoformat() if shipment.estimated_delivery else None,
            "actual_delivery": shipment.actual_delivery.isoformat() if shipment.actual_delivery else None,
            "origin": shipment.origin,
            "destination": shipment.destination,
            "weight_kg": shipment.weight_kg,
            "timeline": [
                {
                    "status": e.status,
                    "location": e.location,
                    "description": e.description,
                    "latitude": e.latitude,
                    "longitude": e.longitude,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in events
            ],
            "delivery_agent": {
                "name": agent.name if agent else None,
                "phone": agent.phone if agent else None,
                "photo": None,  # Could add agent photo later
            } if agent else None,
        }


class DeliveryService:
    """Manages delivery agents and real-time location tracking."""

    def __init__(self, db: Session):
        self.db = db

    def create_agent(self, name: str, phone: Optional[str] = None, email: Optional[str] = None,
                     vehicle_type: Optional[str] = None, vehicle_number: Optional[str] = None) -> DeliveryAgent:
        """Register a new delivery agent."""
        agent = DeliveryAgent(
            name=name,
            phone=phone,
            email=email,
            vehicle_type=vehicle_type,
            vehicle_number=vehicle_number,
            status="AVAILABLE",
        )
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def update_location(self, agent_id: str, latitude: float, longitude: float,
                        accuracy: Optional[float] = None, shipment_id: Optional[str] = None):
        """Update delivery agent's current location."""
        agent = self.db.query(DeliveryAgent).filter(DeliveryAgent.id == agent_id).first()
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        agent.current_latitude = latitude
        agent.current_longitude = longitude
        agent.last_location_update = utcnow()
        self.db.commit()

        # Log the location
        log = DeliveryLocationLog(
            agent_id=agent_id,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
            shipment_id=shipment_id,
        )
        self.db.add(log)
        self.db.commit()

    def set_agent_status(self, agent_id: str, status: str):
        """Set delivery agent status (AVAILABLE, BUSY, OFFLINE)."""
        agent = self.db.query(DeliveryAgent).filter(DeliveryAgent.id == agent_id).first()
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")
        agent.status = status
        self.db.commit()

    def get_available_agents(self) -> list[DeliveryAgent]:
        """Get all available delivery agents."""
        return self.db.query(DeliveryAgent).filter(
            DeliveryAgent.status == "AVAILABLE"
        ).order_by(DeliveryAgent.rating.desc()).all()

    def get_agent_location_history(self, agent_id: str, hours: int = 24) -> list[DeliveryLocationLog]:
        """Get location history for an agent."""
        cutoff = utcnow() - timedelta(hours=hours)
        return self.db.query(DeliveryLocationLog).filter(
            DeliveryLocationLog.agent_id == agent_id,
            DeliveryLocationLog.timestamp >= cutoff,
        ).order_by(DeliveryLocationLog.timestamp.asc()).all()
