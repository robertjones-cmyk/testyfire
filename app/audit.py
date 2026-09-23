"""Audit log — who did what, when.

Logins, failed logins, alert decisions, config changes and demo triggers all
land here. Admin-readable through ``/api/admin/audit``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import db
from .security.redact import redact, redact_mapping


def record(
    action: str,
    *,
    actor_email: str | None = None,
    actor_role: str | None = None,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> int:
    """Append an audit entry. Secrets in ``detail`` are redacted first."""
    safe_detail = json.dumps(redact_mapping(detail or {}), default=str)[:4000]
    return db.insert(
        "INSERT INTO audit_log (ts, actor_email, actor_role, action, target, detail, ip)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            datetime.now(timezone.utc).isoformat(),
            actor_email,
            actor_role,
            action,
            redact(target) if target else None,
            safe_detail,
            ip,
        ),
    )


def recent(limit: int = 200) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 1000),))
    return db.rows_to_dicts(rows)
