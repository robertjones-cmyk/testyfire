"""Security headers and CORS.

CSP notes:

* ``script-src 'self'`` — no inline scripts anywhere in the app;
* ``style-src`` has to allow ``'unsafe-inline'`` because Naive UI injects
  component styles at runtime (CSS-in-JS). That is a real, documented weakening
  of the policy; it is recorded in SECURITY.md under known gaps;
* Mapbox needs ``connect-src`` to its API and ``worker-src blob:`` for its
  tile-decoding workers — nothing wider;
* ``frame-ancestors 'none'`` — this app is never framed.
"""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

MAPBOX_API = "https://api.mapbox.com"
MAPBOX_EVENTS = "https://events.mapbox.com"

def inline_script_hashes(index_html: Path) -> list[str]:
    """SHA-256 hashes of the inline scripts in the built index.html.

    The app ships exactly one inline script: the theme bootstrap that runs
    before first paint so there is no flash of the wrong theme. Rather than
    weaken the policy with 'unsafe-inline' — or hard-code a hash that silently
    breaks the moment the script is edited — the hash is computed from the file
    that is actually being served.
    """
    try:
        html = index_html.read_text(encoding="utf-8")
    except OSError:
        return []
    hashes = []
    for match in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I):
        digest = hashlib.sha256(match.group(1).encode("utf-8")).digest()
        hashes.append(f"'sha256-{base64.b64encode(digest).decode('ascii')}'")
    return hashes


def build_csp(script_hashes: list[str] | None = None) -> str:
    script_src = " ".join(["'self'", *(script_hashes or [])])
    return "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
        f"script-src {script_src}",
        # Naive UI injects styles at runtime; see SECURITY.md "known gaps".
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        f"connect-src 'self' {MAPBOX_API} {MAPBOX_EVENTS}",
        "worker-src 'self' blob:",
        "child-src 'self' blob:",
        "manifest-src 'self'",
    ])


#: Default policy with no inline scripts allowed (used when nothing is built).
CSP = build_csp()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, https: bool = False, index_html: Path | None = None):
        super().__init__(app)
        self.https = https
        self.csp = build_csp(inline_script_hashes(index_html) if index_html else None)

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", self.csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if self.https or request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
