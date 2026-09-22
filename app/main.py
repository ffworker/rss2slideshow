"""Generate image slides + URL inventory for existing Binary Emotions players."""
import hashlib
import io
import logging
import os
from pathlib import Path
from html import unescape
from ipaddress import ip_address
import socket
from urllib.parse import urlsplit
import re
import threading
import time
from zoneinfo import ZoneInfo

import feedparser
from flask import Flask, abort, send_from_directory, jsonify
from PIL import Image, ImageDraw, ImageFont
import requests
import yaml

from app.feeds import get_feeds, mix_feeds

ROOT = Path("/app") if Path("/app/config.yaml").exists() else Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
PUBLIC = CFG["public_url"].rstrip("/")
if not PUBLIC.startswith(("http://", "https://")) or "DISPLAY_HOST_IP" in PUBLIC:
    raise ValueError("Set public_url in config.yaml to the actual server address")
OUT = ROOT / "output"
SLIDES = OUT / "slides"
SLIDES.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", os.environ.get("TZ", "Europe/Berlin"))
TZ = ZoneInfo(DISPLAY_TZ)
BRAND = str(CFG.get("brand_name") or CFG.get("company_name") or "rss2slideshow")[:45]
ACCENT = str(CFG.get("accent_color", "#8b3932"))
if not re.fullmatch(r"#[0-9a-fA-F]{6}", ACCENT):
    raise ValueError("accent_color needs to be a hex color like #8b3932")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"


def font(size, bold=False):
    path = BOLD if bold else FONT
    return ImageFont.truetype(path, size) if Path(path).exists() else ImageFont.load_default()


def wrap(draw, value, fnt, width):
    lines, current = [], ""
    for word in re.sub(r"\s+", " ", value).split():
        candidate = (current + " " + word).strip()
        if current and draw.textbbox((0, 0), candidate, font=fnt)[2] > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + ([current] if current else [])


def fit_lines(draw, text, max_width, max_lines, starting_size, min_size=24, bold=False):
    for size in range(starting_size, min_size - 1, -2):
        chosen = font(size, bold)
        lines = wrap(draw, text, chosen, max_width)
        if len(lines) <= max_lines:
            return chosen, lines
    chosen = font(min_size, bold)
    lines = wrap(draw, text, chosen, max_width)[:max_lines]
    if lines and len(lines) == max_lines:
        last = lines[-1]
        while last and draw.textbbox((0, 0), last + "…", font=chosen)[2] > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return chosen, lines


# meant to feel like a simple news page, not a dashboard
PAPER = "#f8f7f3"
INK = "#252525"
MUTED = "#65635e"
RULE = "#c9c5be"


def headline_font(size):
    if Path(SERIF_BOLD).exists():
        return ImageFont.truetype(SERIF_BOLD, size)
    return font(size, True)


def fit_headline(draw, value, width, max_lines, starting_size, min_size):
    for size in range(starting_size, min_size - 1, -2):
        chosen = headline_font(size)
        lines = wrap(draw, value, chosen, width)
        if len(lines) <= max_lines:
            return chosen, lines
    chosen = headline_font(min_size)
    lines = wrap(draw, value, chosen, width)[:max_lines]
    if lines:
        last = lines[-1]
        while last and draw.textbbox((0, 0), last + "…", font=chosen)[2] > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return chosen, lines


def slide_header(canvas, category, source=""):
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    left = int(w * .045)
    top = int(h * .051)
    brand_x = left
    logo_path = ROOT / "assets" / "logo.png"
    if logo_path.is_file():
        try:
            with Image.open(logo_path) as source_image:
                mark = source_image.convert("RGBA")
                mark.thumbnail((int(w * .061), int(h * .065)), Image.Resampling.LANCZOS)
                canvas.paste(mark, (left, top), mark)
                brand_x += int(w * .074)
        except (OSError, ValueError):
            logging.warning("could not read the logo, using text instead")
    brand_font, brand_lines = fit_lines(
        draw, BRAND, max(80, int(w * .63) - brand_x), 1,
        max(18, int(h * .041)), max(14, int(h * .022)), True
    )
    if brand_lines:
        draw.text((brand_x, top), brand_lines[0], font=brand_font, fill=INK)
    draw.text((left, int(h * .153)), str(category).upper(), font=font(int(h * .026), True), fill=ACCENT)
    line_y = int(h * .206)
    draw.line((left, line_y, w - left, line_y), fill=RULE, width=max(1, int(h * .002)))
    draw.line((left, line_y, left + int(w * .065), line_y), fill=ACCENT, width=max(2, int(h * .004)))
    footer_y = int(h * .92)
    draw.line((left, footer_y, w - left, footer_y), fill=RULE, width=max(1, int(h * .002)))
    if source:
        draw.text((left, int(h * .939)), "Quelle: " + str(source)[:70],
                  font=font(int(h * .021)), fill=MUTED)


def render(title, subtitle="", kind="NEWS", source=""):
    w, h = int(CFG.get("slide_width", 1920)), int(CFG.get("slide_height", 1080))
    canvas = Image.new("RGB", (w, h), PAPER)
    slide_header(canvas, kind, source)
    draw = ImageDraw.Draw(canvas)
    pad = int(w * .052)
    title_font, lines = fit_headline(draw, title, w - 2 * pad, 5, int(h * .072), int(h * .036))
    y = int(h * .26)
    for line in lines:
        if y + title_font.size > int(h * .68):
            break
        draw.text((pad, y), line, font=title_font, fill=INK)
        y += int(title_font.size * 1.3)
    y = max(y + int(h * .04), int(h * .68))
    if subtitle and y < int(h * .87):
        summary_font, summary_lines = fit_lines(draw, subtitle, w - 2 * pad, 4, int(h * .034), int(h * .023))
        for line in summary_lines:
            if y + summary_font.size > int(h * .885):
                break
            draw.text((pad, y), line, font=summary_font, fill=MUTED)
            y += int(summary_font.size * 1.35)
    buffer = io.BytesIO()
    canvas.save(buffer, "JPEG", quality=89, optimize=True)
    return buffer.getvalue()


def publish(data, prefix):
    name = f"{prefix}-{hashlib.sha256(data).hexdigest()[:16]}.jpg"
    path = SLIDES / name
    if not path.exists():
        path.write_bytes(data)
    return name


def news():
    # rss_url is the old/default source. additional feeds live in content/feeds.txt
    # read that file every refresh, so adding/removing a URL doesn't need a restart
    sources = get_feeds(
        CFG.get("rss_url"), CFG.get("news_source_label", "RSS"),
        ROOT / "content" / "feeds.txt"
    )
    groups = []
    for given_label, url in sources:
        try:
            response = requests.get(
                url, timeout=20, headers={"User-Agent": "rss2slideshow/0.1"}
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if not feed.entries:
                raise ValueError("No RSS entries found")
            source_name = (
                given_label or str(feed.feed.get("title", "")).strip()
                or urlsplit(url).hostname or "RSS"
            )[:70]
            articles = []
            for entry in feed.entries[:max(1, int(CFG.get("max_articles", 5)))]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                picture = None
                # feeds disagree about where their image is (hessenschau uses enclosures).
                for media in (
                    entry.get("media_content", [])
                    + entry.get("media_thumbnail", [])
                    + entry.get("enclosures", [])
                ):
                    image_url = media.get("url") or media.get("href") or ""
                    if image_url.startswith("https://") and (
                        media.get("type", "").startswith("image/")
                        or media.get("medium") == "image"
                        or media in entry.get("media_thumbnail", [])
                    ):
                        picture = image_url
                        break
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))
                summary = re.sub(r"\s+", " ", unescape(summary)).strip()
                if picture and CFG.get("news_images", False):
                    try:
                        host = urlsplit(picture).hostname
                        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                        if not addresses or any(
                            not ip_address(address[4][0]).is_global
                            for address in addresses
                        ):
                            raise ValueError("non-public image host")
                        image_response = requests.get(picture, timeout=10, stream=True)
                        image_response.raise_for_status()
                        if not image_response.headers.get("Content-Type", "").lower().startswith("image/"):
                            raise ValueError("not an image")
                        data = b""
                        for chunk in image_response.iter_content(65536):
                            data += chunk
                            if len(data) > 5_000_000:
                                raise ValueError("image too large")
                        with Image.open(io.BytesIO(data)) as image:
                            image.verify()
                        articles.append(publish(render_news(title, summary, data, source_name), "news"))
                        continue
                    except Exception:
                        logging.exception("could not load image for %s", title)
                articles.append(
                    publish(render(title, summary[:300], "NACHRICHTEN", source_name), "news")
                )
            groups.append(articles)
        except Exception:
            logging.exception("could not update RSS feed: %s", url)
    return mix_feeds(groups)


def render_news(title, summary, image_bytes, source_name="RSS"):
    w, h = int(CFG.get("slide_width", 1920)), int(CFG.get("slide_height", 1080))
    canvas = Image.new("RGB", (w, h), PAPER)
    slide_header(canvas, "NACHRICHTEN", source_name)
    draw = ImageDraw.Draw(canvas)
    margin = int(w * .045)
    gap = int(w * .035)
    image_w = int(w * .425)
    top = int(h * .25)
    image_h = int(h * .59)
    bottom = int(h * .86)
    text_x = margin + image_w + gap
    text_width = w - margin - text_x
    # keep the image proportions, no giant cards or gradients
    draw.rectangle((margin, top, margin + image_w, top + image_h), fill="#ebe9e3", outline=RULE, width=max(1, int(h * .002)))
    with Image.open(io.BytesIO(image_bytes)) as source:
        picture = source.convert("RGB")
        picture.thumbnail((image_w - 12, image_h - 12), Image.Resampling.LANCZOS)
        canvas.paste(picture, (margin + (image_w - picture.width) // 2,
                               top + (image_h - picture.height) // 2))

    title_font, title_lines = fit_headline(draw, title, text_width, 6, int(h * .053), int(h * .03))
    y = top
    for line in title_lines:
        if y + title_font.size > int(h * .76):
            break
        draw.text((text_x, y), line, font=title_font, fill=INK)
        y += int(title_font.size * 1.28)
    y += int(h * .035)
    if summary and y < bottom:
        summary_font, summary_lines = fit_lines(
            draw, summary, text_width, max(1, (bottom - y) // int(h * .039)),
            int(h * .028), int(h * .021)
        )
        for line in summary_lines:
            if y + summary_font.size > bottom:
                break
            draw.text((text_x, y), line, font=summary_font, fill=MUTED)
            y += int(summary_font.size * 1.33)
    buffer = io.BytesIO()
    canvas.save(buffer, "JPEG", quality=88, optimize=True)
    return buffer.getvalue()


def weather():
    config = CFG.get("weather", {})
    if not config.get("enabled"):
        return []
    response = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": config["latitude"], "longitude": config["longitude"],
        "current": "temperature_2m,weather_code", "timezone": DISPLAY_TZ
    }, timeout=20)
    response.raise_for_status()
    current = response.json()["current"]
    description = f"{config.get('label', 'Wetter')} · Wettercode {current['weather_code']} · Quelle: Open-Meteo"
    return [publish(render(f"{current['temperature_2m']} °C", description, "WETTER", "Open-Meteo"), "weather")]


def local_images():
    output = []
    w, h = int(CFG.get("slide_width", 1920)), int(CFG.get("slide_height", 1080))
    folders = [ROOT / "content" / "company", ROOT / "content" / "photos"]
    folders += [Path("/app/mounts") / name for name in CFG.get("media_mounts", []) if re.fullmatch(r"[a-zA-Z0-9_-]+", str(name))]
    for directory in folders:
        if not directory.is_dir():
            continue
        folder = directory.name
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                continue
            try:
                with Image.open(path) as source:
                    image = source.convert("RGB")
                    image.thumbnail((w, h))
                    canvas = Image.new("RGB", (w, h), "#122036")
                    canvas.paste(image, ((w - image.width) // 2, (h - image.height) // 2))
                    buffer = io.BytesIO()
                    canvas.save(buffer, "JPEG", quality=88)
                    output.append(publish(buffer.getvalue(), folder))
            except Exception:
                logging.exception("Cannot load image %s", path.name)
    return output


def refresh():
    names = []
    for generator in (news, weather, local_images):
        try:
            names.extend(generator())
        except Exception:
            logging.exception("Slide generator failed: %s", generator.__name__)
    if not names:
        return
    tmp = OUT / "inventory.txt.tmp"
    tmp.write_text("".join(f"{PUBLIC}/slides/{name}\n" for name in names), encoding="utf-8")
    os.replace(tmp, OUT / "inventory.txt")
    active = set(names)
    for old in SLIDES.glob("*.jpg"):
        if old.name not in active and time.time() - old.stat().st_mtime > 86400:
            old.unlink()


def worker():
    while True:
        try:
            refresh()
        except Exception:
            logging.exception("Refresh failed")
        time.sleep(max(5, int(CFG.get("refresh_minutes", 10))) * 60)


@app.get("/inventory.txt")
def inventory():
    if not (OUT / "inventory.txt").exists():
        abort(503)
    return send_from_directory(OUT, "inventory.txt", mimetype="text/plain")


@app.get("/slides/<path:name>")
def image(name):
    if not name.endswith(".jpg"):
        abort(404)
    return send_from_directory(SLIDES, name, mimetype="image/jpeg")


@app.get("/")
@app.get("/player")
def player():
    return send_from_directory(Path(__file__).parent, "player.html", mimetype="text/html")


@app.get("/api/playlist")
def playlist():
    path = OUT / "inventory.txt"
    if not path.exists():
        return jsonify({"items": []})
    return jsonify({"items": ["/slides/" + line.strip().rsplit("/", 1)[-1] for line in path.read_text().splitlines() if line.strip()]})


@app.get("/api/display-config")
def display_config():
    # browser clock uses this time, the selected timezone and a ticking client timer
    return jsonify({
        "timezone": DISPLAY_TZ,
        "brand_name": BRAND,
        "accent_color": ACCENT,
        "server_time_ms": int(time.time() * 1000),
        "slide_seconds": max(3, min(300, int(os.environ.get("SLIDE_SECONDS", "15"))))
    })


@app.get("/healthz")
def health():
    return {"status": "ok", "inventory_ready": (OUT / "inventory.txt").exists()}


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, use_reloader=False)
