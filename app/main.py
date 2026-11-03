"""One RSS kiosk website. No slide files or external player required."""
import calendar
import hashlib
import hmac
import html
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import feedparser
import yaml
from flask import Flask, jsonify, send_from_directory, request, abort, render_template, make_response
from io import BytesIO
import qrcode
from zoneinfo import ZoneInfo

from app.branding import read_brand
from app.feeds import get_feeds, mix_feeds
from app.secure_feed import fetch_feed_bytes
from addons.binary_emotions import inventory_text as binary_emotions_inventory_text, render_slide_jpeg

ROOT = Path("/app") if Path("/app/config.yaml").is_file() else Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", os.environ.get("TZ", "Europe/Berlin"))
ZoneInfo(DISPLAY_TZ)  # fail early if there's a typo
BRAND = str(CFG.get("brand_name") or "RSS2Slideshow")[:60]
ACCENT = str(CFG.get("accent_color") or "#2563eb")
if not re.fullmatch(r"#[0-9a-fA-F]{6}", ACCENT):
    raise ValueError("accent_color needs to be a hex color, e.g. #2563eb")
REFRESH_SECONDS = max(60, int(CFG.get("refresh_minutes", 10)) * 60)
SLIDE_SECONDS = max(5, min(300, int(os.environ.get("SLIDE_SECONDS", "20"))))
FEED_FILE = ROOT / "content" / "feeds.txt"
ADMIN_SETTINGS_FILE = ROOT / "content" / "admin-settings.yaml"
DESIGN_SETTINGS_FILE = ROOT / "content" / "ui-settings.yaml"
DESIGN_LOGO_NAMES = ("design-logo.png", "design-logo.jpg", "design-logo.webp")
DESIGN_FONT_PRESETS = ("news", "sans", "serif", "mono", "Calibri", "Arial", "Verdana")
BINARY_EMOTIONS_ADDON = os.environ.get("BINARY_EMOTIONS_ADDON", "").strip().lower() in ("1", "true", "yes", "on")
try:
    BINARY_EMOTIONS_LIMIT = max(1, min(30, int(os.environ.get("BINARY_EMOTIONS_LIMIT", "10"))))
except ValueError:
    BINARY_EMOTIONS_LIMIT = 10
USER_AGENT = "rss2slideshow/0.2"
MAX_PER_FEED = max(1, min(30, int(CFG.get("max_articles", 5))))
LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
if CFG.get("rss_url") or CFG.get("news_source_label"):
    LOG.warning("rss_url/news_source_label in config.yaml are old settings and are ignored; move that feed into content/feeds.txt")

app = Flask(__name__)
lock = threading.Lock()
refresh_lock = threading.Lock()
snapshot = {"articles": [], "updated_at": None, "sources": [],
            "last_success_at": None, "failed_sources": []}
cached_sources = {}


def _bounded_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def runtime_settings():
    """Kiosk settings, with small writable overrides managed by /admin."""
    settings = {
        "max_articles": _bounded_int(CFG.get("max_articles"), MAX_PER_FEED, 1, 30),
        "refresh_minutes": _bounded_int(CFG.get("refresh_minutes"), max(1, REFRESH_SECONDS // 60), 1, 1440),
        "news_images": bool(CFG.get("news_images", False)),
        "slide_seconds": SLIDE_SECONDS,
    }
    if ADMIN_SETTINGS_FILE.is_file():
        try:
            overrides = yaml.safe_load(ADMIN_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
            if isinstance(overrides, dict):
                settings["max_articles"] = _bounded_int(overrides.get("max_articles"), settings["max_articles"], 1, 30)
                settings["refresh_minutes"] = _bounded_int(overrides.get("refresh_minutes"), settings["refresh_minutes"], 1, 1440)
                settings["slide_seconds"] = _bounded_int(overrides.get("slide_seconds"), settings["slide_seconds"], 5, 300)
                if isinstance(overrides.get("news_images"), bool):
                    settings["news_images"] = overrides["news_images"]
        except (OSError, yaml.YAMLError):
            LOG.exception("could not read admin-settings.yaml")
    return settings


def atomic_text_write(path, text, make_backup=True):
    """Write customer-editable files safely inside the writable content mount."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if make_backup and path.is_file():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def admin_credentials():
    return os.environ.get("ADMIN_USER", "").strip(), os.environ.get("ADMIN_PASSWORD", "")


def admin_form_token():
    _, password = admin_credentials()
    return hashlib.sha256(("rss2slideshow-admin-form\0" + password).encode()).hexdigest()


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        username, password = admin_credentials()
        if not username or not password:
            response = make_response("Admin UI is disabled. Set ADMIN_USER and ADMIN_PASSWORD in .env.", 503)
            response.headers["Cache-Control"] = "no-store"
            return response
        auth = request.authorization
        valid = bool(
            auth
            and hmac.compare_digest(auth.username or "", username)
            and hmac.compare_digest(auth.password or "", password)
        )
        if not valid:
            response = make_response("Login required", 401)
            response.headers["WWW-Authenticate"] = 'Basic realm="rss2slideshow admin", charset="UTF-8"'
            response.headers["Cache-Control"] = "no-store"
            return response
        return function(*args, **kwargs)
    return wrapped


def validate_admin_feeds(labels, urls):
    rows, seen = [], set()
    if len(urls) > 30:
        raise ValueError("Maximal 30 Feeds sind erlaubt.")
    for label, raw_url in zip(labels, urls):
        label, raw_url = str(label or "").strip(), str(raw_url or "").strip()
        if not label and not raw_url:
            continue
        if not raw_url:
            raise ValueError("Zu jedem Namen gehört eine Feed-URL.")
        if len(label) > 70 or "|" in label or "\n" in label or "\r" in label:
            raise ValueError("Feed-Namen dürfen maximal 70 Zeichen lang sein und kein | enthalten.")
        if len(raw_url) > 2048 or http_url(raw_url) != raw_url:
            raise ValueError("Feed-URLs müssen vollständige http:// oder https:// URLs ohne Zugangsdaten sein.")
        if raw_url in seen:
            raise ValueError("Doppelte Feed-URL: " + raw_url)
        seen.add(raw_url)
        rows.append((label, raw_url))
    return rows


def write_admin_feeds(rows):
    lines = [(label + " | " + url) if label else url for label, url in rows]
    atomic_text_write(FEED_FILE, "\n".join(lines) + ("\n" if lines else ""), make_backup=True)


def write_admin_settings(values):
    text = (
        "# Managed by /admin. These values override config.yaml for the running kiosk.\n"
        f"slide_seconds: {values['slide_seconds']}\n"
        f"max_articles: {values['max_articles']}\n"
        f"refresh_minutes: {values['refresh_minutes']}\n"
        f"news_images: {'true' if values['news_images'] else 'false'}\n"
    )
    atomic_text_write(ADMIN_SETTINGS_FILE, text, make_backup=True)


def current_base_brand():
    """Branding shipped/configured for this installation, before admin UI overrides."""
    return read_brand(ROOT, CFG)


def _design_color(value, fallback):
    value = str(value or "").strip().lower()
    return value if re.fullmatch(r"#[0-9a-f]{6}", value) else fallback


def _design_bool(value, fallback):
    return value if isinstance(value, bool) else fallback


def design_logo_url():
    for filename in DESIGN_LOGO_NAMES:
        path = ROOT / "content" / filename
        if path.is_file():
            return "/design-logo?v=" + str(path.stat().st_mtime_ns)
    return ""


def read_design_settings(base_brand=None):
    """Small, validated design layer stored in content/ui-settings.yaml."""
    base = base_brand or current_base_brand()
    settings = {
        "design_enabled": False,
        "brand_name": str(base.get("brand_name") or "RSS2Slideshow")[:60],
        "accent_color": _design_color(base.get("accent_color"), "#2563eb"),
        "background_color": _design_color(base.get("background_color"), "#f8fafc"),
        "text_color": _design_color(base.get("text_color"), "#1f2937"),
        "header_color": _design_color(base.get("header_color"), "#ffffff"),
        "footer_color": _design_color(base.get("footer_color"), "#ffffff"),
        "font_family": str(base.get("font_family") or "news"),
        "headline_color": _design_color(base.get("accent_color"), "#2563eb"),
        "summary_color": _design_color(base.get("text_color"), "#1f2937"),
        "overlay_headline_color": _design_color(base.get("accent_color"), "#2563eb"),
        "overlay_summary_color": "#ffffff",
        "header_height": 150,
        "footer_height": 82,
        "logo_size": 110,
        "image_width": 56,
        "headline_size": 52,
        "summary_size": 28,
        "image_fit": "contain",
        "story_layout": "split",
        "show_clock": True,
        "show_source": True,
        "show_footer_names": True,
        "footer_names": list(base.get("footer_names") or [])[:6],
    }
    if DESIGN_SETTINGS_FILE.is_file():
        try:
            custom = yaml.safe_load(DESIGN_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
            if not isinstance(custom, dict):
                raise ValueError("ui-settings.yaml needs key: value pairs")
            settings["design_enabled"] = True
            if str(custom.get("brand_name") or "").strip():
                settings["brand_name"] = str(custom["brand_name"]).strip()[:60]
            for key in ("accent_color", "background_color", "text_color", "header_color", "footer_color",
                        "headline_color", "summary_color", "overlay_headline_color", "overlay_summary_color"):
                if key in custom:
                    settings[key] = _design_color(custom[key], settings[key])
            if custom.get("font_family") in DESIGN_FONT_PRESETS:
                settings["font_family"] = custom["font_family"]
            for key, low, high in (
                ("header_height", 80, 220),
                ("footer_height", 45, 130),
                ("logo_size", 50, 170),
                ("image_width", 30, 70),
                ("headline_size", 20, 110),
                ("summary_size", 12, 60),
            ):
                settings[key] = _bounded_int(custom.get(key), settings[key], low, high)
            settings["image_fit"] = "cover" if custom.get("image_fit") == "cover" else "contain"
            settings["story_layout"] = "overlay" if custom.get("story_layout") == "overlay" else "split"
            for key in ("show_clock", "show_source", "show_footer_names"):
                settings[key] = _design_bool(custom.get(key), settings[key])
            names = custom.get("footer_names")
            if isinstance(names, list):
                settings["footer_names"] = [
                    str(name).strip()[:48] for name in names[:6]
                    if isinstance(name, str) and name.strip()
                ]
        except (OSError, ValueError, yaml.YAMLError):
            LOG.exception("could not read ui-settings.yaml; using the profile defaults")
    logo = design_logo_url()
    if logo:
        settings["logo_url"] = logo
    return settings


def validate_design_form(form):
    base = read_design_settings(current_base_brand())
    name = str(form.get("design_brand_name") or "").strip()
    if not name or len(name) > 60:
        raise ValueError("Der Anzeigename muss zwischen 1 und 60 Zeichen lang sein.")
    font_family = str(form.get("design_font_family") or base["font_family"]).strip()
    if font_family not in DESIGN_FONT_PRESETS:
        raise ValueError("Bitte eine Schriftart aus der Liste auswählen.")
    values = {
        "brand_name": name,
        "accent_color": _design_color(form.get("design_accent_color"), ""),
        "background_color": _design_color(form.get("design_background_color"), ""),
        "text_color": _design_color(form.get("design_text_color"), ""),
        "header_color": _design_color(form.get("design_header_color"), ""),
        "footer_color": _design_color(form.get("design_footer_color"), ""),
        "font_family": font_family,
        "headline_color": _design_color(form.get("design_headline_color"), base["headline_color"]),
        "summary_color": _design_color(form.get("design_summary_color"), base["summary_color"]),
        "overlay_headline_color": _design_color(form.get("design_overlay_headline_color"), base["overlay_headline_color"]),
        "overlay_summary_color": _design_color(form.get("design_overlay_summary_color"), base["overlay_summary_color"]),
        "header_height": _bounded_int(form.get("design_header_height"), base["header_height"], 80, 220),
        "footer_height": _bounded_int(form.get("design_footer_height"), base["footer_height"], 45, 130),
        "logo_size": _bounded_int(form.get("design_logo_size"), base["logo_size"], 50, 170),
        "image_width": _bounded_int(form.get("design_image_width"), base["image_width"], 30, 70),
        "headline_size": _bounded_int(form.get("design_headline_size"), base["headline_size"], 20, 110),
        "summary_size": _bounded_int(form.get("design_summary_size"), base["summary_size"], 12, 60),
        "image_fit": "cover" if form.get("design_image_fit") == "cover" else "contain",
        "story_layout": "overlay" if form.get("design_story_layout") == "overlay" else "split",
        "show_clock": form.get("design_show_clock") == "on",
        "show_source": form.get("design_show_source") == "on",
        "show_footer_names": form.get("design_show_footer_names") == "on",
    }
    for key in ("design_headline_color", "design_summary_color", "design_overlay_headline_color", "design_overlay_summary_color"):
        if key in form and not _design_color(form.get(key), ""):
            raise ValueError("Farben müssen als vollständige Hex-Werte wie #2563eb angegeben werden.")
    if not all(values[key] for key in ("accent_color", "background_color", "text_color", "header_color", "footer_color")):
        raise ValueError("Farben müssen als vollständige Hex-Werte wie #2563eb angegeben werden.")
    raw_names = str(form.get("design_footer_names") or "")
    values["footer_names"] = [
        line.strip()[:48] for line in raw_names.splitlines()
        if line.strip()
    ][:6]
    return values


def write_design_settings(values):
    text = "# Managed by /admin design editor. Safe values only; no raw CSS.\n" + yaml.safe_dump(
        values, allow_unicode=True, sort_keys=False
    )
    atomic_text_write(DESIGN_SETTINGS_FILE, text, make_backup=True)


def save_design_logo(upload):
    if not upload or not upload.filename:
        return
    data = upload.stream.read(3 * 1024 * 1024 + 1)
    if len(data) > 3 * 1024 * 1024:
        raise ValueError("Das Logo darf maximal 3 MB groß sein.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        filename = "design-logo.png"
    elif data.startswith(b"\xff\xd8\xff"):
        filename = "design-logo.jpg"
    elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        filename = "design-logo.webp"
    else:
        raise ValueError("Logo bitte als PNG, JPG oder WebP hochladen.")
    folder = ROOT / "content"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    temporary = folder / ("." + filename + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    for other in DESIGN_LOGO_NAMES:
        if other != filename:
            try:
                (folder / other).unlink()
            except FileNotFoundError:
                pass


def reset_design_settings():
    for path in (DESIGN_SETTINGS_FILE, DESIGN_SETTINGS_FILE.with_name(DESIGN_SETTINGS_FILE.name + ".bak")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for filename in DESIGN_LOGO_NAMES:
        try:
            (ROOT / "content" / filename).unlink()
        except FileNotFoundError:
            pass


def binary_emotions_brand_settings():
    base = current_base_brand()
    return {**base, **read_design_settings(base)}


def binary_emotions_logo_path():
    for filename in DESIGN_LOGO_NAMES:
        path = ROOT / "content" / filename
        if path.is_file():
            return path
    folder = ROOT / "branding"
    fallback = folder / "logo.png"
    return fallback if fallback.is_file() else None


def test_admin_feeds(rows):
    results = []
    for label, url in rows:
        result = {"label": label or urlsplit(url).hostname or "Feed", "url": url, "ok": False, "detail": ""}
        try:
            parsed = feedparser.parse(fetch_feed_bytes(url, USER_AGENT))
            if not parsed.entries:
                raise ValueError("keine lesbaren Artikel gefunden")
            result["ok"] = True
            result["detail"] = f"{len(parsed.entries)} Artikel gefunden"
        except Exception as exc:
            result["detail"] = str(exc)[:160]
        results.append(result)
    return results


def render_admin_page(message="", error="", feed_rows=None, feed_tests=None):
    settings = runtime_settings()
    design = read_design_settings(current_base_brand())
    feeds = feed_rows if feed_rows is not None else get_feeds(FEED_FILE)
    with lock:
        status = {
            "articles": len(snapshot["articles"]),
            "updated_at": snapshot["updated_at"],
            "sources": len(snapshot["sources"]),
            "failed_feeds": len(snapshot["failed_sources"]),
            "last_success_at": snapshot["last_success_at"],
        }
    response = make_response(render_template(
        "admin.html",
        csrf=admin_form_token(),
        feeds=feeds,
        settings=settings,
        design=design,
        status=status,
        message=message,
        error=error,
        feed_tests=feed_tests or [],
        kiosk_path=os.environ.get("ADMIN_KIOSK_PATH", "/") or "/",
    ))
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-src 'self'; form-action 'self'; frame-ancestors 'none'"
    return response


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
    # Some RSS feeds provide images in enclosures rather than media:thumbnail.
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


def parse_articles(feed, label, feed_url, settings=None):
    active = settings or {"max_articles": MAX_PER_FEED, "news_images": bool(CFG.get("news_images", False))}
    source = (label or text_only(feed.feed.get("title", "")) or urlsplit(feed_url).hostname or "RSS")[:70]
    found = []
    for entry in feed.entries[:active["max_articles"]]:
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
            "image": entry_image(entry) if active["news_images"] else "",
            "published": stamp,
            "url": article_url,
        })
    return source, found


def refresh():
    """Prevent overlapping manual/background refreshes of the shared cache."""
    with refresh_lock:
        return _refresh_locked()


def _refresh_locked():
    active = runtime_settings()
    requested = get_feeds(FEED_FILE)
    if not requested:
        LOG.warning("no RSS feeds configured: add URLs to content/feeds.txt")
    groups = []
    updated_sources = {}
    failed_sources = []
    successful_feeds = 0
    for label, url in requested:
        try:
            parsed = feedparser.parse(fetch_feed_bytes(url, USER_AGENT))
            if not parsed.entries:
                raise ValueError("empty or unreadable feed")
            name, articles = parse_articles(parsed, label, url, active)
            if not articles:
                raise ValueError("feed has no usable titled articles")
            successful_feeds += 1
            updated_sources[url] = articles
            LOG.info("loaded %s: %d articles", name, len(articles))
        except Exception as exc:
            LOG.warning("could not update %s: %s", url, exc)
            failed_sources.append(label or urlsplit(url).hostname or "Feed")
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
        snapshot["failed_sources"] = failed_sources
        if successful_feeds:
            snapshot["last_success_at"] = snapshot["updated_at"]
    LOG.info("kiosk queue: %d articles from %d configured feeds", len(queue), len(requested))
    return requested


def worker():
    last_sources = None
    last_refresh = 0
    while True:
        try:
            sources = get_feeds(FEED_FILE)
            refresh_seconds = runtime_settings()["refresh_minutes"] * 60
            if sources != last_sources or time.monotonic() - last_refresh >= refresh_seconds:
                last_sources = refresh()
                last_refresh = time.monotonic()
        except Exception:
            LOG.exception("refresh failed")
        time.sleep(30)


@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    message, error, tests = "", "", []
    rows = None
    if request.method == "POST":
        if not hmac.compare_digest(request.form.get("csrf", ""), admin_form_token()):
            abort(400)
        action = request.form.get("action", "")
        try:
            if action in ("save_feeds", "test_feeds"):
                rows = validate_admin_feeds(
                    request.form.getlist("feed_label"),
                    request.form.getlist("feed_url"),
                )
            if action == "save_feeds":
                write_admin_feeds(rows)
                message = "Feeds gespeichert. Eine Sicherung liegt als feeds.txt.bak bereit."
            elif action == "test_feeds":
                tests = test_admin_feeds(rows)
                message = "Feed-Test abgeschlossen."
            elif action == "save_settings":
                values = {
                    "slide_seconds": _bounded_int(request.form.get("slide_seconds"), 20, 5, 300),
                    "max_articles": _bounded_int(request.form.get("max_articles"), 5, 1, 30),
                    "refresh_minutes": _bounded_int(request.form.get("refresh_minutes"), 10, 1, 1440),
                    "news_images": request.form.get("news_images") == "on",
                }
                write_admin_settings(values)
                message = "Anzeige-Einstellungen gespeichert."
            elif action == "save_design":
                values = validate_design_form(request.form)
                save_design_logo(request.files.get("design_logo"))
                write_design_settings(values)
                message = "Design gespeichert. Der Kiosk übernimmt es beim nächsten Abruf."
            elif action == "reset_design":
                reset_design_settings()
                message = "Design auf den hinterlegten Kundenstandard zurückgesetzt."
            elif action == "refresh":
                refresh()
                message = "Feeds wurden jetzt neu geladen."
            else:
                raise ValueError("Unbekannte Aktion.")
        except (OSError, ValueError) as exc:
            error = str(exc)
    return render_admin_page(message=message, error=error, feed_rows=rows, feed_tests=tests)


@app.get("/")
@app.get("/kiosk")
def kiosk():
    return send_from_directory(Path(__file__).parent, "player.html", mimetype="text/html")


def serve_brand_file(folder, filename):
    # Browsers decompress logo.svgz as HTTP gzip, then render its vector paths.
    media_type = ("image/svg+xml" if filename in ("logo.svg", "logo.svgz") else
                  "image/png" if filename.endswith(".png") else "font/woff2")
    response = send_from_directory(folder, filename, mimetype=media_type, conditional=True)
    if filename == "logo.svgz":
        response.headers["Content-Encoding"] = "gzip"
    if filename in ("logo.svg", "logo.svgz"):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return response


@app.get("/design-logo")
def design_logo():
    for filename in DESIGN_LOGO_NAMES:
        path = ROOT / "content" / filename
        if path.is_file():
            media_type = (
                "image/png" if filename.endswith(".png")
                else "image/jpeg" if filename.endswith(".jpg")
                else "image/webp"
            )
            response = send_from_directory(path.parent, path.name, mimetype=media_type, conditional=True)
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
    abort(404)


@app.get("/branding/<filename>")
def brand_asset(filename):
    allowed = ("logo.png", "logo.svg", "logo.svgz", "group-logo.png",
               "claim-logo.png", "footer-banner.png", "font.woff2")
    if filename not in allowed:
        abort(404)
    folder = ROOT / "branding"
    if not (folder / filename).is_file():
        abort(404)
    return serve_brand_file(folder, filename)


@app.get("/assets/logo.png")
def logo():
    path = ROOT / "assets" / "logo.png"
    if not path.is_file():
        return "", 404
    return send_from_directory(path.parent, path.name, mimetype="image/png")


@app.get("/addons/binary-emotions/inventory.txt")
def binary_emotions_inventory():
    if not BINARY_EMOTIONS_ADDON:
        abort(404)
    with lock:
        current_articles = list(snapshot["articles"])
    response = make_response(
        binary_emotions_inventory_text(current_articles, request.url_root.rstrip("/"), BINARY_EMOTIONS_LIMIT)
    )
    response.mimetype = "text/plain"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/addons/binary-emotions/slides/<article_id>.jpg")
def binary_emotions_slide(article_id):
    if not BINARY_EMOTIONS_ADDON or not re.fullmatch(r"[0-9a-f]{20}", article_id):
        abort(404)
    with lock:
        article = next((dict(item) for item in snapshot["articles"] if item.get("id") == article_id), None)
    if article is None:
        abort(404)
    jpeg = render_slide_jpeg(article, binary_emotions_brand_settings(), binary_emotions_logo_path())
    response = make_response(jpeg)
    response.mimetype = "image/jpeg"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/articles")
def articles():
    if "demo" in request.args:
        abort(404)
    with lock:
        current = {
            "articles": [
                {**item, "qr_url": article_qr_url(item)}
                for item in snapshot["articles"]
            ],
            "updated_at": snapshot["updated_at"],
            "sources": list(snapshot["sources"]),
        }
    brand_settings = read_brand(ROOT, CFG)
    design_settings = read_design_settings(brand_settings)
    current.update({
        "timezone": DISPLAY_TZ,
        "server_time_ms": int(time.time() * 1000),
        **brand_settings,
        **design_settings,
        "slide_seconds": runtime_settings()["slide_seconds"],
    })
    return jsonify(current)

def article_qr_url(item):
    url = http_url(item.get("url"))
    if not url or len(url.encode("utf-8")) > 512:
        return ""
    fingerprint = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f'/qr/{item["id"]}/{fingerprint}.png'

def make_qr_png(url):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                         box_size=8, border=4)
    code.add_data(url)
    code.make(fit=True)
    output = BytesIO()
    code.make_image(fill_color="black", back_color="white").save(output, format="PNG")
    return output.getvalue()

@app.get("/qr/<article_id>/<fingerprint>.png")
def article_qr(article_id, fingerprint):
    with lock:
        article = next((item for item in snapshot["articles"] if item.get("id") == article_id), None)
    url = http_url(article.get("url")) if article else ""
    if not url or article_qr_url(article) != f'/qr/{article_id}/{fingerprint}.png':
        abort(404)
    response = make_response(make_qr_png(url))
    response.mimetype = "image/png"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/healthz")
def health():
    with lock:
        return jsonify({"status": "ok", "articles": len(snapshot["articles"]),
                        "updated_at": snapshot["updated_at"],
                        "last_success_at": snapshot["last_success_at"],
                        "failed_feeds": len(snapshot["failed_sources"])})


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, use_reloader=False)
