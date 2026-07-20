"""
Support ticket system — users create tickets, vendors/admins reply.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, or_, cast, String as SAString
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import SupportTicket, SupportMessage, User, AdminUser, Retailer
from app.auth import get_current_customer_from_cookie, get_current_admin, require_role
from app.utils import utcnow

router = APIRouter(tags=["support"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TicketCreate(BaseModel):
    subject: str
    description: str
    category: str = "OTHER"
    order_id: Optional[str] = None

class MessageCreate(BaseModel):
    message: str

class TicketStatusUpdate(BaseModel):
    status: str

class TicketAssign(BaseModel):
    assigned_to: str

class TicketPriorityUpdate(BaseModel):
    priority: str


# ---------------------------------------------------------------------------
# User / Vendor endpoints
# ---------------------------------------------------------------------------

@router.post("/api/support/tickets")
def create_ticket(
    body: TicketCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_customer_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    ticket = SupportTicket(
        subject=body.subject[:255],
        description=body.description,
        category=body.category.upper(),
        created_by=user.id,
        order_id=body.order_id,
    )
    db.add(ticket)
    db.flush()

    first_msg = SupportMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        sender_role="VENDOR" if user.role == "RETAILER" else "USER",
        message=body.description,
    )
    db.add(first_msg)
    db.commit()
    db.refresh(ticket)

    return {"id": ticket.id, "subject": ticket.subject, "status": ticket.status}


@router.get("/api/support/tickets")
def list_my_tickets(
    request: Request,
    status: Optional[str] = None,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    user = get_current_customer_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    q = db.query(SupportTicket).filter(SupportTicket.created_by == user.id)
    if status:
        q = q.filter(SupportTicket.status == status.upper())

    total = q.count()
    tickets = (
        q.options(joinedload(SupportTicket.messages))
        .order_by(desc(SupportTicket.updated_at))
        .offset(offset).limit(limit).all()
    )

    result = []
    for t in tickets:
        last_msg = t.messages[-1] if t.messages else None
        unread = sum(1 for m in t.messages if not m.is_read and m.sender_role != ("VENDOR" if user.role == "RETAILER" else "USER"))
        result.append({
            "id": t.id,
            "subject": t.subject,
            "category": t.category,
            "status": t.status,
            "priority": t.priority,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "message_count": len(t.messages),
            "unread_count": unread,
            "last_message": {
                "message": last_msg.message[:120] if last_msg else t.description[:120],
                "sender_role": last_msg.sender_role if last_msg else "USER",
                "created_at": last_msg.created_at.isoformat() if last_msg else (t.created_at.isoformat() if t.created_at else None),
            } if last_msg or t.description else None,
        })

    return {"tickets": result, "total": total}


@router.get("/api/support/tickets/{ticket_id}")
def get_ticket(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_customer_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    ticket = (
        db.query(SupportTicket)
        .options(joinedload(SupportTicket.messages).joinedload(SupportMessage.sender))
        .filter(SupportTicket.id == ticket_id, SupportTicket.created_by == user.id)
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    messages = []
    for m in ticket.messages:
        sender_name = ""
        if m.sender:
            sender_name = f"{m.sender.first_name or ''} {m.sender.last_name or ''}".strip()
            if not sender_name:
                sender_name = m.sender.email
        messages.append({
            "id": m.id,
            "sender_role": m.sender_role,
            "sender_name": sender_name or ("Support Team" if m.sender_role == "ADMIN" else "You"),
            "message": m.message,
            "attachment_url": m.attachment_url,
            "is_read": m.is_read,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    # Mark admin messages as read
    for m in ticket.messages:
        if m.sender_role in ("ADMIN", "VENDOR") and not m.is_read:
            m.is_read = True
    db.commit()

    assignee_name = None
    if ticket.assignee:
        assignee_name = f"{ticket.assignee.first_name or ''} {ticket.assignee.last_name or ''}".strip()
        if not assignee_name:
            assignee_name = ticket.assignee.email

    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "description": ticket.description,
        "category": ticket.category,
        "status": ticket.status,
        "priority": ticket.priority,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "assigned_to_name": assignee_name,
        "order_id": ticket.order_id,
        "messages": messages,
    }


@router.post("/api/support/tickets/{ticket_id}/messages")
def reply_to_ticket(
    ticket_id: str,
    body: MessageCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_customer_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    ticket = db.query(SupportTicket).filter(
        SupportTicket.id == ticket_id,
        SupportTicket.created_by == user.id,
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status in ("RESOLVED", "CLOSED"):
        raise HTTPException(status_code=400, detail="Ticket is closed")

    msg = SupportMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        sender_role="VENDOR" if user.role == "RETAILER" else "USER",
        message=body.message,
    )
    db.add(msg)
    ticket.status = "WAITING_CUSTOMER" if ticket.status == "IN_PROGRESS" else ticket.status
    ticket.updated_at = utcnow()
    db.commit()

    return {"id": msg.id, "created_at": msg.created_at.isoformat() if msg.created_at else None}


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.get("/api/admin/support/tickets")
def admin_list_tickets(
    request: Request,
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    q = db.query(SupportTicket)

    if status:
        q = q.filter(SupportTicket.status == status.upper())
    if category:
        q = q.filter(SupportTicket.category == category.upper())
    if priority:
        q = q.filter(SupportTicket.priority == priority.upper())
    if search:
        q = q.join(User, cast(SupportTicket.created_by, SAString) == cast(User.id, SAString), isouter=True).filter(
            or_(
                SupportTicket.subject.ilike(f"%{search}%"),
                User.first_name.ilike(f"%{search}%"),
                User.last_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
            )
        )

    total = q.count()
    tickets = (
        q.options(joinedload(SupportTicket.creator), joinedload(SupportTicket.messages))
        .order_by(desc(SupportTicket.updated_at))
        .offset(offset).limit(limit).all()
    )

    result = []
    for t in tickets:
        creator_name = ""
        if t.creator:
            creator_name = f"{t.creator.first_name or ''} {t.creator.last_name or ''}".strip()
            if not creator_name:
                creator_name = t.creator.email
        last_msg = t.messages[-1] if t.messages else None
        unread = sum(1 for m in t.messages if not m.is_read and m.sender_role == "ADMIN")
        result.append({
            "id": t.id,
            "subject": t.subject,
            "category": t.category,
            "status": t.status,
            "priority": t.priority,
            "created_by_name": creator_name,
            "created_by_email": t.creator.email if t.creator else None,
            "assigned_to": t.assigned_to,
            "retailer_id": t.retailer_id,
            "order_id": t.order_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "message_count": len(t.messages),
            "unread_count": unread,
            "last_message": {
                "message": last_msg.message[:120] if last_msg else "",
                "sender_role": last_msg.sender_role if last_msg else "",
                "created_at": last_msg.created_at.isoformat() if last_msg else None,
            } if last_msg else None,
        })

    return {"tickets": result, "total": total}


@router.get("/api/admin/support/tickets/{ticket_id}")
def admin_get_ticket(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    ticket = (
        db.query(SupportTicket)
        .options(
            joinedload(SupportTicket.messages).joinedload(SupportMessage.sender),
            joinedload(SupportTicket.creator),
        )
        .filter(SupportTicket.id == ticket_id)
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    messages = []
    for m in ticket.messages:
        sender_name = ""
        if m.sender:
            sender_name = f"{m.sender.first_name or ''} {m.sender.last_name or ''}".strip()
            if not sender_name:
                sender_name = m.sender.email
        messages.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_role": m.sender_role,
            "sender_name": sender_name or ("Support Team" if m.sender_role == "ADMIN" else "Customer"),
            "message": m.message,
            "attachment_url": m.attachment_url,
            "is_read": m.is_read,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    creator_name = ""
    if ticket.creator:
        creator_name = f"{ticket.creator.first_name or ''} {ticket.creator.last_name or ''}".strip()
        if not creator_name:
            creator_name = ticket.creator.email

    assignee_name = None
    if ticket.assignee:
        assignee_name = f"{ticket.assignee.first_name or ''} {ticket.assignee.last_name or ''}".strip()
        if not assignee_name:
            assignee_name = ticket.assignee.email

    # Mark all non-admin messages as read
    for m in ticket.messages:
        if m.sender_role != "ADMIN" and not m.is_read:
            m.is_read = True
    db.commit()

    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "description": ticket.description,
        "category": ticket.category,
        "status": ticket.status,
        "priority": ticket.priority,
        "created_by_name": creator_name,
        "created_by_email": ticket.creator.email if ticket.creator else None,
        "assigned_to": ticket.assigned_to,
        "assigned_to_name": assignee_name,
        "retailer_id": ticket.retailer_id,
        "order_id": ticket.order_id,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "messages": messages,
    }


@router.post("/api/admin/support/tickets/{ticket_id}/messages")
def admin_reply_to_ticket(
    ticket_id: str,
    body: MessageCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    msg = SupportMessage(
        ticket_id=ticket.id,
        sender_id=admin.id,
        sender_role="ADMIN",
        message=body.message,
    )
    db.add(msg)
    if ticket.status in ("OPEN", "WAITING_CUSTOMER"):
        ticket.status = "IN_PROGRESS"
    ticket.updated_at = utcnow()
    db.commit()

    return {"id": msg.id, "created_at": msg.created_at.isoformat() if msg.created_at else None}


@router.post("/api/admin/support/tickets/{ticket_id}/status")
def admin_update_status(
    ticket_id: str,
    body: TicketStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    valid = ["OPEN", "IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED", "CLOSED"]
    new_status = body.status.upper()
    if new_status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(valid)}")

    ticket.status = new_status
    ticket.updated_at = utcnow()
    if new_status in ("RESOLVED", "CLOSED"):
        ticket.resolved_at = utcnow()
    db.commit()

    return {"status": ticket.status}


@router.post("/api/admin/support/tickets/{ticket_id}/assign")
def admin_assign_ticket(
    ticket_id: str,
    body: TicketAssign,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.assigned_to = body.assigned_to
    if ticket.status == "OPEN":
        ticket.status = "IN_PROGRESS"
    ticket.updated_at = utcnow()
    db.commit()

    return {"assigned_to": ticket.assigned_to}


@router.get("/api/admin/support/stats")
def admin_support_stats(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    total = db.query(func.count(SupportTicket.id)).scalar() or 0
    open_count = db.query(func.count(SupportTicket.id)).filter(SupportTicket.status == "OPEN").scalar() or 0
    in_progress = db.query(func.count(SupportTicket.id)).filter(SupportTicket.status == "IN_PROGRESS").scalar() or 0
    resolved = db.query(func.count(SupportTicket.id)).filter(SupportTicket.status.in_(["RESOLVED", "CLOSED"])).scalar() or 0
    urgent = db.query(func.count(SupportTicket.id)).filter(SupportTicket.priority == "URGENT", SupportTicket.status.in_(["OPEN", "IN_PROGRESS"])).scalar() or 0

    return {
        "total": total,
        "open": open_count,
        "in_progress": in_progress,
        "resolved": resolved,
        "urgent": urgent,
    }


@router.get("/api/admin/support/admins")
def list_admin_users(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_role("orders")),
):
    admins = db.query(AdminUser).filter(AdminUser.is_active == True).all()
    result = []
    for a in admins:
        name = f"{a.first_name or ''} {a.last_name or ''}".strip()
        if not name:
            name = a.email
        result.append({"id": a.id, "name": name, "email": a.email, "role": a.role})
    return {"admins": result}
