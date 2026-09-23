"""Login, logout, session info."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from ..audit import record as audit_record
from ..config import get_config
from ..security.auth import (
    GENERIC_LOGIN_ERROR,
    SESSION_COOKIE,
    clear_failures,
    create_session,
    destroy_session,
    get_user_by_email,
    is_rate_limited,
    record_login_attempt,
    verify_password,
)
from .deps import client_ip, current_session, require_csrf, require_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    config = get_config()
    ip = client_ip(request)
    max_failures = int(config.get("app.login_rate_limit.max_failures", 5))
    window = int(config.get("app.login_rate_limit.window_minutes", 15))

    if is_rate_limited(payload.email, ip, max_failures=max_failures, window_minutes=window):
        audit_record("login.rate_limited", target=payload.email, ip=ip)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed attempts. Try again in {window} minutes.",
        )

    user = get_user_by_email(payload.email)
    # Always the same message, whatever failed.
    if user is None or user["disabled"] or not verify_password(user["password_hash"], payload.password):
        record_login_attempt(payload.email, ip, success=False)
        audit_record("login.failed", target=payload.email, ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    record_login_attempt(payload.email, ip, success=True)
    clear_failures(payload.email, ip)
    absolute = int(config.get("app.session.absolute_timeout_minutes", 480))
    session_id, csrf_token = create_session(
        int(user["id"]),
        absolute_timeout_minutes=absolute,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=absolute * 60,
        path="/",
    )
    audit_record("login.success", actor_email=user["email"], actor_role=user["role"], ip=ip)
    return {
        "email": user["email"],
        "role": user["role"],
        "csrf_token": csrf_token,
        "session": _session_timing(config),
    }


@router.post("/logout")
def logout(request: Request, response: Response, session: dict = Depends(require_csrf)) -> dict[str, str]:
    destroy_session(session["session_id"])
    response.delete_cookie(SESSION_COOKIE, path="/")
    audit_record(
        "logout", actor_email=session.get("email"), actor_role=session.get("role"), ip=client_ip(request)
    )
    return {"status": "logged out"}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    session = current_session(request)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    config = get_config()
    return {
        "email": session["email"],
        "role": session["role"],
        "csrf_token": session["csrf_token"],
        "idle_expires_at": session.get("idle_expires_at"),
        "absolute_expires_at": session.get("expires_at"),
        "session": _session_timing(config),
    }


@router.post("/extend")
def extend(session: dict = Depends(require_csrf)) -> dict[str, Any]:
    """Called by the idle-timeout warning dialog when the user chooses to stay.

    ``require_session`` already refreshed ``last_seen``, so this just reports the
    new deadline.
    """
    config = get_config()
    return {
        "extended_at": datetime.now(timezone.utc).isoformat(),
        "session": _session_timing(config),
    }


def _session_timing(config) -> dict[str, int]:
    return {
        "idle_timeout_minutes": int(config.get("app.session.idle_timeout_minutes", 30)),
        "absolute_timeout_minutes": int(config.get("app.session.absolute_timeout_minutes", 480)),
        "idle_warning_seconds": int(config.get("app.session.idle_warning_seconds", 120)),
    }


__all__ = ["router", "require_session"]
