"""Request dependencies: session loading, CSRF and role guards.

Every route that needs a user takes one of these. Roles are checked **here, on
the server**, for every endpoint — the UI hiding a button is not access control.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status

from ..audit import record as audit_record
from ..config import get_config
from ..security.auth import CSRF_HEADER, SESSION_COOKIE, check_csrf, load_session, role_allows

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def client_ip(request: Request) -> str:
    """Direct peer address. We do not trust X-Forwarded-For by default: behind a
    reverse proxy, configure the proxy to set it and enable it deliberately."""
    return request.client.host if request.client else "unknown"


def current_session(request: Request) -> dict[str, Any] | None:
    config = get_config()
    idle = int(config.get("app.session.idle_timeout_minutes", 30))
    session = load_session(request.cookies.get(SESSION_COOKIE), idle_timeout_minutes=idle)
    request.state.session = session
    return session


def require_session(request: Request) -> dict[str, Any]:
    session = current_session(request)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return session


def require_csrf(request: Request, session: dict[str, Any] = Depends(require_session)) -> dict[str, Any]:
    """State-changing requests must echo the session's CSRF token."""
    if request.method in SAFE_METHODS:
        return session
    token = request.headers.get(CSRF_HEADER)
    if not check_csrf(session, token):
        audit_record(
            "csrf.rejected",
            actor_email=session.get("email"),
            actor_role=session.get("role"),
            target=str(request.url.path),
            ip=client_ip(request),
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
    return session


def require_role(required: str) -> Callable[..., dict[str, Any]]:
    """Dependency factory: viewer < operator < admin."""

    def dependency(request: Request, session: dict[str, Any] = Depends(require_csrf)) -> dict[str, Any]:
        if not role_allows(session.get("role"), required):
            audit_record(
                "authz.denied",
                actor_email=session.get("email"),
                actor_role=session.get("role"),
                target=str(request.url.path),
                detail={"required_role": required},
                ip=client_ip(request),
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action requires the {required} role",
            )
        return session

    return dependency


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role("admin")
