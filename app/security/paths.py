"""Filesystem-path safety.

Rule: on-disk paths are built **only** from identifiers we generate or that we
have validated against ``^[a-z0-9_-]+$``. A camera name from a feed's JSON never
reaches the filesystem, so a camera called ``../../etc/x`` cannot escape the
image folder.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from pathlib import Path

SAFE_ID = re.compile(r"^[a-z0-9_-]{1,64}$")


def slugify_id(raw: str, *, prefix: str = "cam") -> str:
    """Turn arbitrary feed-supplied text into a safe identifier.

    Never returns a value containing ``/``, ``\\`` or ``..``. If nothing usable
    survives, a random suffix is generated so the caller always gets a valid id.
    """
    text = unicodedata.normalize("NFKD", str(raw or "")).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)[:64]
    if not text or not SAFE_ID.match(text):
        text = f"{prefix}-{uuid.uuid4().hex[:12]}"
    return text


def is_safe_id(value: str) -> bool:
    return bool(SAFE_ID.match(str(value or "")))


def safe_join(base: Path, *parts: str) -> Path:
    """Join ``parts`` under ``base``, rejecting anything that escapes ``base``.

    Every part must already be a validated safe id (or a generated filename).
    """
    base = Path(base).resolve()
    for part in parts:
        if not is_safe_id(Path(part).stem.replace(".", "-")) and not _is_safe_filename(part):
            raise ValueError(f"unsafe path component: {part!r}")
    candidate = base.joinpath(*parts).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"path escapes base directory: {candidate}")
    return candidate


_SAFE_FILENAME = re.compile(r"^[a-z0-9_\-]{1,80}\.(jpg|jpeg|png|json|csv)$")


def _is_safe_filename(part: str) -> bool:
    return bool(_SAFE_FILENAME.match(str(part)))
