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

Default binding: `127.0.0.1:8085`. For a remote display, set `BIND_IP` to an interface reachable from that device, and restrict access using firewall rules or an HTTPS reverse proxy. Never expose the Basic Auth editor unprotected on the internet.

Check both `/healthz` and `/api/articles` and verify the actual kiosk screen. A healthy process does not mean your feed has valid articles.

For later upgrades see [Update safety](update-safety.md).
