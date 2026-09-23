"""Credential redaction.

Camera URLs routinely carry credentials (``rtsp://user:pass@host/stream``).
:func:`redact` must be applied to every URL that reaches a log line, an error
message, an API response or the UI.
"""
from __future__ import annotations

import re
from typing import Any

# rtsp://user:pass@host  /  https://user:pass@host
_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<user>[^/@:\s]+)(?::(?P<pw>[^/@\s]*))?@")
# ?key=...&token=...&password=...&api_key=...
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:api[_-]?key|key|token|access[_-]?token|password|passwd|pwd|secret|sig|signature)=)[^&\s]*"
)
# Bare high-entropy credentials that show up in headers/log lines.
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")
_ANTHROPIC = re.compile(r"sk-ant-[A-Za-z0-9\-_]{8,}")
_MAPBOX_SECRET = re.compile(r"sk\.[A-Za-z0-9._\-]{20,}")

REDACTED = "***"

_SECRET_KEY_HINT = re.compile(
    r"(?i)(pass|pwd|secret|token|api[_-]?key|authorization|cookie|hmac|credential)"
)


def redact(value: Any) -> str:
    """Return ``value`` as a string with any embedded credential removed."""
    if value is None:
        return ""
    text = str(value)
    text = _USERINFO.sub(lambda m: f"{m.group('scheme')}{REDACTED}:{REDACTED}@", text)
    text = _QUERY_SECRET.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    text = _ANTHROPIC.sub(REDACTED, text)
    text = _MAPBOX_SECRET.sub(REDACTED, text)
    return text


def redact_mapping(data: dict) -> dict:
    """Redact secret-looking values in a flat-ish mapping (for log/audit context)."""
    out: dict = {}
    for key, val in data.items():
        if _SECRET_KEY_HINT.search(str(key)):
            out[key] = REDACTED
        elif isinstance(val, dict):
            out[key] = redact_mapping(val)
        elif isinstance(val, str):
            out[key] = redact(val)
        else:
            out[key] = val
    return out
