from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.models import AdminUser, User
from app.schemas import LoginRequest
from app.auth import verify_password, hash_password, create_access_token, get_current_admin

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)
limiter = Limiter(key_func=get_remote_address)


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    # First try admin login
    admin = db.query(AdminUser).filter(AdminUser.email == data.email).first()
    if admin and verify_password(data.password, admin.password):
        token = create_access_token({
            "sub": admin.id,
            "email": admin.email,
            "role": admin.role.value if hasattr(admin.role, 'value') else admin.role,
            "type": "admin",
        })
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=86400,
            secure=False,
            samesite="lax",
        )
        return {
            "access_token": token,
            "user": {
                "id": admin.id,
                "email": admin.email,
                "name": admin.name,
                "role": admin.role.value if hasattr(admin.role, 'value') else admin.role,
            },
            "is_admin": True,
        }

    # Then try customer login
    customer = db.query(User).filter(User.email == data.email).first()
    if customer and customer.password and verify_password(data.password, customer.password):
        token = create_access_token({
            "sub": customer.id,
            "email": customer.email,
            "name": customer.name,
            "type": "customer",
        }, expires_delta=timedelta(days=30))
        response.set_cookie(
            key="customer_token",
            value=token,
            httponly=True,
            max_age=86400 * 30,
            secure=False,
            samesite="lax",
        )
        return {
            "access_token": token,
            "user": {
                "id": customer.id,
                "email": customer.email,
                "name": customer.name,
            },
            "is_admin": False,
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
    )


@router.post("/signup")
@limiter.limit("5/minute")
def signup(request: Request, data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists",
        )

    customer = User(
        email=data.email,
        password=hash_password(data.password),
        name=data.name or data.email.split('@')[0],
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    # Send welcome email
    try:
        from app.services.email_service import send_welcome_email
        send_welcome_email(customer.email, customer.name or "")
    except Exception:
        pass

    # Notify admins of new signup
    try:
        from app.models import AdminNotification
        from app.services.notification_bus import push as bus_push
        notif = AdminNotification(
            type="new_customer",
            title="New Customer Signed Up",
            message=f"{customer.name} ({customer.email}) just created an account.",
            link="/admin/customers",
        )
        db.add(notif)
        db.commit()
        bus_push("new_customer", notif.title, notif.message, notif.link)
    except Exception:
        pass

    token = create_access_token({
        "sub": customer.id,
        "email": customer.email,
        "name": customer.name,
        "type": "customer",
    }, expires_delta=timedelta(days=30))
    response.set_cookie(
        key="customer_token",
        value=token,
        httponly=True,
        max_age=86400 * 30,
        secure=False,
        samesite="lax",
    )

    return {
        "access_token": token,
        "user": {
            "id": customer.id,
            "email": customer.email,
            "name": customer.name,
        },
    }


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("customer_token")
    return {"message": "Logged out"}


@router.get("/me")
def get_me(request: Request, db: Session = Depends(get_db)):
    from app.auth import get_current_user_from_cookie, get_current_customer_from_cookie
    # Try admin first
    admin = get_current_user_from_cookie(request, db)
    if admin:
        return {
            "id": admin.id,
            "email": admin.email,
            "name": admin.name,
            "role": admin.role.value if hasattr(admin.role, 'value') else admin.role,
            "type": "admin",
        }
    # Then try customer
    customer = get_current_customer_from_cookie(request, db)
    if customer:
        return {
            "id": customer.id,
            "email": customer.email,
            "name": customer.name,
            "type": "customer",
        }
    raise HTTPException(status_code=401, detail="Not authenticated")


# ===== Password Reset =====

@router.post("/forgot-password")
def forgot_password(data: dict, db: Session = Depends(get_db)):
    """Send a password reset link to the user's email."""
    from datetime import datetime, timedelta
    from app.models import PasswordResetToken
    from app.services.email_service import send_password_reset_email
    import secrets

    email = data.get("email", "")
    user = db.query(User).filter(User.email == email).first()
    # Always return success to prevent email enumeration
    if not user:
        return {"message": "If that email exists, a reset link has been sent."}

    token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(reset_token)
    db.commit()

    # Send email (falls back to console if SMTP not configured)
    from app.config import get_settings
    base_url = get_settings().site_base_url.rstrip("/")
    reset_link = f"{base_url}/shop/reset-password/{token}"
    send_password_reset_email(user.email, reset_link)

    return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(data: dict, db: Session = Depends(get_db)):
    """Reset password using a valid reset token."""
    from datetime import datetime
    from app.models import PasswordResetToken

    token_str = data.get("token", "")
    new_password = data.get("password", "")

    if not token_str or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Invalid token or password too short")

    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token_str,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > datetime.utcnow(),
    ).first()

    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password = hash_password(new_password)
    reset_token.used = True
    db.commit()

    return {"message": "Password reset successfully. You can now sign in with your new password."}


@router.post("/setup")
def setup_admin(db: Session = Depends(get_db)):
    """Setup default admin if not exists (for first-time setup)."""
    existing = db.query(AdminUser).filter(AdminUser.email == "admin@forgestore.com").first()
    if existing:
        return {"message": "Admin already exists"}

    admin = AdminUser(
        email="admin@forgestore.com",
        password=hash_password("admin123"),
        name="Super Admin",
        role="DIR_ADMIN",
    )
    db.add(admin)
    db.commit()

    return {"message": "Default admin created (admin@forgestore.com / admin123)"}
