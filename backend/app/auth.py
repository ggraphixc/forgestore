"""
Re‑export shim for backward compatibility.

All authentication logic has moved to ``app.core.security``.
This module re‑exports every public name so that existing import paths
(e.g. ``from app.auth import get_current_admin``) continue to work
without modification.
"""

from app.core.security import (
    # ── RBAC ──
    ROLE_PERMISSIONS,
    has_permission,
    require_role,

    # ── Password helpers ──
    verify_password,
    hash_password,

    # ── JWT helpers ──
    create_access_token,
    decode_token,

    # ── Cookie helpers ──
    set_auth_cookie,
    delete_auth_cookie,
    COOKIE_MAX_AGE_DAYS,

    # ── Dependencies ──
    get_current_admin,
    get_current_user,
    get_current_user_optional,
    get_current_user_from_cookie,
    get_current_customer_from_cookie,

    # ── Audit ──
    log_admin_action,

    # ── Re-exported model type used by callers ──
    AdminRole,
)

# Module-level convenience references kept for anyone who imported
# `settings` or `security` directly from `app.auth`
from app.core.security import settings, security  # noqa: F811
