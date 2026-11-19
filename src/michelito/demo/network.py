"""The visitor's IP for the per-day copy quota (in memory only, never on disk).

- Without trusted proxies (`--trusted-proxy`), the connection's IP is used and the forwarding
  headers are **ignored**: anyone can send a made-up `X-Forwarded-For`.
- If the connection comes from a trusted proxy (Caddy), `X-Forwarded-For` is walked right to left
  skipping the trusted proxies: the first one that is not trusted was added by the last trusted
  proxy. The ones further left may have been written by the client and are not looked at.
- The quota key (`quota_key`): an IPv4 is its address (the /24 would group neighbors that have
  nothing to do with each other; a connection shared through NAT already shares an address); an
  IPv6 is grouped by its /64 (what a single household usually gets, which can change the last 64
  bits at will). What cannot be understood falls into `UNKNOWN`, a single quota for everyone. An
  IPv6 also counts in its /56 and its /48 (`quota_keys`), with wider quotas: whoever hands out a
  /48 does not get 65,536 quotas.
- Without trusted proxies, an `X-Forwarded-For` arriving from loopback or a private network is
  almost surely an unconfigured proxy: it is logged once (`warn_unconfigured_proxy`).
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Iterable, Sequence

from starlette.requests import Request

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
UNKNOWN = "unknown"
# IPv6 prefixes that also have a quota, with how many times the per-IP quota they get.
IPV6_WIDER = ((56, 2), (48, 4))
log = logging.getLogger(__name__)
_warned = False


def networks(texts: Iterable[str]) -> tuple[Network, ...]:
    """The networks of the trusted proxies ("127.0.0.1", "10.0.0.0/8", "::1"…)."""
    return tuple(ipaddress.ip_network(t.strip(), strict=False) for t in texts if t.strip())


def _parse(text: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address((text or "").strip())
    except ValueError:
        return None


def _trusted(address: str | None, proxies: Sequence[Network]) -> bool:
    parsed = _parse(address)
    return parsed is not None and any(parsed in net for net in proxies)


def client_ip(request: Request, proxies: Sequence[Network]) -> str | None:
    """The visitor's IP (see the module docstring); None if unknown."""
    peer = request.client.host if request.client else None
    if not _trusted(peer, proxies):
        return peer
    joined = ",".join(request.headers.getlist("x-forwarded-for"))  # it may come repeated
    hops = [hop.strip() for hop in joined.split(",")]
    for hop in reversed([h for h in hops if h]):
        if not _trusted(hop, proxies):
            return hop
    return peer


def quota_key(address: str | None) -> str:
    """The per-IP quota key: the whole IPv4, the IPv6 by /64, or `UNKNOWN`."""
    parsed = _parse(address)
    if parsed is None:
        return UNKNOWN
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        return str(ipaddress.ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


def quota_keys(address: str | None) -> tuple[tuple[str, int], ...]:
    """The quotas an IP counts in: (key, times the per-IP quota). The first one is
    `quota_key`; an IPv6 adds its /56 and its /48."""
    key = quota_key(address)
    parsed = _parse(address)
    if not isinstance(parsed, ipaddress.IPv6Address) or parsed.ipv4_mapped is not None:
        return ((key, 1),)
    wider = tuple(
        (str(ipaddress.ip_network(f"{parsed}/{bits}", strict=False)), factor)
        for bits, factor in IPV6_WIDER
    )
    return ((key, 1), *wider)


def warn_unconfigured_proxy(request: Request, proxies: Sequence[Network]) -> None:
    """Warn (once per process) if there seems to be a proxy in front without `--trusted-proxy`."""
    global _warned
    if _warned or proxies or not request.headers.get("x-forwarded-for"):
        return
    peer = _parse(request.client.host if request.client else None)
    if peer is not None and (peer.is_private or peer.is_loopback):
        _warned = True
        log.warning(
            "X-Forwarded-For arrives from %s without --trusted-proxy: every visitor shares "
            'that IP\'s quota. Configure the proxy (see README, "Demo").',
            peer,
        )
