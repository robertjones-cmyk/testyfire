"""Admin-only endpoints: audit log, users, demo controls, feed validation."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field

from .. import audit, db
from ..config import get_config
from ..security.auth import MIN_PASSWORD_LENGTH, create_user, get_user_by_email, set_password
from .deps import client_ip, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/audit")
def get_audit(session: dict = Depends(require_admin), limit: int = Query(200, le=1000)) -> dict[str, Any]:
    return {"entries": audit.recent(limit)}


@router.get("/users")
def list_users(session: dict = Depends(require_admin)) -> dict[str, Any]:
    rows = db.query("SELECT id, email, role, created_at, disabled FROM users ORDER BY email")
    return {"users": db.rows_to_dicts(rows)}


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    role: Literal["viewer", "operator", "admin"] = "viewer"


@router.post("/users")
def add_user(payload: CreateUserRequest, request: Request, session: dict = Depends(require_admin)) -> dict[str, Any]:
    if get_user_by_email(payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with that email already exists")
    user_id = create_user(payload.email, payload.password, payload.role)
    audit.record(
        "user.created", actor_email=session["email"], actor_role=session["role"],
        target=payload.email, detail={"role": payload.role}, ip=client_ip(request),
    )
    return {"id": user_id, "email": payload.email, "role": payload.role}


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


@router.post("/users/reset-password")
def reset_password(
    payload: ResetPasswordRequest, request: Request, session: dict = Depends(require_admin)
) -> dict[str, Any]:
    if not set_password(payload.email, payload.password):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    audit.record(
        "user.password_reset", actor_email=session["email"], actor_role=session["role"],
        target=payload.email, ip=client_ip(request),
    )
    return {"status": "password updated", "email": payload.email}


class FireScenarioRequest(BaseModel):
    sensor_id: str | None = None


@router.post("/demo/fire-scenario")
def fire_scenario(payload: FireScenarioRequest, request: Request, session: dict = Depends(require_admin)) -> dict[str, Any]:
    """Trigger the mock fire. Every resulting record is tagged ``demo``."""
    worker = getattr(request.app.state, "worker", None)
    if worker is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Ingest worker is not running")
    try:
        sensor_id = worker.start_fire_scenario(payload.sensor_id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    audit.record(
        "demo.fire_scenario_started", actor_email=session["email"], actor_role=session["role"],
        target=f"sensor:{sensor_id}", ip=client_ip(request),
    )
    return {
        "status": "running",
        "sensor_id": sensor_id,
        "nearest_camera": worker.nearest_camera_to_sensor(sensor_id),
        "note": (
            "Readings are ramping. Events created from this scenario are tagged demo=true, "
            "show a DEMO badge, and are dispatched only to the local test receiver."
        ),
    }


@router.post("/demo/fire-scenario/stop")
def stop_fire_scenario(request: Request, session: dict = Depends(require_admin)) -> dict[str, str]:
    worker = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.stop_fire_scenario()
    audit.record(
        "demo.fire_scenario_stopped", actor_email=session["email"], actor_role=session["role"],
        ip=client_ip(request),
    )
    return {"status": "stopped"}


@router.post("/ingest/poll-now")
def poll_now(request: Request, session: dict = Depends(require_admin)) -> dict[str, Any]:
    """Force an immediate ingest cycle (used by the demo script)."""
    worker = getattr(request.app.state, "worker", None)
    if worker is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Ingest worker is not running")
    worker._next_due.clear()
    stored = worker.poll_once()
    audit.record(
        "ingest.manual_poll", actor_email=session["email"], actor_role=session["role"],
        detail={"frames_stored": stored}, ip=client_ip(request),
    )
    return {"frames_stored": stored}


@router.get("/feed-health")
def feed_health(session: dict = Depends(require_admin)) -> dict[str, Any]:
    return {"feeds": db.rows_to_dicts(db.query("SELECT * FROM feed_health ORDER BY feed_id"))}
