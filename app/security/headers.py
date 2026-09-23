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

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

MAPBOX_API = "https://api.mapbox.com"
MAPBOX_EVENTS = "https://events.mapbox.com"

CSP = "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self'",
    # Naive UI injects styles at runtime; see SECURITY.md "known gaps".
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    f"connect-src 'self' {MAPBOX_API} {MAPBOX_EVENTS}",
    "worker-src 'self' blob:",
    "child-src 'self' blob:",
    "manifest-src 'self'",
])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, https: bool = False):
        super().__init__(app)
        self.https = https

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
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
