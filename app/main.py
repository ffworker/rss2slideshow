"""Generate image slides + URL inventory for existing Binary Emotions players."""
import hashlib
import io
import logging
import os
from pathlib import Path
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
from flask import Flask, abort, send_from_directory, jsonify
from PIL import Image, ImageDraw, ImageFont
import requests
import yaml

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
TZ = ZoneInfo("Europe/Berlin")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


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


def render(title, subtitle="", kind="NEWS"):
    w, h = int(CFG.get("slide_width", 1920)), int(CFG.get("slide_height", 1080))
    image = Image.new("RGB", (w, h), "#f5f5f2")
    draw = ImageDraw.Draw(image)
    pad = int(w * .05)
    draw.text((pad, int(h * .07)), kind, font=font(int(h * .035), True), fill="#555555")
    draw.line((pad, int(h * .14), w - pad, int(h * .14)), fill="#bbbbbb", width=2)
    title_font, lines = fit_lines(draw, title, w - 2 * pad, 5, int(h * .074), int(h * .036), True)
    y = int(h * .23)
    step = int(title_font.size * 1.32)
    for line in lines:
        draw.text((pad, y), line, font=title_font, fill="#181818")
        y += step
    summary_font, summary_lines = fit_lines(draw, subtitle, w - 2 * pad, 4, int(h * .039), int(h * .025))
    y = max(y + int(h * .045), int(h * .7))
    for line in summary_lines:
        if y + summary_font.size > int(h * .9):
            break
        draw.text((pad, y), line, font=summary_font, fill="#454545")
        y += int(summary_font.size * 1.4)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=89, optimize=True)
    return buffer.getvalue()


def publish(data, prefix):
    name = f"{prefix}-{hashlib.sha256(data).hexdigest()[:16]}.jpg"
    path = SLIDES / name
    if not path.exists():
        path.write_bytes(data)
    return name


def news():
    response = requests.get(CFG["rss_url"], timeout=20, headers={"User-Agent": "rss2slideshow/0.1"})
    response.raise_for_status()
    entries = feedparser.parse(response.content).entries
    if not entries:
        raise ValueError("No RSS entries found")
    results = []
    for entry in entries[:int(CFG.get("max_articles", 5))]:
        title = entry.get("title", "").strip()
        if not title:
            continue
        # many rss feeds contain thumbnails in media_content or media_thumbnail.
        # only retrieve images from the feed, never scrape article pages.
        picture = None
        # some feeds (including hessenschau) put article jpgs in enclosures.
        for media in (
            entry.get("media_content", [])
            + entry.get("media_thumbnail", [])
            + entry.get("enclosures", [])
        ):
            url = media.get("url") or media.get("href") or ""
            if url.startswith("https://") and (
                media.get("type", "").startswith("image/")
                or media.get("medium") == "image"
                or media in entry.get("media_thumbnail", [])
            ):
                picture = url
                break
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))
        summary = re.sub(r"\\s+", " ", summary).strip()
        # images must be explicitly enabled: check provider rights before displaying at work.
        if picture and CFG.get("news_images", False):
            try:
                from urllib.parse import urlparse
                from PIL import UnidentifiedImageError
                from ipaddress import ip_address
                import socket
                host = urlparse(picture).hostname
                addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                if not addresses or any(not ip_address(addr[4][0]).is_global for addr in addresses):
                    raise ValueError("non-public image host")
                resp = requests.get(picture, timeout=10, stream=True)
                resp.raise_for_status()
                if not resp.headers.get("Content-Type", "").lower().startswith("image/"):
                    raise ValueError("not an image")
                data = b""
                for chunk in resp.iter_content(65536):
                    data += chunk
                    if len(data) > 5_000_000:
                        raise ValueError("image too large")
                with Image.open(io.BytesIO(data)) as img:
                    img.verify()
                results.append(publish(render_news(title, summary, data), "news"))
                continue
            except Exception:
                logging.exception("Could not load image for %s", title)
        results.append(publish(render(title, summary[:300] + " | Quelle: " + CFG.get("news_source_label", "RSS"), "NEWS"), "news"))
    return results


def render_news(title, summary, image_bytes):
    w, h = int(CFG.get("slide_width", 1920)), int(CFG.get("slide_height", 1080))
    canvas = Image.new("RGB", (w, h), "#f5f5f2")
    draw = ImageDraw.Draw(canvas)
    margin = int(w * .045)
    gap = int(w * .035)
    image_w = int(w * .43)
    top = int(h * .17)
    bottom = int(h * .89)
    image_h = bottom - top
    text_x = margin + image_w + gap
    text_width = w - margin - text_x
    # keep image proportions, same top edge as text; no stretching or overlap.
    with Image.open(io.BytesIO(image_bytes)) as source:
        picture = source.convert("RGB")
        picture.thumbnail((image_w, image_h), Image.Resampling.LANCZOS)
        canvas.paste(picture, (margin + (image_w - picture.width) // 2, top))
    label = str(CFG.get("news_source_label", "RSS"))
    draw.text((margin, int(h * .065)), label, font=font(int(h * .034), True), fill="#555555")
    draw.line((margin, int(h * .13), w - margin, int(h * .13)), fill="#bbbbbb", width=2)
    title_font, title_lines = fit_lines(
        draw, title, text_width, 6, int(h * .054), int(h * .033), True
    )
    y = top
    for line in title_lines:
        draw.text((text_x, y), line, font=title_font, fill="#181818")
        y += int(title_font.size * 1.25)
    y += int(h * .035)
    available = max(0, bottom - y)
    if available:
        summary_font, summary_lines = fit_lines(
            draw, summary, text_width, max(1, available // int(h * .043)),
            int(h * .028), int(h * .021)
        )
        for line in summary_lines:
            if y + summary_font.size > bottom:
                break
            draw.text((text_x, y), line, font=summary_font, fill="#444444")
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
        "current": "temperature_2m,weather_code", "timezone": "Europe/Berlin"
    }, timeout=20)
    response.raise_for_status()
    current = response.json()["current"]
    description = f"{config.get('label', 'Wetter')} · Wettercode {current['weather_code']} · Quelle: Open-Meteo"
    return [publish(render(f"{current['temperature_2m']} °C", description, "WETTER"), "weather")]


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
    if CFG.get("clock", {}).get("enabled", False):
        now = datetime.now(TZ)
        names.append(publish(render(now.strftime("%H:%M"), now.strftime("%A, %d.%m.%Y"), "UHRZEIT"), "clock"))
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


@app.get("/healthz")
def health():
    return {"status": "ok", "inventory_ready": (OUT / "inventory.txt").exists()}


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, use_reloader=False)
