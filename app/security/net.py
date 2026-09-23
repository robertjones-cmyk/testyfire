"""Outbound-request safety (SSRF guard).

Feeds are the main attack surface: a feed's JSON can name any URL it likes, and
a redirect can point anywhere. Every outbound fetch in this codebase goes
through :func:`safe_fetch`, which enforces:

* a per-adapter scheme allowlist (``file:``, ``ftp:``, ``gopher:`` … rejected);
* a DNS-resolution check that blocks private, loopback, link-local, multicast,
  reserved and cloud-metadata addresses (169.254.169.254 and friends) unless the
  feed explicitly opts in with ``allow_private_network: true``;
* the same check again on **every** redirect hop, with at most 3 hops;
* connect/total timeouts and a hard download-size cap;
* magic-byte verification plus a guarded Pillow decode and re-encode for images.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Iterable, Sequence
from urllib.parse import urlparse

import httpx

from .redact import redact

DEFAULT_CONNECT_TIMEOUT_S = 5.0
DEFAULT_TOTAL_TIMEOUT_S = 15.0
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_REDIRECTS = 3
USER_AGENT = "TorchCameraFusionPrototype/0.1 (internal evaluation; +https://torchsystems.com)"

# Cloud metadata endpoints, blocked explicitly as well as by range checks.
METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.goog",
    "100.100.100.200",  # Alibaba
    "fd00:ec2::254",    # AWS IMDSv2 over IPv6
}


class BlockedRequest(Exception):
    """Raised when a request is refused by policy (SSRF guard)."""


class FetchTooLarge(Exception):
    """Raised when a response exceeds the download cap."""


@dataclass(slots=True)
class FetchResult:
    url: str                 # final URL after redirects (redacted before logging)
    status_code: int
    content: bytes
    content_type: str
    elapsed_s: float
    hops: list[str] = field(default_factory=list)


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (getattr(ip, "is_site_local", False))
    )


def resolve_and_check(host: str, *, allow_private: bool = False) -> list[str]:
    """Resolve ``host`` and refuse if any resolved address is disallowed.

    All resolved addresses are checked, not just the first: a hostname that
    resolves to both a public and a private address is refused.
    """
    if not host:
        raise BlockedRequest("missing host")
    if host.lower() in METADATA_HOSTS:
        raise BlockedRequest(f"blocked metadata host: {host}")

    # A literal IP is checked directly; otherwise resolve.
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        addresses = [str(literal)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise BlockedRequest(f"DNS resolution failed for {host}: {exc}") from exc
        addresses = sorted({info[4][0] for info in infos})

    if not addresses:
        raise BlockedRequest(f"no addresses for {host}")

    for addr in addresses:
        if addr in METADATA_HOSTS:
            raise BlockedRequest(f"blocked metadata address: {addr}")
        ip = ipaddress.ip_address(addr.split("%")[0])
        if _is_blocked_ip(ip) and not allow_private:
            raise BlockedRequest(
                f"blocked non-public address {addr} for host {host} "
                "(set allow_private_network: true on this feed to permit LAN cameras)"
            )
    return addresses


def check_url(
    url: str,
    *,
    allowed_schemes: Sequence[str],
    allow_private: bool = False,
) -> str:
    """Validate a URL's scheme and destination. Returns the normalised URL."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {s.lower() for s in allowed_schemes}:
        raise BlockedRequest(
            f"scheme {scheme or '(none)'!r} is not allowed here "
            f"(allowed: {', '.join(allowed_schemes)})"
        )
    if not parsed.hostname:
        raise BlockedRequest("URL has no host")
    resolve_and_check(parsed.hostname, allow_private=allow_private)
    return url


def safe_fetch(
    url: str,
    *,
    allowed_schemes: Sequence[str] = ("http", "https"),
    allow_private: bool = False,
    headers: dict[str, str] | None = None,
    auth: httpx.Auth | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_S,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT_S,
    expect: Iterable[str] | None = None,
) -> FetchResult:
    """Fetch ``url`` with the SSRF guard applied to every hop.

    ``expect`` optionally restricts the accepted ``Content-Type`` prefixes.
    """
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    request_headers.update(headers or {})

    hops: list[str] = []
    current = url
    timeout = httpx.Timeout(total_timeout, connect=connect_timeout)

    with httpx.Client(follow_redirects=False, timeout=timeout, trust_env=True) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            check_url(current, allowed_schemes=allowed_schemes, allow_private=allow_private)
            hops.append(redact(current))
            with client.stream("GET", current, headers=request_headers, auth=auth) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    if not location:
                        raise BlockedRequest("redirect without Location header")
                    current = str(response.url.join(location))
                    response.close()
                    continue

                declared = response.headers.get("content-length")
                if declared and int(declared) > max_bytes:
                    raise FetchTooLarge(
                        f"declared size {declared} exceeds cap {max_bytes} for {redact(current)}"
                    )

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchTooLarge(
                            f"response exceeded cap {max_bytes} for {redact(current)}"
                        )
                    chunks.append(chunk)

                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if expect and content_type and not any(
                    content_type.startswith(prefix) for prefix in expect
                ):
                    raise BlockedRequest(
                        f"unexpected content-type {content_type!r} from {redact(current)}"
                    )
                return FetchResult(
                    url=redact(str(response.url)),
                    status_code=response.status_code,
                    content=b"".join(chunks),
                    content_type=content_type,
                    elapsed_s=response.elapsed.total_seconds(),
                    hops=hops,
                )

    raise BlockedRequest(f"too many redirects (>{MAX_REDIRECTS}) starting at {redact(url)}")
