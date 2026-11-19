"""La IP del visitante para el cupo de copias por día (solo en memoria, nunca a disco).

- Sin proxies confiables (`--proxy-confiable`), se usa la IP de la conexión y se **ignoran** las
  cabeceras de reenvío: cualquiera puede mandar un `X-Forwarded-For` inventado.
- Si la conexión viene de un proxy confiable (Caddy), se recorre `X-Forwarded-For` de derecha a
  izquierda saltando los proxies confiables: la primera que no lo es la agregó el último proxy
  confiable. Las de más a la izquierda las pudo escribir el cliente y no se miran.
- La clave del cupo (`quota_key`): una IPv4 es su dirección (el /24 juntaría a vecinos que no
  tienen nada que ver; una conexión compartida por NAT ya comparte dirección); una IPv6 se junta
  por su /64 (lo que suele recibir un solo hogar, que puede cambiar los últimos 64 bits a gusto).
  Lo que no se entiende cae en `UNKNOWN`, un solo cupo para todos. Una IPv6 cuenta además en su
  /56 y su /48 (`quota_keys`), con cupos más anchos: quien reparte un /48 no saca 65,536 cupos.
- Sin proxies confiables, un `X-Forwarded-For` que llega desde loopback o una red privada casi
  seguro es un proxy sin configurar: se avisa una vez en el registro (`warn_unconfigured_proxy`).
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Iterable, Sequence

from starlette.requests import Request

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
UNKNOWN = "desconocida"
# Prefijos IPv6 que también tienen cupo, con cuántas veces el cupo por IP les toca.
IPV6_WIDER = ((56, 2), (48, 4))
log = logging.getLogger(__name__)
_warned = False


def networks(texts: Iterable[str]) -> tuple[Network, ...]:
    """Las redes de los proxies confiables («127.0.0.1», «10.0.0.0/8», «::1»…)."""
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
    """La IP del visitante (ver el docstring del módulo); None si no se sabe."""
    peer = request.client.host if request.client else None
    if not _trusted(peer, proxies):
        return peer
    joined = ",".join(request.headers.getlist("x-forwarded-for"))  # puede venir repetida
    hops = [hop.strip() for hop in joined.split(",")]
    for hop in reversed([h for h in hops if h]):
        if not _trusted(hop, proxies):
            return hop
    return peer


def quota_key(address: str | None) -> str:
    """La clave del cupo por IP: la IPv4 entera, la IPv6 por /64, o `UNKNOWN`."""
    parsed = _parse(address)
    if parsed is None:
        return UNKNOWN
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        return str(ipaddress.ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


def quota_keys(address: str | None) -> tuple[tuple[str, int], ...]:
    """Los cupos en que cuenta una IP: (clave, veces el cupo por IP). La primera es
    `quota_key`; una IPv6 suma su /56 y su /48."""
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
    """Avisa (una vez por proceso) si parece haber un proxy delante sin `--proxy-confiable`."""
    global _warned
    if _warned or proxies or not request.headers.get("x-forwarded-for"):
        return
    peer = _parse(request.client.host if request.client else None)
    if peer is not None and (peer.is_private or peer.is_loopback):
        _warned = True
        log.warning(
            "llega X-Forwarded-For desde %s sin --proxy-confiable: todos los visitantes "
            "comparten el cupo de esa IP. Configura el proxy (ver README, «Demo»).",
            peer,
        )
