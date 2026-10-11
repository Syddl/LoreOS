"""Fetch one page for URL import. Every hop's addresses are checked, then the connection dials the checked address.

The dial is pinned below httpx2, so a host that resolves differently on a second lookup, an environment proxy
or a parser disagreement over the host can never send the connection anywhere but the checked address.
TLS still uses the URL's host name for SNI and the certificate check.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpcore2
import httpx2

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 10
MAX_REDIRECTS = 5
DEFAULT_PORTS = {"http": 80, "https": 443}
# Prefixes that carry an IPv4 address in their last 32 bits, which ipaddress calls global whatever that address is:
# NAT64 (RFC 6052) and the deprecated IPv4-compatible form (RFC 4291, ::a.b.c.d).
CARRIES_IPV4 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("::/96"))
KINDS = {"text/html": "html", "application/xhtml+xml": "html", "text/plain": "txt", "application/pdf": "pdf"}

Resolve = Callable[[str, int], Awaitable[list[str]]]
Dial = Callable[[str, int], tuple[str, int]]


class Refused(ValueError):
    pass


class TooLarge(ValueError):
    pass


class UnsupportedContent(ValueError):
    pass


class HTTPStatus(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"{url} answered HTTP {status}; check that the page is public and try again")
        self.status = status


@dataclass(frozen=True)
class Fetched:
    content: bytes
    kind: Literal["html", "txt", "pdf"]
    url: str


def normalise(url: str) -> str:
    """The URL with scheme and host lowercased, the default port and the fragment dropped, and `/` for no path."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError as e:
        raise Refused(f"{url!r} is not a valid URL ({e}); check it and try again") from e
    if parts.scheme not in DEFAULT_PORTS:
        raise Refused(f"{url!r} is not an http or https URL; only web pages can be imported")
    if "@" in parts.netloc:
        raise Refused(f"{url!r} carries a user name or password; remove the part before @")
    if not host:
        raise Refused(f"{url!r} has no host; give the full address, such as https://example.com/page")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != DEFAULT_PORTS[parts.scheme]:
        netloc += f":{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


async def fetch(url: str, *, resolve: Resolve | None = None, dial: Dial | None = None) -> Fetched:
    """Fetch one page, following at most MAX_REDIRECTS redirects, each checked like the first URL.

    resolve(host, port) returns every address of host (default: the loop's getaddrinfo).
    dial(address, port) is a test hook that returns where to connect instead of the checked address.
    """
    url = normalise(url)
    async with asyncio.timeout(TIMEOUT_S):
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            port = parts.port or DEFAULT_PORTS[parts.scheme]
            address = await _checked(parts.hostname, port, resolve or _getaddrinfo)
            async with _client(address, port, dial) as client, client.stream("GET", url) as response:
                if response.has_redirect_location:
                    url = normalise(urljoin(url, response.headers["location"]))
                    continue
                return await _read(response, url)
    raise Refused(f"{url} redirects more than {MAX_REDIRECTS} times; import the page it ends on")


async def _getaddrinfo(host: str, port: int) -> list[str]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise httpx2.ConnectError(f"cannot resolve {host} ({e}); check the address") from e
    return [info[4][0] for info in infos]


async def _checked(host: str, port: int, resolve: Resolve) -> str:
    """The first address of host, once every address is public. No address at all is refused too."""
    addresses = [getattr(a, "ipv4_mapped", None) or a for a in map(ipaddress.ip_address, await resolve(host, port))]
    bad = [str(a) for a in addresses if not _public(a)]
    if bad or not addresses:
        found = ", ".join(bad) or "no address"
        raise Refused(f"{host} resolves to {found}; only pages on public addresses can be imported")
    return str(addresses[0])


def _public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Global and not multicast. NAT64 and IPv4-compatible addresses are judged by the IPv4 address they carry; 6to4
    and Teredo are not global."""
    if any(address in network for network in CARRIES_IPV4):
        address = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return address.is_global and not address.is_multicast


class _Pinned(httpcore2.AnyIOBackend):
    """Connects to the checked address whatever host the request names."""

    def __init__(self, address: str, port: int, dial: Dial | None) -> None:
        self._target = (address, port)
        self._dial = dial

    async def connect_tcp(self, host: str, port: int, **kwargs) -> httpcore2.AsyncNetworkStream:
        target = self._dial(*self._target) if self._dial else self._target
        return await super().connect_tcp(*target, **kwargs)


def _client(address: str, port: int, dial: Dial | None) -> httpx2.AsyncClient:
    ssl_context = httpx2.create_ssl_context(trust_env=False)
    transport = httpx2.AsyncHTTPTransport(verify=ssl_context)
    # httpx2's transport takes no network backend, so its pool is swapped for one whose backend is pinned.
    transport._pool = httpcore2.AsyncConnectionPool(ssl_context=ssl_context, network_backend=_Pinned(address, port, dial))
    return httpx2.AsyncClient(transport=transport, trust_env=False, follow_redirects=False)


async def _read(response: httpx2.Response, url: str) -> Fetched:
    if response.status_code >= 400:
        raise HTTPStatus(response.status_code, url)
    mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
    kind = KINDS.get(mime)
    if kind is None:
        raise UnsupportedContent(f"{url} is {mime or 'of no stated type'}; import an HTML, plain text or PDF page")
    content = bytearray()
    async for chunk in response.aiter_bytes():
        content += chunk
        if len(content) > MAX_BYTES:
            raise TooLarge(f"{url} is larger than {MAX_BYTES // (1024 * 1024)} MB; import a smaller page")
    return Fetched(bytes(content), kind, url)
