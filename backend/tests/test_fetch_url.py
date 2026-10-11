"""fetch_url against a local HTTP server: every resolved address is checked, and only the checked one is dialled.

Names resolve through a stub; IP literals go through the real getaddrinfo, which needs no network for a literal.
The dial hook records the checked address and port, then sends the connection to the local server.
"""

import asyncio
import gzip
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from loreos import fetch_url
from loreos.fetch_url import MAX_BYTES, MAX_REDIRECTS, HTTPStatus, Refused, TooLarge, UnsupportedContent, fetch, normalise

PUBLIC = "93.184.216.34"
NAMES = {
    "public.test": [PUBLIC],
    "private.test": ["10.0.0.1"],
    "mixed.test": [PUBLIC, "10.0.0.1"],
    "empty.test": [],
    "nat64.test": ["64:ff9b::a00:1"],  # NAT64 (RFC 6052) carrying 10.0.0.1; ipaddress calls the prefix global
}
PAGES = {
    "/page.html": ("text/html; charset=utf-8", b"<p>hello</p>"),
    "/page.xhtml": ("application/xhtml+xml", b"<p>hello</p>"),
    "/notes.txt": ("text/plain", b"plain words"),
    "/doc.pdf": ("application/pdf", b"%PDF-1.4 not really"),
    "/image.png": ("image/png", b"\x89PNG"),
}
SLOW_S = 1


class Handler(BaseHTTPRequestHandler):
    """/hops/<n> redirects n times; /status/<code> answers that code; /gzip/<n> is n zero bytes, gzipped."""

    def do_GET(self):
        path = self.path
        if path.startswith("/hops/"):
            hops = int(path.removeprefix("/hops/"))
            if hops:
                return self.send(302, b"", {"Location": f"/hops/{hops - 1}"})
            return self.send(200, b"<p>end</p>", {"Content-Type": "text/html"})
        if path == "/to-private":
            return self.send(302, b"", {"Location": "http://private.test/page.html"})
        if path.startswith("/status/"):
            return self.send(int(path.removeprefix("/status/")), b"no", {"Content-Type": "text/plain"})
        if path.startswith("/gzip/"):
            body = gzip.compress(b"\0" * int(path.removeprefix("/gzip/")))
            return self.send(200, body, {"Content-Type": "text/plain", "Content-Encoding": "gzip"})
        if path == "/slow":
            time.sleep(SLOW_S)
            path = "/page.html"
        content_type, body = PAGES[path]
        self.send(200, body, {"Content-Type": content_type})

    def send(self, status, body, headers):
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def port():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield httpd.server_port
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def get(port):
    """get(url) fetches through the stub resolver (resolver=None for the real one); get.dialled lists each dial."""
    dialled = []

    async def stub(host, _port):
        return NAMES[host]

    def dial(address, dial_port):
        dialled.append((address, dial_port))
        return "127.0.0.1", port

    def go(url, resolver=stub):
        return asyncio.run(fetch(url, resolve=resolver, dial=dial))

    go.dialled = dialled
    return go


# Refused


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "[::ffff:127.0.0.1]", "224.0.0.1"])
def test_a_private_address_is_refused(get, host):
    with pytest.raises(Refused):
        get(f"http://{host}/page.html", resolver=None)
    assert get.dialled == []


@pytest.mark.parametrize("name", ["mixed.test", "empty.test", "nat64.test"])
def test_a_name_is_refused_unless_every_address_is_public(get, name):
    with pytest.raises(Refused):
        get(f"http://{name}/page.html")
    assert get.dialled == []


def test_a_redirect_to_a_private_name_is_refused(get):
    with pytest.raises(Refused):
        get("http://public.test/to-private")
    assert get.dialled == [(PUBLIC, 80)]


def test_five_redirects_are_followed_and_a_sixth_is_refused(get):
    fetched = get(f"http://public.test/hops/{MAX_REDIRECTS}")
    assert (fetched.kind, fetched.url) == ("html", "http://public.test/hops/0")
    with pytest.raises(Refused, match="redirects"):
        get(f"http://public.test/hops/{MAX_REDIRECTS + 1}")


@pytest.mark.parametrize("url", ["ftp://public.test/page.html", "http://user:pw@public.test/page.html"])
def test_another_scheme_or_userinfo_is_refused(get, url):
    with pytest.raises(Refused):
        get(url)
    assert get.dialled == []


@pytest.mark.parametrize("url", ["http:///page.html", "http://public.test:99999/", "http://[::1/"])
def test_normalise_refuses_a_url_without_a_usable_host(url):
    with pytest.raises(Refused):
        normalise(url)


def test_normalise():
    assert normalise("HTTP://Public.TEST:80/a?b=1#part") == "http://public.test/a?b=1"
    assert normalise("https://public.test:443") == "https://public.test/"
    assert normalise("https://public.test:8443/x") == "https://public.test:8443/x"
    assert normalise("http://[2001:db8::1]:8080") == "http://[2001:db8::1]:8080/"


# Pinned


def test_the_dialled_address_is_the_checked_one(get):
    fetched = get("http://public.test/page.html")
    assert fetched.content == b"<p>hello</p>"
    assert get.dialled == [(PUBLIC, 80)]


def test_a_proxy_in_the_environment_is_ignored(get, monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    assert get("http://public.test/page.html").kind == "html"
    assert get.dialled == [(PUBLIC, 80)]


# Limits


def test_decoded_bytes_are_counted(get):
    assert len(get(f"http://public.test/gzip/{MAX_BYTES}").content) == MAX_BYTES
    with pytest.raises(TooLarge):
        get(f"http://public.test/gzip/{MAX_BYTES + 1}")


def test_a_slow_server_times_out(get, monkeypatch):
    monkeypatch.setattr(fetch_url, "TIMEOUT_S", SLOW_S / 4)
    with pytest.raises(TimeoutError):
        get("http://public.test/slow")


# Status and type


@pytest.mark.parametrize("status", [404, 503])
def test_an_error_status_raises(get, status):
    with pytest.raises(HTTPStatus) as caught:
        get(f"http://public.test/status/{status}")
    assert caught.value.status == status


def test_an_unsupported_type_is_named(get):
    with pytest.raises(UnsupportedContent, match="image/png"):
        get("http://public.test/image.png")


@pytest.mark.parametrize(
    ("path", "kind"), [("/page.html", "html"), ("/page.xhtml", "html"), ("/notes.txt", "txt"), ("/doc.pdf", "pdf")]
)
def test_each_type_maps_to_its_kind(get, path, kind):
    fetched = get(f"http://public.test{path}")
    assert (fetched.content, fetched.kind, fetched.url) == (PAGES[path][1], kind, f"http://public.test{path}")
