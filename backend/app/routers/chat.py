"""
WebSocket Chat Router — authenticated customer <-> vendor messaging.

Endpoints:
  - WS /ws/chat/{token} — Real-time bidirectional chat
  - GET /api/chat/messages — Historical message feed
  - POST /api/chat/send — REST fallback for message sending
"""
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_

from app.database import get_db
from app.models import ChatMessage, User, Order, Retailer
from app.core.chat_manager import chat_manager
from app.auth import decode_token
from app.utils import utcnow

logger = logging.getLogger("forgestore.chat")

router = APIRouter(tags=["chat"])


def _get_user_from_token(token: str, db: Session):
    """Validate JWT token and return User."""
    payload = decode_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


@router.websocket("/ws/chat/{token}")
async def websocket_chat(websocket: WebSocket, token: str):
    """
    Authenticated WebSocket chat endpoint.
    Token is a JWT passed in the URL path for WS handshake auth.
    """
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        user = _get_user_from_token(token, db)
        if not user:
            await websocket.close(code=4001, reason="Invalid authentication token")
            return

        await chat_manager.connect(websocket, user.id)

        # Send online status
        await websocket.send_text(json.dumps({
            "type": "connected",
            "user_id": user.id,
            "online_users": chat_manager.get_online_users(),
        }))

        # Deliver any pending offline messages
        pending = db.query(ChatMessage).filter(
            ChatMessage.recipient_id == user.id,
            ChatMessage.is_read == False,
        ).order_by(ChatMessage.created_at.asc()).limit(50).all()

        for msg in pending:
            msg.is_read = True
            await websocket.send_text(json.dumps({
                "type": "message",
                "id": msg.id,
                "sender_id": msg.sender_id,
                "recipient_id": msg.recipient_id,
                "order_id": msg.order_id,
                "message_text": msg.message_text,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }))
        db.commit()

        # Main receive loop
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            msg_type = payload.get("type", "")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if msg_type == "message":
                recipient_id = payload.get("recipient_id", "")
                message_text = payload.get("message_text", "").strip()
                order_id = payload.get("order_id")

                if not recipient_id or not message_text:
                    await websocket.send_text(json.dumps({"type": "error", "message": "recipient_id and message_text required"}))
                    continue

                # Persist message
                chat_msg = ChatMessage(
                    sender_id=user.id,
                    recipient_id=recipient_id,
                    order_id=order_id,
                    message_text=message_text,
                )
                db.add(chat_msg)
                db.commit()
                db.refresh(chat_msg)

                msg_payload = {
                    "type": "message",
                    "id": chat_msg.id,
                    "sender_id": user.id,
                    "recipient_id": recipient_id,
                    "order_id": order_id,
                    "message_text": message_text,
                    "created_at": chat_msg.created_at.isoformat() if chat_msg.created_at else None,
                }

                # Send to recipient if online
                await chat_manager.send_to_user(recipient_id, msg_payload)
                # Echo to sender
                await websocket.send_text(json.dumps(msg_payload))

            elif msg_type == "typing":
                recipient_id = payload.get("recipient_id", "")
                await chat_manager.send_to_user(recipient_id, {
                    "type": "typing",
                    "user_id": user.id,
                })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("Chat WebSocket error: %s", exc)
    finally:
        await chat_manager.disconnect(websocket)
        db.close()


@router.get("/api/chat/messages")
def get_chat_messages(
    request: Request,
    other_user_id: str = "",
    order_id: str = "",
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get chat message history between two users or for an order."""
    from app.auth import get_current_customer_from_cookie
    from app.core.security import decode_token as dt

    # Auth check
    token = request.cookies.get("customer_token")
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = dt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub", "")

    query = db.query(ChatMessage).filter(
        or_(
            ChatMessage.sender_id == user_id,
            ChatMessage.recipient_id == user_id,
        )
    )

    if other_user_id:
        query = query.filter(
            or_(
                (ChatMessage.sender_id == user_id) & (ChatMessage.recipient_id == other_user_id),
                (ChatMessage.sender_id == other_user_id) & (ChatMessage.recipient_id == user_id),
            )
        )

    if order_id:
        query = query.filter(ChatMessage.order_id == order_id)

    messages = query.order_by(ChatMessage.created_at.desc()).limit(limit).all()

    return {
        "messages": [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "recipient_id": m.recipient_id,
                "order_id": m.order_id,
                "message_text": m.message_text,
                "is_read": m.is_read,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in reversed(messages)
        ],
    }


@router.post("/api/chat/send")
def send_chat_message(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """REST fallback for sending chat messages."""
    from app.core.security import decode_token as dt

    token = request.cookies.get("customer_token") or request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = dt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub", "")

    recipient_id = data.get("recipient_id", "")
    message_text = data.get("message_text", "").strip()
    order_id = data.get("order_id")

    if not recipient_id or not message_text:
        raise HTTPException(status_code=400, detail="recipient_id and message_text required")

    chat_msg = ChatMessage(
        sender_id=user_id,
        recipient_id=recipient_id,
        order_id=order_id,
        message_text=message_text,
    )
    db.add(chat_msg)
    db.commit()
    db.refresh(chat_msg)

    # Deliver via WebSocket if recipient online
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(chat_manager.send_to_user(recipient_id, {
            "type": "message",
            "id": chat_msg.id,
            "sender_id": user_id,
            "recipient_id": recipient_id,
            "order_id": order_id,
            "message_text": message_text,
            "created_at": chat_msg.created_at.isoformat() if chat_msg.created_at else None,
        }))
    except RuntimeError:
        pass

    return {"success": True, "message_id": chat_msg.id}
