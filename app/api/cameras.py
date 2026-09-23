"""Cameras, frames and images."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from .. import db
from ..config import get_config
from ..pipeline.fusion import FusionEngine
from ..pipeline.viewchange import view_changes_today
from .deps import require_session

router = APIRouter(prefix="/api", tags=["cameras"])


def _camera_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["view_changes_today"] = view_changes_today(row["key"])
    latest = db.query_one(
        "SELECT id, ts, score, view_changed, bbox FROM frames WHERE camera_key = ?"
        " ORDER BY id DESC LIMIT 1",
        (row["key"],),
    )
    data["latest_frame"] = dict(latest) if latest else None
    data["heading_known"] = row["heading"] is not None
    return data


@router.get("/cameras")
def list_cameras(session: dict = Depends(require_session)) -> dict[str, Any]:
    rows = db.query("SELECT * FROM cameras ORDER BY feed_id, name")
    cameras = [_camera_dict(row) for row in rows]
    feeds_health = {row["feed_id"]: dict(row) for row in db.query("SELECT * FROM feed_health")}
    return {"cameras": cameras, "feeds": feeds_health}


@router.get("/cameras/{camera_key}")
def get_camera(camera_key: str, session: dict = Depends(require_session)) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM cameras WHERE key = ?", (camera_key,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    data = _camera_dict(row)
    data["recent_frames"] = db.rows_to_dicts(db.query(
        "SELECT id, ts, score, view_changed, bbox, inference_ms, cost_usd FROM frames"
        " WHERE camera_key = ? ORDER BY id DESC LIMIT 10",
        (camera_key,),
    ))
    return data


@router.get("/cameras/{camera_key}/view")
def camera_view(camera_key: str, session: dict = Depends(require_session)) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM cameras WHERE key = ?", (camera_key,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    view = FusionEngine(get_config()).camera_view(row)
    if view is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Camera has no location")
    return view.as_geojson_feature()


@router.get("/camera-views")
def camera_views(session: dict = Depends(require_session)) -> dict[str, Any]:
    engine = FusionEngine(get_config())
    return {
        "type": "FeatureCollection",
        "features": [view.as_geojson_feature() for view in engine.all_views()],
    }


@router.get("/frames/{frame_id}/image")
def frame_image(frame_id: int, session: dict = Depends(require_session)) -> Response:
    """Images are served **only** through this authenticated endpoint.

    The frames folder is never mounted as static files.
    """
    row = db.query_one("SELECT path FROM frames WHERE id = ?", (frame_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame not found")

    frames_root = Path(get_config().frames_dir).resolve()
    path = Path(row["path"]).resolve()
    # Defence in depth: never serve a file outside the frames directory, even if
    # a bad row somehow got in.
    if frames_root != path and frames_root not in path.parents:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Refusing to serve a file outside the frame store")
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame file has been deleted by retention")

    return Response(
        content=path.read_bytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/frames/{frame_id}")
def frame_detail(frame_id: int, session: dict = Depends(require_session)) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM frames WHERE id = ?", (frame_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame not found")
    data = dict(row)
    data.pop("path", None)   # never expose filesystem paths to the browser
    data["bbox"] = json.loads(row["bbox"]) if row["bbox"] else None
    camera = db.query_one("SELECT name FROM cameras WHERE key = ?", (row["camera_key"],))
    data["camera_name"] = camera["name"] if camera else row["camera_key"]
    return data
