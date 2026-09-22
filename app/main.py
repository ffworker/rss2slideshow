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


def render(title, subtitle="", kind="NEWS"):
    w, h = int(CFG.get("slide_width", 1920)), int(CFG.get("slide_height", 1080))
    image = Image.new("RGB", (w, h), "#122036")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w, 22), fill="#63a9ff")
    draw.text((90, 85), str(CFG.get("company_name", "Company")), font=font(44, True), fill="#b6c9e2")
    draw.text((90, 215), kind, font=font(37, True), fill="#63a9ff")
    y = 300
    for line in wrap(draw, title, font(80, True), w - 180)[:5]:
        if y + 105 > h - 90:
            break
        draw.text((90, y), line, font=font(80, True), fill="white")
        y += 105
    y += 35
    for line in wrap(draw, subtitle, font(39), w - 180)[:5]:
        if y + 57 > h - 90:
            break
        draw.text((90, y), line, font=font(39), fill="#c9d4e3")
        y += 57
    draw.text((90, h - 75), datetime.now(TZ).strftime("%d.%m.%Y  %H:%M"), font=font(32), fill="#a4b6cf")
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
    canvas = Image.new("RGB", (w, h), "#122036")
    with Image.open(io.BytesIO(image_bytes)) as source:
        picture = source.convert("RGB")
        picture.thumbnail((int(w * .45), int(h * .7)))
        canvas.paste(picture, (w - picture.width - 65, (h - picture.height) // 2))
    draw = ImageDraw.Draw(canvas)
    draw.text((65, 65), "NEWS · " + CFG.get("news_source_label", "RSS"), font=font(36, True), fill="#80b9ff")
    y = 220
    for line in wrap(draw, title, font(58, True), int(w * .52))[:6]:
        draw.text((65, y), line, font=font(58, True), fill="white")
        y += 78
    y += 30
    for line in wrap(draw, summary, font(29), int(w * .52))[:5]:
        if y > h - 90:
            break
        draw.text((65, y), line, font=font(29), fill="#d1dae8")
        y += 44
    buffer = io.BytesIO()
    canvas.save(buffer, "JPEG", quality=88)
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
