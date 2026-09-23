"""Dispatch webhook: signing, HTTPS-only, demo routing, and the payload rules."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.pipeline.dispatch import (  # noqa: E402
    DispatchRefused,
    Dispatcher,
    is_loopback_url,
    sign,
    validate_target,
    verify_signature,
)

SECRET = "a" * 64


def test_signature_round_trip():
    body = b'{"event_id":1}'
    signature = sign(SECRET, "1758585600", body)
    assert signature.startswith("sha256=")
    assert verify_signature(SECRET, "1758585600", body, signature)


def test_signature_fails_on_tampered_body():
    signature = sign(SECRET, "1758585600", b'{"event_id":1}')
    assert not verify_signature(SECRET, "1758585600", b'{"event_id":2}', signature)


def test_signature_fails_on_replayed_timestamp():
    """The timestamp is inside the signed material, so it cannot be swapped."""
    signature = sign(SECRET, "1758585600", b"{}")
    assert not verify_signature(SECRET, "1758589999", b"{}", signature)


def test_signature_fails_with_the_wrong_secret():
    signature = sign(SECRET, "1758585600", b"{}")
    assert not verify_signature("b" * 64, "1758585600", b"{}", signature)


@pytest.mark.parametrize("url", [
    "http://dispatch.example.com/hook",
    "http://10.0.0.1/hook",
    "ftp://example.com/hook",
])
def test_plain_http_targets_are_refused(url):
    with pytest.raises(DispatchRefused):
        validate_target(url)


def test_https_target_is_accepted():
    assert validate_target("https://dispatch.example.com/hook")


def test_loopback_http_is_allowed_for_the_test_receiver():
    assert validate_target("http://127.0.0.1:8001/dispatch-test")
    assert is_loopback_url("http://localhost:8001/x")
    assert not is_loopback_url("http://example.com/x")


def test_payload_carries_a_link_not_an_image(config, database):
    dispatcher = Dispatcher(config)
    payload = dispatcher.build_payload({
        "id": 42, "status": "verified", "ts": "2026-09-22T18:00:00+00:00",
        "updated_at": "2026-09-22T18:01:00+00:00", "camera_key": "feed__cam1",
        "score": 0.81, "sensor_id": "TS-004", "frame_id": 7,
        "confirmation_detail": "Sensor TS-004 inside the camera's view polygon",
        "category": "Fire", "severity": "Critical", "demo": 0,
    })
    serialised = json.dumps(payload)
    assert payload["review_url"].endswith("/events/42")
    assert "image" not in payload or payload["image_url"].endswith("/image")
    # No imagery, no credentials, ever.
    assert "base64" not in serialised and "password" not in serialised
    assert "jpeg" not in serialised.lower()


def test_demo_events_never_reach_a_real_dispatch_url(config, database):
    config.raw["dispatch"]["enabled"] = True
    config.raw["dispatch"]["url"] = "https://real-dispatch.example.com/hook"
    dispatcher = Dispatcher(config)

    real_target = dispatcher.target_for({"id": 1, "status": "verified", "demo": 0})
    demo_target = dispatcher.target_for({"id": 2, "status": "verified", "demo": 1})

    assert real_target == "https://real-dispatch.example.com/hook"
    assert demo_target == "http://127.0.0.1:8001/dispatch-test"


def test_possible_smoke_is_never_sent(config, database, monkeypatch):
    """The core product rule, checked at the dispatcher as well as in fusion."""
    monkeypatch.setenv("DISPATCH_HMAC_SECRET", SECRET)
    config.raw["dispatch"]["enabled"] = True
    config.raw["dispatch"]["url"] = "https://real-dispatch.example.com/hook"
    dispatcher = Dispatcher(config)

    calls: list = []
    monkeypatch.setattr(dispatcher, "_attempt", lambda *a, **k: calls.append(a) or (True, 200, ""))

    db.execute(
        "INSERT INTO events (id, ts, updated_at, status) "
        "VALUES (5,'2026-09-22T00:00:00+00:00','2026-09-22T00:00:00+00:00','possible_smoke')"
    )
    assert dispatcher.send({"id": 5, "status": "possible_smoke", "demo": 0}) is False
    assert calls == [], "possible_smoke must never leave the dashboard"

    entry = db.query_one("SELECT * FROM audit_log WHERE action = 'dispatch.refused'")
    assert entry is not None


def test_missing_secret_blocks_sending_rather_than_sending_unsigned(config, database, monkeypatch):
    monkeypatch.delenv("DISPATCH_HMAC_SECRET", raising=False)
    config.raw["dispatch"]["enabled"] = True
    config.raw["dispatch"]["url"] = "https://real-dispatch.example.com/hook"
    dispatcher = Dispatcher(config)

    calls: list = []
    monkeypatch.setattr(dispatcher, "_attempt", lambda *a, **k: calls.append(a) or (True, 200, ""))

    assert dispatcher.send({"id": 6, "status": "verified", "demo": 0}) is False
    assert calls == []


def test_successful_send_is_logged_and_marks_the_event(config, database, monkeypatch):
    monkeypatch.setenv("DISPATCH_HMAC_SECRET", SECRET)
    config.raw["dispatch"]["enabled"] = True
    config.raw["dispatch"]["url"] = "https://real-dispatch.example.com/hook"
    dispatcher = Dispatcher(config)
    monkeypatch.setattr(dispatcher, "_attempt", lambda *a, **k: (True, 202, ""))

    db.execute(
        "INSERT INTO events (id, ts, updated_at, status) "
        "VALUES (9,'2026-09-22T00:00:00+00:00','2026-09-22T00:00:00+00:00','verified')"
    )
    assert dispatcher.send({"id": 9, "status": "verified", "demo": 0, "frame_id": None}) is True

    assert db.query_one("SELECT dispatched_at FROM events WHERE id=9")["dispatched_at"]
    log_row = db.query_one("SELECT * FROM dispatch_log WHERE event_id = 9")
    assert log_row["ok"] == 1 and log_row["status_code"] == 202


def test_every_failed_attempt_is_logged(config, database, monkeypatch):
    monkeypatch.setenv("DISPATCH_HMAC_SECRET", SECRET)
    config.raw["dispatch"]["enabled"] = True
    config.raw["dispatch"]["url"] = "https://real-dispatch.example.com/hook"
    config.raw["dispatch"]["max_retries"] = 3
    dispatcher = Dispatcher(config)
    monkeypatch.setattr(dispatcher, "_attempt", lambda *a, **k: (False, 500, "server error"))
    monkeypatch.setattr("app.pipeline.dispatch.time.sleep", lambda _s: None)

    db.execute(
        "INSERT INTO events (id, ts, updated_at, status) "
        "VALUES (11,'2026-09-22T00:00:00+00:00','2026-09-22T00:00:00+00:00','sensor_only')"
    )
    assert dispatcher.send({"id": 11, "status": "sensor_only", "demo": 0, "frame_id": None}) is False
    assert db.query_one("SELECT COUNT(*) AS n FROM dispatch_log WHERE event_id=11")["n"] == 3


def test_dispatch_url_with_credentials_is_redacted_in_the_log(config, database, monkeypatch):
    monkeypatch.setenv("DISPATCH_HMAC_SECRET", SECRET)
    config.raw["dispatch"]["enabled"] = True
    config.raw["dispatch"]["url"] = "https://user:hunter2@dispatch.example.com/hook"
    dispatcher = Dispatcher(config)
    monkeypatch.setattr(dispatcher, "_attempt", lambda *a, **k: (True, 200, ""))

    db.execute(
        "INSERT INTO events (id, ts, updated_at, status) "
        "VALUES (13,'2026-09-22T00:00:00+00:00','2026-09-22T00:00:00+00:00','verified')"
    )
    dispatcher.send({"id": 13, "status": "verified", "demo": 0, "frame_id": None})
    logged = db.query_one("SELECT url FROM dispatch_log WHERE event_id=13")["url"]
    assert "hunter2" not in logged and "dispatch.example.com" in logged
