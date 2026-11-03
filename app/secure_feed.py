"""Bounded, public-internet-only RSS downloads.

DNS is resolved and vetted at TCP connection time.  The approved numeric IP is
used for the socket, while urllib3 retains the original hostname for HTTP Host,
TLS SNI, and certificate verification.  Do not replace this with URL-only checks.
"""
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests
import urllib3
from urllib3 import connection as urllib3_connection
from urllib3 import connectionpool
from urllib3.exceptions import NameResolutionError, NewConnectionError

MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_FETCH_SECONDS = 30
MAX_REDIRECTS = 3
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10


class FeedFetchError(ValueError):
    """A feed was rejected, oversized or did not complete safely."""


def _validate_url(url):
    if not isinstance(url, str) or len(url) > 2048 or not url or url != url.strip():
        raise FeedFetchError("invalid feed URL")
    try:
        parsed = urlsplit(url)
        # .port also catches malformed ports or unmatched brackets.
        port = parsed.port
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise FeedFetchError("feed URL must be HTTP(S) with a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise FeedFetchError("feed URL must not contain credentials")
        if port == 0:
            raise FeedFetchError("invalid feed port")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
            raise FeedFetchError("invalid control character in feed URL")
    except ValueError as exc:
        raise FeedFetchError("invalid feed URL") from exc
    return url


class _PublicIPConnection:
    """Mixin: never perform a second DNS lookup using the hostname after validation."""

    def _new_conn(self):
        try:
            answers = socket.getaddrinfo(self._dns_host, self.port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise NameResolutionError(self.host, self, exc) from exc
        try:
            # Fail closed on mixed public/private DNS responses, not just the first A record.
            if not answers or any(not ipaddress.ip_address(answer[4][0]).is_global for answer in answers):
                raise FeedFetchError("feed hostname resolves to a non-public IP address")
        except ValueError as exc:
            raise NewConnectionError(self, str(exc)) from exc

        last_error = None
        for _, _, _, _, sockaddr in answers:
            # A numeric address is passed to the connector; TLS still uses self.host.
            try:
                return urllib3_connection.connection.create_connection(
                    (sockaddr[0], self.port),
                    self.timeout,
                    source_address=self.source_address,
                    socket_options=self.socket_options,
                )
            except OSError as exc:
                last_error = exc
        raise NewConnectionError(self, f"could not connect to public feed host: {last_error}") from last_error


class _PublicHTTPConnection(_PublicIPConnection, urllib3_connection.HTTPConnection):
    pass


class _PublicHTTPSConnection(_PublicIPConnection, urllib3_connection.HTTPSConnection):
    pass


class _PublicHTTPPool(connectionpool.HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(connectionpool.HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicIPAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            "http": _PublicHTTPPool,
            "https": _PublicHTTPSPool,
        }


def fetch_feed_bytes(url, user_agent="rss2slideshow/0.2"):
    """Fetch one feed with pinned public IPs, validated redirects and a hard byte cap."""
    current = _validate_url(url)
    started = time.monotonic()
    with requests.Session() as session:
        # Never use ambient proxy settings: they would bypass the validated socket.
        session.trust_env = False
        adapter = _PublicIPAdapter(max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        for hop in range(MAX_REDIRECTS + 1):
            if time.monotonic() - started > MAX_FETCH_SECONDS:
                raise FeedFetchError("RSS fetch exceeded time limit")
            with session.get(
                current,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                headers={"User-Agent": user_agent},
                stream=True,
                allow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    target = response.headers.get("Location", "")
                    if not target:
                        raise FeedFetchError("feed redirect had no Location header")
                    if hop == MAX_REDIRECTS:
                        raise FeedFetchError("too many feed redirects")
                    next_url = _validate_url(urljoin(current, target))
                    if current.startswith("https://") and not next_url.startswith("https://"):
                        raise FeedFetchError("HTTPS feed redirected to unencrypted HTTP")
                    current = next_url
                    continue
                response.raise_for_status()
                length = response.headers.get("Content-Length", "")
                if length.isdecimal() and int(length) > MAX_FEED_BYTES:
                    raise FeedFetchError("RSS feed exceeds 2 MiB response limit")
                chunks = []
                size = 0
                for chunk in response.iter_content(chunk_size=32768):
                    if time.monotonic() - started > MAX_FETCH_SECONDS:
                        raise FeedFetchError("RSS fetch exceeded time limit")
                    size += len(chunk)
                    if size > MAX_FEED_BYTES:
                        raise FeedFetchError("RSS feed exceeds 2 MiB response limit")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise FeedFetchError("RSS fetch did not finish")
