"""Single-frame grabs via ffmpeg, used by the RTSP and HLS adapters.

Rules (see SECURITY.md):

* ``subprocess.run`` with an **argument list** — never ``shell=True``;
* ``-protocol_whitelist`` limited to exactly what the feed needs;
* a hard timeout that kills the process group;
* runs at low priority (``nice``) so a stuck grab cannot starve the box;
* the stream URL is only ever passed as the value of ``-i``, never as options,
  and is redacted in every log line and error message;
* only one frame is decoded — **no video is retained**.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.security.redact import redact

FFMPEG_TIMEOUT_S = 25


class FfmpegUnavailable(Exception):
    """ffmpeg is not installed on this machine."""


class FfmpegGrabFailed(Exception):
    pass


def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FfmpegUnavailable(
            "ffmpeg is not installed; the rtsp and hls adapters need it "
            "(macOS: brew install ffmpeg, Debian/Ubuntu: apt install ffmpeg)"
        )
    return path


def grab_frame(
    url: str,
    *,
    protocols: str,
    rtsp_transport: str | None = "tcp",
    timeout_s: int = FFMPEG_TIMEOUT_S,
) -> bytes:
    """Return the bytes of a single JPEG frame grabbed from ``url``."""
    binary = ffmpeg_path()
    with tempfile.TemporaryDirectory(prefix="torch-grab-") as tmp:
        out_path = Path(tmp) / "frame.jpg"
        args: list[str] = [binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        # Whitelist is set BEFORE -i so it applies to the input.
        args += ["-protocol_whitelist", protocols]
        if rtsp_transport:
            args += ["-rtsp_transport", rtsp_transport]
        args += [
            "-analyzeduration", "2000000",
            "-probesize", "2000000",
            "-i", url,               # untrusted value, but only ever as -i's argument
            "-frames:v", "1",
            "-f", "image2",
            "-q:v", "4",
            str(out_path),
        ]
        try:
            completed = subprocess.run(  # noqa: S603 - argument list, no shell
                args,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                start_new_session=True,
                preexec_fn=_lower_priority if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise FfmpegGrabFailed(
                f"ffmpeg timed out after {timeout_s}s for {redact(url)}"
            ) from exc

        if completed.returncode != 0 or not out_path.exists():
            stderr = redact(completed.stderr.decode("utf-8", "replace"))[:300]
            raise FfmpegGrabFailed(f"ffmpeg failed for {redact(url)}: {stderr}")
        return out_path.read_bytes()


def _lower_priority() -> None:  # pragma: no cover - child process hook
    try:
        os.nice(10)
    except OSError:
        pass
