"""Dispatch webhook.

Rules enforced here:

* **disabled until an admin sets a URL** — no accidental deliveries;
* **HTTPS only**, with one exception: the loopback test receiver;
* **only ``verified`` and ``sensor_only`` events** are ever sent (the check is
  in :func:`~app.pipeline.fusion.should_dispatch`, re-asserted here);
* every payload is **signed with HMAC-SHA256** over ``timestamp.body`` using a
  secret from the environment, and carries a timestamp, an event id and a
  delivery id so the receiver can reject replays and duplicates;
* the payload carries **event data and a link that requires login** to see the
  image — never the raw image, never credentials;
* **retries with exponential backoff**, and every attempt is logged to
  ``dispatch_log``;
* **demo events go only to the local test receiver**, never to a real URL.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import db
from ..audit import record as audit_record
from ..config import env_secret
from ..security.redact import redact

SIGNATURE_HEADER = "X-Torch-Signature"
TIMESTAMP_HEADER = "X-Torch-Timestamp"
EVENT_ID_HEADER = "X-Torch-Event-Id"
DELIVERY_ID_HEADER = "X-Torch-Delivery-Id"


class DispatchRefused(Exception):
    """Raised when a dispatch target or event fails policy."""


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """``sha256=<hex>`` over ``timestamp.body`` — replay-resistant."""
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_signature(secret: str, timestamp: str, body: bytes, provided: str) -> bool:
    return hmac.compare_digest(sign(secret, timestamp, body), provided or "")


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def validate_target(url: str) -> str:
    """HTTPS required, except for the loopback test receiver."""
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and is_loopback_url(url):
        return url
    raise DispatchRefused(
        f"dispatch URL must be https:// (got {redact(url)}); plain http is only "
        "allowed for the local test receiver on 127.0.0.1"
    )


class Dispatcher:
    def __init__(self, config) -> None:
        self.config = config
        self.enabled = bool(config.get("dispatch.enabled", False))
        self.url = str(config.get("dispatch.url", "") or "")
        self.secret_env = str(config.get("dispatch.secret_env", "DISPATCH_HMAC_SECRET"))
        self.timeout_s = float(config.get("dispatch.timeout_s", 10))
        self.max_retries = int(config.get("dispatch.max_retries", 4))
        self.test_receiver_enabled = bool(config.get("dispatch.local_test_receiver.enabled", True))
        self.test_receiver_url = str(
            config.get("dispatch.local_test_receiver.url", "http://127.0.0.1:8001/dispatch-test")
        )
        self.base_link = str(config.get("app.base_link", "http://127.0.0.1:5173"))

    # -- targeting -----------------------------------------------------------
    def target_for(self, event: dict[str, Any]) -> str | None:
        """Which URL (if any) this event may be sent to."""
        if event.get("demo"):
            # Demo events NEVER reach a real dispatch URL.
            return self.test_receiver_url if self.test_receiver_enabled else None
        if self.enabled and self.url:
            return validate_target(self.url)
        if self.test_receiver_enabled and self.test_receiver_url:
            return self.test_receiver_url
        return None

    # -- payload -------------------------------------------------------------
    def build_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        """Event data plus a login-gated link. No image bytes, no credentials."""
        event_id = int(event["id"])
        return {
            "schema": "torch.camera_fusion.event/v1",
            "event_id": event_id,
            "delivery_id": str(uuid.uuid4()),
            "status": event.get("status"),
            "category": event.get("category", "Fire"),
            "severity": event.get("severity", "Warning"),
            "detected_at": event.get("ts"),
            "updated_at": event.get("updated_at"),
            "camera_key": event.get("camera_key"),
            "camera_score": event.get("score"),
            "confirming_sensor_id": event.get("sensor_id"),
            "confirmation": event.get("confirmation_detail"),
            "demo": bool(event.get("demo")),
            # Login required to view. The image itself is never in the payload.
            "review_url": f"{self.base_link}/events/{event_id}",
            "image_url": f"{self.base_link}/api/frames/{event.get('frame_id')}/image"
            if event.get("frame_id") else None,
            "note": "Open review_url and sign in to view the frame. This payload contains no imagery.",
        }

    # -- sending -------------------------------------------------------------
    def send(self, event: dict[str, Any]) -> bool:
        from .fusion import should_dispatch

        status = str(event.get("status", ""))
        if not should_dispatch(status):
            # Belt and braces: possible_smoke must never leave the dashboard.
            audit_record(
                "dispatch.refused",
                target=f"event:{event.get('id')}",
                detail={"reason": f"status {status} is not dispatchable"},
            )
            return False

        url = self.target_for(event)
        if not url:
            audit_record(
                "dispatch.skipped",
                target=f"event:{event.get('id')}",
                detail={"reason": "no dispatch URL configured"},
            )
            return False

        secret = env_secret(self.secret_env)
        if not secret:
            audit_record(
                "dispatch.skipped",
                target=f"event:{event.get('id')}",
                detail={"reason": f"{self.secret_env} is not set; refusing to send unsigned"},
            )
            return False

        payload = self.build_payload(event)
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(secret, timestamp, body),
            TIMESTAMP_HEADER: timestamp,
            EVENT_ID_HEADER: str(payload["event_id"]),
            DELIVERY_ID_HEADER: str(payload["delivery_id"]),
            "User-Agent": "TorchCameraFusionPrototype/0.1",
        }

        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            ok, status_code, error = self._attempt(url, body, headers)
            db.execute(
                "INSERT INTO dispatch_log (event_id, ts, url, attempt, status_code, ok, error)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    int(event["id"]), datetime.now(timezone.utc).isoformat(), redact(url),
                    attempt, status_code, 1 if ok else 0, redact(error)[:300] if error else None,
                ),
            )
            if ok:
                db.execute(
                    "UPDATE events SET dispatched_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), int(event["id"])),
                )
                audit_record(
                    "dispatch.sent",
                    target=f"event:{event['id']}",
                    detail={"url": redact(url), "attempt": attempt, "status": status_code},
                )
                return True
            if attempt < self.max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 16.0)

        audit_record(
            "dispatch.failed",
            target=f"event:{event['id']}",
            detail={"url": redact(url), "attempts": self.max_retries},
        )
        return False

    def _attempt(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[bool, int | None, str]:
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=False) as client:
                response = client.post(url, content=body, headers=headers)
            return (200 <= response.status_code < 300), response.status_code, ""
        except Exception as exc:
            return False, None, str(exc)
