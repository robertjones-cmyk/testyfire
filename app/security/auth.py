"""Authentication, sessions, CSRF and roles.

Design notes:

* passwords are hashed with **argon2id** (argon2-cffi defaults);
* sessions are **server-side** — the cookie holds an opaque 256-bit id and
  nothing else, so a stolen cookie can be revoked by deleting one row;
* every session carries a CSRF token; state-changing requests must echo it in
  ``X-CSRF-Token``;
* roles are checked **on the server** for every endpoint, never only in the UI;
* login failures are rate limited per account *and* per IP, and the error
  message is always the same regardless of why the login failed.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .. import db

SESSION_COOKIE = "torch_session"
CSRF_HEADER = "X-CSRF-Token"
GENERIC_LOGIN_ERROR = "Email or password is incorrect"
MIN_PASSWORD_LENGTH = 12

ROLES = ("viewer", "operator", "admin")
ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}

_hasher = PasswordHasher()


# --------------------------------------------------------------------------- #
# passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


# --------------------------------------------------------------------------- #
# users
# --------------------------------------------------------------------------- #
def create_user(email: str, password: str, role: str = "viewer") -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    return db.insert(
        "INSERT INTO users (email, password_hash, role, created_at) VALUES (?,?,?,?)",
        (email.strip().lower(), hash_password(password), role, _now_iso()),
    )


def get_user_by_email(email: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    return dict(row) if row else None


def set_password(email: str, password: str) -> bool:
    cursor = db.execute(
        "UPDATE users SET password_hash = ? WHERE email = ?",
        (hash_password(password), email.strip().lower()),
    )
    return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# login rate limiting
# --------------------------------------------------------------------------- #
def record_login_attempt(email: str | None, ip: str | None, success: bool) -> None:
    db.execute(
        "INSERT INTO login_attempts (email, ip, ts, success) VALUES (?,?,?,?)",
        ((email or "").strip().lower() or None, ip, _now_iso(), 1 if success else 0),
    )


def is_rate_limited(email: str | None, ip: str | None, *, max_failures: int, window_minutes: int) -> bool:
    """True when either the account or the IP has too many recent failures."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
    by_email = db.query_one(
        "SELECT COUNT(*) AS n FROM login_attempts"
        " WHERE success = 0 AND ts > ? AND email = ?",
        (since, (email or "").strip().lower()),
    )
    by_ip = db.query_one(
        "SELECT COUNT(*) AS n FROM login_attempts WHERE success = 0 AND ts > ? AND ip = ?",
        (since, ip),
    )
    return bool((by_email and by_email["n"] >= max_failures) or (by_ip and by_ip["n"] >= max_failures))


def clear_failures(email: str, ip: str | None) -> None:
    db.execute(
        "DELETE FROM login_attempts WHERE success = 0 AND (email = ? OR ip = ?)",
        (email.strip().lower(), ip),
    )


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #
def create_session(
    user_id: int,
    *,
    absolute_timeout_minutes: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str]:
    """Create a session. Returns ``(session_id, csrf_token)``."""
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO sessions (id, user_id, csrf_token, created_at, last_seen, expires_at, ip, user_agent)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            session_id,
            user_id,
            csrf_token,
            now.isoformat(),
            now.isoformat(),
            (now + timedelta(minutes=absolute_timeout_minutes)).isoformat(),
            ip,
            (user_agent or "")[:200],
        ),
    )
    return session_id, csrf_token


def load_session(
    session_id: str | None,
    *,
    idle_timeout_minutes: int,
) -> dict[str, Any] | None:
    """Return the session + user, or ``None`` if missing/expired/idle-timed-out.

    Also refreshes ``last_seen``, which is what the idle timeout is measured
    against.
    """
    if not session_id:
        return None
    row = db.query_one(
        "SELECT s.id AS session_id, s.csrf_token, s.created_at, s.last_seen, s.expires_at,"
        "       u.id AS user_id, u.email, u.role, u.disabled"
        " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (session_id,),
    )
    if row is None:
        return None
    data = dict(row)
    if data["disabled"]:
        destroy_session(session_id)
        return None

    now = datetime.now(timezone.utc)
    if now >= _parse(data["expires_at"]):
        destroy_session(session_id)
        return None
    if now - _parse(data["last_seen"]) > timedelta(minutes=idle_timeout_minutes):
        destroy_session(session_id)
        return None

    db.execute("UPDATE sessions SET last_seen = ? WHERE id = ?", (now.isoformat(), session_id))
    data["last_seen"] = now.isoformat()
    data["idle_expires_at"] = (now + timedelta(minutes=idle_timeout_minutes)).isoformat()
    return data


def destroy_session(session_id: str | None) -> None:
    if session_id:
        db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def destroy_user_sessions(user_id: int) -> None:
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def check_csrf(session: dict[str, Any] | None, token: str | None) -> bool:
    if not session or not token:
        return False
    return hmac.compare_digest(str(session.get("csrf_token", "")), str(token))


def role_allows(actual: str | None, required: str) -> bool:
    return ROLE_RANK.get(str(actual), -1) >= ROLE_RANK.get(required, 99)


def purge_expired_sessions() -> int:
    cursor = db.execute("DELETE FROM sessions WHERE expires_at < ?", (_now_iso(),))
    return cursor.rowcount or 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
