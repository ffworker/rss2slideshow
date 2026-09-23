"""One RSS kiosk website. No slide files or external player required."""
import calendar
import hashlib
import html
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import feedparser
import requests
import yaml
from flask import Flask, jsonify, send_from_directory, request, abort
from zoneinfo import ZoneInfo

from app.branding import read_brand
from app.feeds import get_feeds, mix_feeds

ROOT = Path("/app") if Path("/app/config.yaml").is_file() else Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", os.environ.get("TZ", "Europe/Berlin"))
ZoneInfo(DISPLAY_TZ)  # fail early if there's a typo
BRAND = str(CFG.get("brand_name") or "rss2slideshow")[:60]
ACCENT = str(CFG.get("accent_color") or "#8b3932")
if not re.fullmatch(r"#[0-9a-fA-F]{6}", ACCENT):
    raise ValueError("accent_color needs to be a hex color, e.g. #8b3932")
REFRESH_SECONDS = max(60, int(CFG.get("refresh_minutes", 10)) * 60)
SLIDE_SECONDS = max(5, min(300, int(os.environ.get("SLIDE_SECONDS", "20"))))
FEED_FILE = ROOT / "content" / "feeds.txt"
USER_AGENT = "rss2slideshow/0.2"
MAX_PER_FEED = max(1, min(30, int(CFG.get("max_articles", 5))))
LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
if CFG.get("rss_url") or CFG.get("news_source_label"):
    LOG.warning("rss_url/news_source_label in config.yaml are old settings and are ignored; move that feed into content/feeds.txt")

app = Flask(__name__)
lock = threading.Lock()
snapshot = {"articles": [], "updated_at": None, "sources": []}
cached_sources = {}


def text_only(raw):
    # RSS summaries sometimes contain html, never pass that html to the browser.
    value = re.sub(r"<[^>]*>", " ", str(raw or ""))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def http_url(raw):
    value = str(raw or "").strip()
    parts = urlsplit(value)
    if parts.scheme in ("https", "http") and parts.hostname and not parts.username and not parts.password:
        return value
    return ""


def entry_image(entry):
    # hessenschau, for example, puts jpgs in an enclosure rather than media:thumbnail.
    for media in (
        entry.get("media_content", [])
        + entry.get("media_thumbnail", [])
        + entry.get("enclosures", [])
    ):
        url = http_url(media.get("url") or media.get("href"))
        if url.startswith("https://") and (
            str(media.get("type", "")).startswith("image/")
            or media.get("medium") == "image"
            or media in entry.get("media_thumbnail", [])
        ):
            return url
    # some feeds only have an image embedded in the summary.
    match = re.search(r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", entry.get("summary", ""), re.I)
    return http_url(html.unescape(match.group(1))) if match and match.group(1).startswith("https://") else ""


def parse_articles(feed, label, feed_url):
    source = (label or text_only(feed.feed.get("title", "")) or urlsplit(feed_url).hostname or "RSS")[:70]
    found = []
    for entry in feed.entries[:MAX_PER_FEED]:
        title = text_only(entry.get("title", ""))
        if not title:
            continue
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        stamp = None
        if published:
            try:
                stamp = datetime.fromtimestamp(calendar.timegm(published), timezone.utc).isoformat()
            except (OverflowError, ValueError, TypeError):
                pass
        article_url = http_url(entry.get("link"))
        uid = str(entry.get("id") or article_url or title)
        found.append({
            "id": hashlib.sha256((feed_url + "\0" + uid).encode()).hexdigest()[:20],
            "source": source,
            "title": title,
            "summary": text_only(entry.get("summary", "") or entry.get("description", ""))[:900],
            "image": entry_image(entry) if CFG.get("news_images", False) else "",
            "published": stamp,
            "url": article_url,
        })
    return source, found


def refresh():
    requested = get_feeds(FEED_FILE)
    if not requested:
        LOG.warning("no RSS feeds configured: add URLs to content/feeds.txt")
    groups = []
    updated_sources = {}
    for label, url in requested:
        try:
            response = requests.get(url, timeout=(5, 15), headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if not parsed.entries:
                raise ValueError("empty or unreadable feed")
            name, articles = parse_articles(parsed, label, url)
            updated_sources[url] = articles
            LOG.info("loaded %s: %d articles", name, len(articles))
        except Exception as exc:
            LOG.warning("could not update %s: %s", url, exc)
            # keep the last working stories if a feed temporarily fails.
            updated_sources[url] = cached_sources.get(url, [])
        groups.append(updated_sources[url])
    cached_sources.clear()
    cached_sources.update(updated_sources)
    queue = mix_feeds(groups)
    with lock:
        snapshot["articles"] = queue
        snapshot["sources"] = [label or urlsplit(url).hostname for label, url in requested]
        snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
    LOG.info("kiosk queue: %d articles from %d configured feeds", len(queue), len(requested))
    return requested


def worker():
    last_sources = None
    last_refresh = 0
    while True:
        try:
            sources = get_feeds(FEED_FILE)
            if sources != last_sources or time.monotonic() - last_refresh >= REFRESH_SECONDS:
                last_sources = refresh()
                last_refresh = time.monotonic()
        except Exception:
            LOG.exception("refresh failed")
        time.sleep(30)


@app.get("/")
@app.get("/kiosk")
def kiosk():
    return send_from_directory(Path(__file__).parent, "player.html", mimetype="text/html")


@app.get("/demo/<profile>")
def demo(profile):
    # only sample profiles committed in branding/examples, never private customer config
    if not re.fullmatch(r"[a-z0-9-]{1,40}", profile):
        abort(404)
    if not (ROOT / "branding" / "examples" / profile / "brand.yaml").is_file():
        abort(404)
    return send_from_directory(Path(__file__).parent, "player.html", mimetype="text/html")


@app.get("/branding/examples/<profile>/<filename>")
def demo_asset(profile, filename):
    if not re.fullmatch(r"[a-z0-9-]{1,40}", profile) or filename not in ("logo.png", "group-logo.png", "font.woff2"):
        abort(404)
    folder = ROOT / "branding" / "examples" / profile
    if not (folder / "brand.yaml").is_file() or not (folder / filename).is_file():
        abort(404)
    return send_from_directory(folder, filename, mimetype="image/png" if filename.endswith(".png") else "font/woff2", conditional=True)


@app.get("/branding/<filename>")
def brand_asset(filename):
    if filename not in ("logo.png", "font.woff2"):
        return "", 404
    folder = ROOT / "branding"
    if not (folder / filename).is_file():
        return "", 404
    media_type = "image/png" if filename == "logo.png" else "font/woff2"
    return send_from_directory(folder, filename, mimetype=media_type, conditional=True)


@app.get("/assets/logo.png")
def logo():
    path = ROOT / "assets" / "logo.png"
    if not path.is_file():
        return "", 404
    return send_from_directory(path.parent, path.name, mimetype="image/png")


@app.get("/api/articles")
def articles():
    demo_name = request.args.get("demo")
    if demo_name and (not re.fullmatch(r"[a-z0-9-]{1,40}", demo_name) or not (ROOT / "branding" / "examples" / demo_name / "brand.yaml").is_file()):
        abort(404)
    with lock:
        current = {
            "articles": list(snapshot["articles"]),
            "updated_at": snapshot["updated_at"],
            "sources": list(snapshot["sources"]),
        }
    current.update({
        "timezone": DISPLAY_TZ,
        "server_time_ms": int(time.time() * 1000),
        **read_brand(ROOT, CFG, profile=demo_name),
        "slide_seconds": SLIDE_SECONDS,
    })
    return jsonify(current)


@app.get("/healthz")
def health():
    with lock:
        return jsonify({"status": "ok", "articles": len(snapshot["articles"]),
                        "updated_at": snapshot["updated_at"]})


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, use_reloader=False)
