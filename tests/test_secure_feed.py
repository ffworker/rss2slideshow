"""Network hardening regression tests. All downloads and sockets are mocked."""
import socket
import unittest
from unittest.mock import MagicMock, patch

from urllib3.exceptions import NewConnectionError

from app import secure_feed


class Response:
    def __init__(self, *, status=200, chunks=(), headers=None):
        self.status_code = status
        self.chunks = chunks
        self.headers = headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise secure_feed.requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        yield from self.chunks


class SecureFeedTests(unittest.TestCase):
    def fake_fetch(self, responses, url="https://news.example/rss"):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.side_effect = responses
        with patch.object(secure_feed.requests, "Session", return_value=session):
            result = secure_feed.fetch_feed_bytes(url)
        return result, session

    def test_streaming_success_and_proxy_bypass(self):
        result, session = self.fake_fetch([Response(chunks=[b"<rss>", b"</rss>"])])
        self.assertEqual(result, b"<rss></rss>")
        self.assertIs(session.trust_env, False)
        self.assertTrue(session.mount.called)
        self.assertEqual(session.get.call_args.kwargs["stream"], True)
        self.assertEqual(session.get.call_args.kwargs["allow_redirects"], False)

    def test_reject_bad_url_before_network(self):
        for url in ("file:///etc/passwd", "http://user:pass@example.org/rss",
                    "http://[::1/rss", "http://example.org:0/rss",
                    "https://example.org/rss\nX: header"):
            with self.subTest(url=url):
                with patch.object(secure_feed.requests, "Session") as session:
                    with self.assertRaises(secure_feed.FeedFetchError):
                        secure_feed.fetch_feed_bytes(url)
                    session.assert_not_called()

    def test_bounded_stream_even_when_content_length_lies(self):
        with self.assertRaisesRegex(secure_feed.FeedFetchError, "2 MiB"):
            self.fake_fetch([Response(chunks=[b"x" * secure_feed.MAX_FEED_BYTES, b"x"])])
        with self.assertRaisesRegex(secure_feed.FeedFetchError, "2 MiB"):
            self.fake_fetch([Response(headers={"Content-Length": str(secure_feed.MAX_FEED_BYTES + 1)})])

    def test_https_redirects_stay_https_and_are_bounded(self):
        result, session = self.fake_fetch([
            Response(status=302, headers={"Location": "/next"}),
            Response(chunks=[b"<feed/>"]),
        ])
        self.assertEqual(result, b"<feed/>")
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[1].args[0], "https://news.example/next")
        with self.assertRaisesRegex(secure_feed.FeedFetchError, "unencrypted"):
            self.fake_fetch([Response(status=302, headers={"Location": "http://news.example/rss"})])
        with self.assertRaisesRegex(secure_feed.FeedFetchError, "too many"):
            self.fake_fetch([Response(status=302, headers={"Location": "/loop"}) for _ in range(4)])

    def test_timeout_budget_applies_across_streaming_chunks(self):
        with patch.object(secure_feed.time, "monotonic", side_effect=[0, 0, 31]):
            with self.assertRaisesRegex(secure_feed.FeedFetchError, "time limit"):
                self.fake_fetch([Response(chunks=[b"x"])])

    def test_blocks_private_and_mixed_dns_before_opening_socket(self):
        for addresses in (["127.0.0.1"], ["8.8.8.8", "10." + "1.1.1"],
                          ["169.254.169.254"], ["::1"], ["100.96.41.106"]):
            records = [(socket.AF_INET6 if ":" in a else socket.AF_INET,
                        socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]
            with self.subTest(addresses=addresses), \
                 patch.object(secure_feed.socket, "getaddrinfo", return_value=records), \
                 patch.object(secure_feed.urllib3_connection.connection, "create_connection") as connect:
                conn = secure_feed._PublicHTTPSConnection("news.example", port=443)
                with self.assertRaises(NewConnectionError):
                    conn._new_conn()
                connect.assert_not_called()

    def test_connects_to_vetted_numeric_ip_but_retains_tls_hostname(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        sentinel = object()
        with patch.object(secure_feed.socket, "getaddrinfo", return_value=records), \
             patch.object(secure_feed.urllib3_connection.connection, "create_connection",
                          return_value=sentinel) as connect:
            conn = secure_feed._PublicHTTPSConnection("news.example", port=443)
            self.assertIs(conn._new_conn(), sentinel)
            self.assertEqual(conn.host, "news.example")
            self.assertEqual(connect.call_args.args[0], ("8.8.8.8", 443))


if __name__ == "__main__":
    unittest.main()
