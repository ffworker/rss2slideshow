# RSS2Slideshow

Self-hosted RSS news display with a browser kiosk and compact web editor.

**Project status: Stable — maintenance only (November 2026).** The feature set is complete. Future changes are limited to confirmed defects, security fixes and compatibility maintenance; no further feature work is planned.

Project story: [Bytegeist Blog · RSS2Slideshow / 003](https://blog.bytegeist.dev/artikel/rss2slideshow/).

A personal project by **Bytegeist / ffworker**, created in my **own free time, outside working hours**. It is not an employer product or endorsement.

## Features

- Multiple RSS feeds, configurable article rotation and refresh intervals
- Browser-based 16:9 display with optional images, article QR codes and clock
- Admin editor for RSS feeds, typography, layout, colors and uploaded logos
- Optional JPEG output for older slideshow players
- Docker Compose deployment with persistent local settings
- Gunicorn HTTP runtime (one worker to preserve the in-memory RSS refresh cache)

## Quick start

Requires Docker Engine and the Compose plugin.

```sh
git clone https://github.com/ffworker/rss2slideshow.git
cd rss2slideshow
cp .env.example .env
cp config.example.yaml config.yaml
cp content/feeds.example.txt content/feeds.txt
# Set ADMIN_USER and ADMIN_PASSWORD in .env.
# Replace the example RSS URL in content/feeds.txt with a working feed.
docker compose up -d --build
```

By default the service binds to `127.0.0.1:8085`. Open `/` or `/kiosk` for the kiosk and `/admin` for the editor. The embedded preview uses `/kiosk` by default, including when upgrading from `ADMIN_KIOSK_PATH=/`. Set a custom `ADMIN_KIOSK_PATH` only when required by a reverse proxy. Basic Auth is for trusted environments; use HTTPS and proper access restrictions before exposing either UI over a network.

## Your configuration stays yours

Runtime settings are kept out of Git and the Docker image:

| Local file/path | Purpose |
|---|---|
| `branding/brand.yaml` and images | Optional custom theme and logo |
| `content/ui-settings.yaml` | Design editor changes |
| `content/admin-settings.yaml` | Display settings |
| `content/feeds.txt` | Your RSS feeds |
| `config.yaml`, `.env` | Deployment settings and secrets |

Use `python3 scripts/safe_update.py check` and `python3 scripts/safe_update.py update` for manual upgrades with a backup and configuration drift checks. There is no automatic deployment. The container uses a bounded in-container HTTP healthcheck; a healthy response is not proof that RSS content or browser rendering is correct.

See [Deployment](docs/deployment.md), [Branding](docs/branding.md), [Update safety](docs/update-safety.md).

## Tests

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q app addons
python3 scripts/export_public.py --check
```

MIT licensed. RSS content belongs to its publishers: check feed terms, attribution and image rights before displaying it. No customer logos or customer configuration files are included.
