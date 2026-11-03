# Deployment

Requirements: Docker Engine, Docker Compose plugin, Git and your own RSS feed.

```sh
git clone https://github.com/ffworker/rss2slideshow.git
cd rss2slideshow
cp .env.example .env
cp config.example.yaml config.yaml
cp content/feeds.example.txt content/feeds.txt
# Set ADMIN_USER and ADMIN_PASSWORD in .env and configure your feed.
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

The sample feed URL is deliberately not a working source. Replace it with a feed whose content you are permitted to display. Admin login requires both credentials to be set.

The image runs Gunicorn with **one worker process and four request threads**.
The single worker matters: the periodic RSS refresh loop and article cache
are in that process's memory. More worker processes would create independent
RSS caches. Do not enable Gunicorn `--preload`; its RSS refresh loop must start
after the worker process is forked.

## RSS feed egress policy

Feed URLs configured via the editor or `content/feeds.txt` are treated as untrusted.
The application downloads only HTTP(S) feeds resolving **exclusively to public IP
addresses**, including checking every DNS A/AAAA answer immediately before the TCP
connection. It connects to that vetted numeric IP without another hostname lookup,
while retaining normal TLS certificate validation, SNI and Host headers. Each
redirect is handled independently, with a maximum of three redirects and no
HTTPS-to-HTTP downgrade. Ambient HTTP proxy environment variables are ignored
for feed downloads so proxies cannot bypass the socket restrictions.

Downloads are streamed with a 2 MiB decompressed body limit, a 30-second overall
fetch budget, and separate connect/read timeouts. An unsafe or oversized feed is
logged as failed; previously cached articles remain available if present. The
admin status panel and `/healthz` provide failed-feed counts and last successful
fetch information. `/healthz` remains a **process health** endpoint, not a content
freshness probe.

This security policy intentionally **does not support internal RSS feeds**, such
as localhost, 10.x / 172.16.x / 192.168.x services, link-local metadata endpoints
or VPN-only IPs. Deploy an approved public RSS gateway if internal content must
be displayed. This protects **server-side feed retrieval**; browser-requested
external article images and user-scanned QR links are separate egress paths. On
untrusted feeds, leave `news_images: false` and restrict the kiosk browser's
network access as appropriate.

The Docker healthcheck verifies that the HTTP endpoint responds; it does
**not** prove articles have arrived or that the screen looks correct. Confirm
`/api/articles`, the actual kiosk display, and that article counts and local
branding match after an upgrade.

Default binding: `127.0.0.1:8085`. For a remote display, set `BIND_IP` to an interface reachable from that device, and restrict access using firewall rules or an HTTPS reverse proxy. Never expose the Basic Auth editor unprotected on the internet.
**Basic Auth over plain HTTP exposes credentials on the network**; use
HTTPS in front of the app if other devices access /admin. A host/LAN port
binding alone is not an authentication or TLS boundary. This change does
not add TLS, a reverse proxy, a firewall rule, or a non-root container user.

Check both `/healthz` and `/api/articles` and verify the actual kiosk screen. A healthy process does not mean your feed has valid articles.

For later upgrades see [Update safety](update-safety.md).
