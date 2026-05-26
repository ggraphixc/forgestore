"""
Authentication & Authorisation — JWT tokens, password hashing, RBAC.

Every function that was in ``app.auth`` lives here now.  ``app.auth`` is a
thin re‑export shim so that existing import paths keep working.
"""

from datetime import datetime, timedelta
from typing import Optional, List

from jose import JWTError, jwt
import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AdminUser, User, AdminRole

settings = get_settings()
security = HTTPBearer(auto_error=False)

# ==============================================================================
# RBAC SYSTEM
# ==============================================================================

ROLE_PERMISSIONS = {
    AdminRole.DIR_ADMIN: [
        "dashboard", "catalog", "categories", "retailers",
        "orders", "customers", "settings", "admin_users",
    ],
    AdminRole.MANAGEMENT: [
        "dashboard", "catalog", "categories", "retailers",
        "orders", "customers",
    ],
    AdminRole.TECH_ADMIN: [
        "dashboard", "settings", "admin_users",
        "settings_technical", "settings_developer",
    ],
    AdminRole.RETAILER: [
        "dashboard", "catalog",
    ],
    AdminRole.LOGISTICS: [
        "dashboard", "orders", "customers",
    ],
}


def has_permission(admin: AdminUser, permission: str) -> bool:
    """Check whether *admin* holds *permission* under the current RBAC map."""
    role = admin.role
    if isinstance(role, str):
        try:
            role = AdminRole(role)
        except ValueError:
            return False
    return permission in ROLE_PERMISSIONS.get(role, [])


def require_role(*permissions: str):
    """FastAPI dependency guard — raises **403** if the admin lacks *any* of the
    given permissions.

    Usage::

        @router.get("/secret-stuff")
        def secret(admin: AdminUser = Depends(require_role("admin_users"))):
            ...
    """
    def role_checker(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
        if not permissions:
            return admin
        for perm in permissions:
            if has_permission(admin, perm):
                return admin
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )
    return role_checker


# ==============================================================================
# PASSWORD HELPERS
# ==============================================================================


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Compare a plain‑text password against a bcrypt hash."""
    return _bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def hash_password(password: str) -> str:
    """Return the bcrypt hash of *password*."""
    return _bcrypt.hashpw(
        password.encode("utf-8"),
        _bcrypt.gensalt(),
    ).decode("utf-8")


# ==============================================================================
# JWT HELPERS
# ==============================================================================


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT containing *data*.

    If *expires_delta* is ``None`` the token lifetime falls back to
    ``settings.access_token_expire_minutes``.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> Optional[dict]:
    """Decode (and verify) a JWT.  Returns ``None`` on any error."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


# ==============================================================================
# FASTAPI DEPENDENCIES
# ==============================================================================


def get_current_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> AdminUser:
    """FastAPI dependency — extract & validate the admin JWT.

    Tries the ``Authorization: Bearer <token>`` header first and falls back to
    the ``access_token`` cookie (so the same function works for both API
    clients and browser‑rendered pages).
    """
    token: Optional[str] = None

    # 1) Bearer header
    if credentials is not None:
        token = credentials.credentials

    # 2) Cookie fallback
    if token is None:
        token = request.cookies.get("access_token")

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    admin_id = payload.get("sub")
    if admin_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin not found",
        )
    return admin


def get_current_user_from_cookie(
    request: Request,
    db: Session,
) -> Optional[AdminUser]:
    """Try to authenticate **only** via the ``access_token`` cookie
    (no Bearer header).  Returns ``None`` instead of raising.

    This is the dependency used by server‑rendered page routes (Jinja2
    templates) so that public pages remain accessible without forcing a
    redirect.
    """
    token = request.cookies.get("access_token")
    if not token:
        return None

    payload = decode_token(token)
    if payload is None:
        return None

    user_id = payload.get("sub")
    user_type = payload.get("type", "admin")
    if user_id is None:
        return None

    if user_type == "admin":
        return db.query(AdminUser).filter(AdminUser.id == user_id).first()
    return None  # Customer tokens are handled by get_current_customer_from_cookie


def get_current_customer_from_cookie(
    request: Request,
    db: Session,
) -> Optional[User]:
    """Extract the authenticated **customer** from the ``customer_token`` cookie.

    Returns ``None`` silently when there is no cookie or the token is invalid.
    """
    token = request.cookies.get("customer_token")
    if not token:
        return None

    payload = decode_token(token)
    if payload is None:
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    return db.query(User).filter(User.id == user_id).first()


# ==============================================================================
# AUDIT LOGGING
# ==============================================================================


def log_admin_action(
    db: Session,
    admin: AdminUser,
    action: str,
    resource_type: str = None,
    resource_id: str = None,
    details: str = None,
    ip_address: str = None,
):
    """Persist an admin action to the audit log."""
    from app.models import AdminAuditLog

    log = AdminAuditLog(
        admin_id=admin.id if admin else None,
        admin_email=admin.email if admin else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
    )
    db.add(log)
    db.commit()
