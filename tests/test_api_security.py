"""API auth: 401 without a session, 403 for the wrong role, CSRF, rate limit."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.config import get_config  # noqa: E402
from app.security.auth import CSRF_HEADER, SESSION_COOKIE, create_user  # noqa: E402

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture()
def client(tmp_path, base_config_data, monkeypatch):
    """A TestClient with no lifespan, so no ingest threads start."""
    import copy

    import yaml

    data = copy.deepcopy(base_config_data)
    data["app"]["data_dir"] = str(tmp_path / "data")
    data["app"]["db_path"] = str(tmp_path / "data" / "test.db")
    data["app"]["frames_dir"] = str(tmp_path / "data" / "frames")
    for feed in data["feeds"]:
        feed["enabled"] = False
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(data))

    config = get_config(config_path, reload=True)
    db.configure(config.db_path)
    db.init_db()

    create_user("viewer@torchsystems.com", PASSWORD, "viewer")
    create_user("operator@torchsystems.com", PASSWORD, "operator")
    create_user("admin@torchsystems.com", PASSWORD, "admin")

    from app.main import create_app

    # No context manager -> lifespan (and the ingest worker) does not run.
    yield TestClient(create_app())
    get_config(Path("config.yaml"), reload=True)


def login(client: TestClient, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


# --------------------------------------------------------------------------- #
# 401
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", [
    "/api/cameras", "/api/events", "/api/sensors", "/api/metrics/today",
    "/api/blindspot", "/api/feeds", "/api/config/ui", "/api/camera-views",
    "/api/admin/audit", "/api/admin/users", "/api/admin/feed-health",
    "/api/frames/1/image", "/api/metrics/daily.csv",
])
def test_every_route_requires_a_session(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", [
    "/api/events/1/decision", "/api/admin/users", "/api/admin/demo/fire-scenario",
    "/api/admin/ingest/poll-now", "/api/auth/logout",
])
def test_post_routes_require_a_session(client, path):
    assert client.post(path, json={}).status_code == 401


def test_health_is_the_only_unauthenticated_route(client):
    assert client.get("/api/health").status_code == 200


# --------------------------------------------------------------------------- #
# 403 — wrong role
# --------------------------------------------------------------------------- #
def test_viewer_cannot_decide_an_event(client):
    csrf = login(client, "viewer@torchsystems.com")
    db.execute(
        "INSERT INTO events (id, ts, updated_at, status) "
        "VALUES (1,'2026-09-22T00:00:00+00:00','2026-09-22T00:00:00+00:00','possible_smoke')"
    )
    response = client.post(
        "/api/events/1/decision", json={"label": "false_alarm"}, headers={CSRF_HEADER: csrf}
    )
    assert response.status_code == 403
    assert "operator" in response.json()["detail"]


def test_operator_can_decide_an_event(client):
    csrf = login(client, "operator@torchsystems.com")
    db.execute(
        "INSERT INTO events (id, ts, updated_at, status) "
        "VALUES (1,'2026-09-22T00:00:00+00:00','2026-09-22T00:00:00+00:00','possible_smoke')"
    )
    response = client.post(
        "/api/events/1/decision", json={"label": "real"}, headers={CSRF_HEADER: csrf}
    )
    assert response.status_code == 200
    assert db.query_one("SELECT human_label FROM events WHERE id=1")["human_label"] == "real"


@pytest.mark.parametrize("path,payload", [
    ("/api/admin/users", {"email": "x@y.com", "password": "averylongpassword1", "role": "viewer"}),
    ("/api/admin/demo/fire-scenario", {}),
    ("/api/admin/ingest/poll-now", {}),
])
def test_operator_cannot_use_admin_routes(client, path, payload):
    csrf = login(client, "operator@torchsystems.com")
    assert client.post(path, json=payload, headers={CSRF_HEADER: csrf}).status_code == 403


def test_operator_cannot_read_the_audit_log(client):
    login(client, "operator@torchsystems.com")
    assert client.get("/api/admin/audit").status_code == 403


def test_admin_can_read_the_audit_log(client):
    login(client, "admin@torchsystems.com")
    assert client.get("/api/admin/audit").status_code == 200


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #
def test_state_changing_request_without_csrf_is_rejected(client):
    login(client, "operator@torchsystems.com")
    db.execute(
        "INSERT INTO events (id, ts, updated_at, status) "
        "VALUES (1,'2026-09-22T00:00:00+00:00','2026-09-22T00:00:00+00:00','possible_smoke')"
    )
    response = client.post("/api/events/1/decision", json={"label": "real"})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


def test_wrong_csrf_token_is_rejected(client):
    login(client, "operator@torchsystems.com")
    response = client.post("/api/auth/logout", headers={CSRF_HEADER: "not-the-right-token"})
    assert response.status_code == 403


def test_reads_do_not_need_csrf(client):
    login(client, "viewer@torchsystems.com")
    assert client.get("/api/events").status_code == 200


# --------------------------------------------------------------------------- #
# login behaviour
# --------------------------------------------------------------------------- #
def test_login_error_is_generic_for_unknown_user_and_bad_password(client):
    unknown = client.post("/api/auth/login", json={"email": "nobody@x.com", "password": "whatever12345"})
    wrong = client.post("/api/auth/login", json={"email": "viewer@torchsystems.com", "password": "wrongpassword"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"] == "Email or password is incorrect"


def test_login_rate_limit_kicks_in(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "viewer@torchsystems.com", "password": "badpassword1"})
    blocked = client.post("/api/auth/login", json={"email": "viewer@torchsystems.com", "password": PASSWORD})
    assert blocked.status_code == 429, "a correct password must not bypass the rate limit"


def test_session_cookie_is_httponly_and_samesite_lax(client):
    response = client.post(
        "/api/auth/login", json={"email": "viewer@torchsystems.com", "password": PASSWORD}
    )
    cookie_header = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header.replace("Samesite", "SameSite")


def test_logout_destroys_the_session(client):
    csrf = login(client, "viewer@torchsystems.com")
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout", headers={CSRF_HEADER: csrf}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------- #
# headers and secrets
# --------------------------------------------------------------------------- #
def test_security_headers_are_present(client):
    headers = client.get("/api/health").headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "script-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_secret_mapbox_token_is_never_sent_to_the_browser(client, monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", "sk.thisIsASecretTokenThatMustNotLeak")
    login(client, "viewer@torchsystems.com")
    payload = client.get("/api/config/ui").json()
    assert payload["map"]["token"] == ""
    # The token VALUE must not appear anywhere in the response. (The warning
    # message mentions the "sk." prefix on purpose, so match the value itself.)
    assert "thisIsASecretTokenThatMustNotLeak" not in str(payload)
    assert "secret" in payload["map"]["token_problem"].lower()


def test_public_mapbox_token_is_passed_through(client, monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.publicTokenIsFine")
    login(client, "viewer@torchsystems.com")
    payload = client.get("/api/config/ui").json()
    assert payload["map"]["token"] == "pk.publicTokenIsFine"


def test_frame_endpoint_refuses_paths_outside_the_store(client, tmp_path):
    """Even a poisoned database row cannot make the API serve /etc/passwd."""
    login(client, "viewer@torchsystems.com")
    db.execute(
        "INSERT INTO frames (id, camera_key, ts, path, sha256) VALUES (99,'c','2026-01-01','/etc/passwd','x')"
    )
    assert client.get("/api/frames/99/image").status_code == 403
