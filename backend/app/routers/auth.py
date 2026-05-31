from datetime import datetime, timedelta
from app.utils import utcnow

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, BackgroundTasks
from fastapi.security import HTTPBearer
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
import httpx

from app.database import get_db
from app.models import AdminUser, User
from app.schemas import LoginRequest
from app.auth import verify_password, hash_password, create_access_token, get_current_admin, get_current_user, set_auth_cookie, delete_auth_cookie
from app.config import get_settings

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
        set_auth_cookie(response, token, "access_token")
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
        set_auth_cookie(response, token, "customer_token")
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
def signup(request: Request, data: LoginRequest, response: Response, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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

    # Send welcome email via BackgroundTasks (non-blocking)
    try:
        from app.services.email_service import send_welcome_email
        background_tasks.add_task(send_welcome_email, customer.email, customer.name or "")
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
    set_auth_cookie(response, token, "customer_token")

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
    delete_auth_cookie(response, "access_token")
    delete_auth_cookie(response, "customer_token")
    return {"message": "Logged out"}


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    if isinstance(user, AdminUser):
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role.value if hasattr(user.role, 'value') else user.role,
            "type": "admin",
        }
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "type": "customer",
    }


# ===== Password Reset =====

@router.post("/forgot-password")
def forgot_password(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Send a password reset link to the user's email (non-blocking via BackgroundTasks)."""
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
        expires_at=utcnow() + timedelta(hours=1),
    )
    db.add(reset_token)
    db.commit()

    # Send email via BackgroundTasks (non-blocking)
    from app.config import get_settings
    base_url = get_settings().site_base_url.rstrip("/")
    reset_link = f"{base_url}/shop/reset-password/{token}"
    background_tasks.add_task(send_password_reset_email, user.email, reset_link)

    return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(data: dict, db: Session = Depends(get_db)):
    """Reset password using a valid reset token."""
    from app.models import PasswordResetToken

    token_str = data.get("token", "")
    new_password = data.get("password", "")

    if not token_str or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Invalid token or password too short")

    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token_str,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > utcnow(),
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


# ===== Google OAuth =====

@router.get("/google/login")
async def google_login(request: Request):
    """Redirects the client browser to Google's OAuth2 consent screen."""
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured on this server.")

    redirect_uri = f"{settings.site_base_url.rstrip('/')}/api/auth/google/callback"
    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?response_type=code&client_id={settings.google_client_id}"
        f"&redirect_uri={redirect_uri}&scope=openid%20email%20profile"
        f"&access_type=offline&prompt=consent"
    )
    return RedirectResponse(url=google_auth_url)


@router.get("/google/callback")
async def google_callback(code: str, db: Session = Depends(get_db)):
    """Exchanges auth code for tokens, verifies profile, and establishes session."""
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured on this server.")

    redirect_uri = f"{settings.site_base_url.rstrip('/')}/api/auth/google/callback"

    # 1. Exchange authorization code for access tokens
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to retrieve token from Google.")
        token_data = token_response.json()
        access_token = token_data.get("access_token")

        # 2. Extract profile identity from Google UserInfo endpoint
        user_info_response = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_info_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to retrieve profile from Google.")
        profile_data = user_info_response.json()

    email = profile_data.get("email")
    name = profile_data.get("name", email.split("@")[0]) if email else None
    if not email:
        raise HTTPException(status_code=400, detail="Google account did not provide a valid email.")

    # 3. Synchronize with local user table
    user = db.query(User).filter(User.email == email).first()
    if not user:
        import secrets as _secrets
        random_pass = _secrets.token_urlsafe(32)
        user = User(
            email=email,
            name=name,
            password=hash_password(random_pass),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # 4. Generate session JWT and set cookies
    token_payload = {"sub": str(user.id), "email": user.email, "name": user.name, "type": "customer"}
    session_jwt = create_access_token(data=token_payload, expires_delta=timedelta(days=30))

    response = RedirectResponse(url="/shop")
    set_auth_cookie(response, session_jwt, cookie_name="customer_token")
    set_auth_cookie(response, session_jwt, cookie_name="access_token")
    return response
