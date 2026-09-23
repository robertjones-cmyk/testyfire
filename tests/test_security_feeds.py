"""SSRF, path traversal and credential redaction — the feed attack surface."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.security.images import UnsafeImage, normalise_to_jpeg  # noqa: E402
from app.security.net import (  # noqa: E402
    BlockedRequest,
    check_url,
    resolve_and_check,
    safe_fetch,
)
from app.security.paths import is_safe_id, safe_join, slugify_id  # noqa: E402
from app.security.redact import redact, redact_mapping  # noqa: E402

HTTP_SCHEMES = ("http", "https")


# --------------------------------------------------------------------------- #
# SSRF
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",          # AWS metadata
    "http://169.254.169.254/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://127.0.0.1/",
    "http://localhost:8000/admin",
    "http://10.0.0.5/axis-cgi/jpg/image.cgi",            # private range
    "http://192.168.1.10/snapshot.jpg",
    "http://172.16.4.4/img",
    "http://[::1]/",
])
def test_private_and_metadata_addresses_are_refused(url):
    with pytest.raises(BlockedRequest):
        check_url(url, allowed_schemes=HTTP_SCHEMES)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/x.jpg",
    "gopher://example.com/",
    "dict://example.com:11211/",
    "jar:http://example.com/!/",
    "data:image/jpeg;base64,AAAA",
])
def test_non_http_schemes_are_refused(url):
    with pytest.raises(BlockedRequest):
        check_url(url, allowed_schemes=HTTP_SCHEMES)


def test_feed_tester_refuses_file_url_end_to_end():
    with pytest.raises(BlockedRequest):
        safe_fetch("file:///etc/passwd", allowed_schemes=HTTP_SCHEMES)


def test_private_network_requires_explicit_opt_in():
    """Customer LAN cameras work, but only when the feed asks for it."""
    with pytest.raises(BlockedRequest):
        check_url("http://192.168.1.50/image.jpg", allowed_schemes=HTTP_SCHEMES)
    assert check_url(
        "http://192.168.1.50/image.jpg", allowed_schemes=HTTP_SCHEMES, allow_private=True
    )


def test_rtsp_scheme_rejected_by_an_http_adapter_and_vice_versa():
    with pytest.raises(BlockedRequest):
        check_url("rtsp://camera.example.com/stream", allowed_schemes=HTTP_SCHEMES)
    with pytest.raises(BlockedRequest):
        check_url("https://camera.example.com/x.jpg", allowed_schemes=("rtsp", "rtsps"))


def test_resolve_and_check_blocks_loopback_literal():
    with pytest.raises(BlockedRequest):
        resolve_and_check("127.0.0.1")
    with pytest.raises(BlockedRequest):
        resolve_and_check("169.254.169.254")


def test_redirect_to_a_private_address_is_refused(monkeypatch):
    """A public URL that 302s to the metadata service must not be followed."""
    import httpx

    from app.security import net as net_module

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, content=b"\xff\xd8\xffshould-never-get-here")

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(net_module.httpx, "Client", fake_client)
    # Only the first hop resolves to a public address; the redirect target does not.
    monkeypatch.setattr(net_module, "resolve_and_check", _allow_only("public.example.com"))

    with pytest.raises(BlockedRequest):
        safe_fetch("http://public.example.com/snapshot.jpg", allowed_schemes=HTTP_SCHEMES)


def _allow_only(allowed_host: str):
    def checker(host: str, *, allow_private: bool = False) -> list[str]:
        if host == allowed_host:
            return ["93.184.216.34"]
        raise BlockedRequest(f"blocked non-public address for host {host}")

    return checker


# --------------------------------------------------------------------------- #
# path traversal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("hostile", [
    "../../etc/x",
    "../../../../etc/passwd",
    "..\\..\\windows\\system32",
    "/etc/shadow",
    "cam/../../../root",
    "....//....//etc",
    "‮/etc/passwd",
])
def test_hostile_camera_names_are_slugified_safely(hostile):
    slug = slugify_id(hostile)
    assert is_safe_id(slug)
    assert "/" not in slug and "\\" not in slug and ".." not in slug


def test_camera_named_traversal_is_stored_inside_the_frame_folder(tmp_path):
    from feeds.base import Camera

    camera = Camera(id="../../etc/x", name="../../etc/x", feed_id="evil_feed")
    assert is_safe_id(camera.id)

    base = tmp_path / "frames"
    base.mkdir()
    target = safe_join(base, slugify_id(camera.key), "20260922")
    assert base in target.parents


def test_safe_join_refuses_to_escape():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        with pytest.raises(ValueError):
            safe_join(base, "../outside")
        with pytest.raises(ValueError):
            safe_join(base, "..", "..", "etc")


# --------------------------------------------------------------------------- #
# redaction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,must_not_contain", [
    ("rtsp://admin:hunter2@10.0.0.5/stream1", "hunter2"),
    ("https://user:s3cr3t@cam.example.com/jpg", "s3cr3t"),
    ("https://api.example.com/x?api_key=AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    ("https://api.example.com/x?token=abc123def456", "abc123def456"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiIs", "eyJhbGciOiJIUzI1NiIs"),
    ("key sk-ant-api03-SUPERSECRETVALUE here", "SUPERSECRETVALUE"),
    ("mapbox sk.eyJ1IjoidGVzdCIsImEiOiJjbGFiY2RlZmcifQ.abc", "sk.eyJ1"),
])
def test_redaction_removes_credentials(raw, must_not_contain):
    assert must_not_contain not in redact(raw)


def test_redaction_keeps_the_useful_part():
    redacted = redact("rtsp://admin:hunter2@10.0.0.5:554/Streaming/Channels/101")
    assert "10.0.0.5" in redacted and "Streaming" in redacted
    assert "admin" not in redacted and "hunter2" not in redacted


def test_redact_mapping_masks_secret_keys():
    masked = redact_mapping({
        "url": "rtsp://u:p@host/s",
        "password": "hunter2",
        "api_key": "abc",
        "nested": {"token": "xyz", "camera": "I-40"},
        "count": 3,
    })
    assert masked["password"] == "***" and masked["api_key"] == "***"
    assert masked["nested"]["token"] == "***"
    assert masked["nested"]["camera"] == "I-40" and masked["count"] == 3
    assert "p@host" not in masked["url"]


# --------------------------------------------------------------------------- #
# image intake
# --------------------------------------------------------------------------- #
def test_non_image_bytes_are_refused():
    with pytest.raises(UnsafeImage):
        normalise_to_jpeg(b"<html><body>not an image</body></html>")
    with pytest.raises(UnsafeImage):
        normalise_to_jpeg(b"GIF89a" + b"\x00" * 100)


def test_exif_is_stripped_on_reencode():
    import io

    from PIL import Image

    source = io.BytesIO()
    image = Image.new("RGB", (64, 64), (120, 130, 140))
    exif = image.getexif()
    exif[0x010E] = "SECRET CAMERA LOCATION"      # ImageDescription
    image.save(source, "JPEG", exif=exif)
    assert b"SECRET CAMERA LOCATION" in source.getvalue()

    cleaned, size = normalise_to_jpeg(source.getvalue())
    assert b"SECRET CAMERA LOCATION" not in cleaned
    assert size == (64, 64)


def test_oversized_image_is_refused():
    import io

    from PIL import Image

    from app.security import images as images_module

    small = io.BytesIO()
    Image.new("RGB", (64, 64)).save(small, "JPEG")
    monkey = images_module.MAX_PIXELS
    try:
        images_module.MAX_PIXELS = 100      # 64x64 = 4096 > 100
        with pytest.raises(UnsafeImage):
            normalise_to_jpeg(small.getvalue())
    finally:
        images_module.MAX_PIXELS = monkey
