"""Tiny bridge for Binary Emotions Raspberry Slideshow.

The normal app stays a browser kiosk. This addon only turns the already loaded
RSS articles into plain JPEGs + an inventory/serverlist that Raspberry
Slideshow can download through media.conf.
"""
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


WIDTH = 1920
HEIGHT = 1080


def _hex(value, fallback):
    value = str(value or "").strip()
    if len(value) == 7 and value.startswith("#"):
        try:
            tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
            return value
        except ValueError:
            pass
    return fallback


def _font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_lines(draw, text, font, width, max_lines):
    words = str(text or "").split()
    if not words:
        return []
    lines, current = [], ""
    for word in words:
        candidate = word if not current else current + " " + word
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        full = " ".join(words)
        shown = " ".join(lines)
        if shown != full:
            while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > width:
                lines[-1] = lines[-1][:-1].rstrip()
            lines[-1] = lines[-1] + "…"
    return lines


def _paste_logo(canvas, logo_path, x, y, max_size):
    if not logo_path:
        return
    path = Path(logo_path)
    if not path.is_file():
        return
    try:
        with Image.open(path) as source:
            logo = source.convert("RGBA")
            logo.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            canvas.alpha_composite(logo, (x, y + (max_size - logo.height) // 2))
    except Exception:
        # A broken optional logo should never break the inventory feed.
        return


def inventory_text(articles, base_url, limit=10):
    base = str(base_url).rstrip("/")
    lines = []
    for article in list(articles)[:max(1, min(int(limit), 30))]:
        article_id = str(article.get("id") or "").strip()
        if article_id:
            lines.append(f"{base}/addons/binary-emotions/slides/{article_id}.jpg")
    return "\n".join(lines) + ("\n" if lines else "")


def render_slide_jpeg(article, settings, logo_path=None):
    """Render one stable 1920x1080 slide. No remote image fetches here."""
    accent = _hex(settings.get("accent_color"), "#2563eb")
    paper = _hex(settings.get("background_color"), "#f8fafc")
    ink = _hex(settings.get("text_color"), "#1f2937")
    header = _hex(settings.get("header_color"), "#ffffff")
    footer = _hex(settings.get("footer_color"), "#eef2f7")

    canvas = Image.new("RGBA", (WIDTH, HEIGHT), paper)
    draw = ImageDraw.Draw(canvas)

    header_h = 150
    footer_h = 92
    pad = 74

    draw.rectangle((0, 0, WIDTH, header_h), fill=header)
    draw.rectangle((0, HEIGHT - footer_h, WIDTH, HEIGHT), fill=footer)
    draw.rectangle((0, 0, WIDTH, 8), fill=accent)

    _paste_logo(canvas, logo_path, pad, 18, 112)

    brand = str(settings.get("brand_name") or "RSS")
    source = str(article.get("source") or "RSS")
    brand_x = pad + (145 if logo_path else 0)
    brand_font = _font(42, bold=True)
    source_font = _font(30, bold=True)
    draw.text((brand_x, 36), brand, fill=accent, font=brand_font)
    if settings.get("show_source", True) is not False:
        draw.text((brand_x, 90), "Aktuelle Nachrichten: " + source, fill=ink, font=source_font)

    left = pad
    top = header_h + 76
    content_width = WIDTH - (2 * pad)

    title = str(article.get("title") or "")
    summary = str(article.get("summary") or "")

    title_font = _font(64, bold=True)
    summary_font = _font(34)
    title_lines = _fit_lines(draw, title, title_font, content_width, 4)
    y = top
    for line in title_lines:
        draw.text((left, y), line, fill=accent, font=title_font)
        y += 78

    y += 32
    summary_lines = _fit_lines(draw, summary, summary_font, content_width, 8)
    for line in summary_lines:
        if y > HEIGHT - footer_h - 55:
            break
        draw.text((left, y), line, fill=ink, font=summary_font)
        y += 49

    names = settings.get("footer_names") if settings.get("show_footer_names", True) is not False else []
    if isinstance(names, list) and names:
        footer_text = "  |  ".join(str(name).strip() for name in names[:6] if str(name).strip())
    else:
        footer_text = brand
    footer_font = _font(26, bold=True)
    draw.text((pad, HEIGHT - footer_h + 29), footer_text, fill=accent, font=footer_font)

    output = BytesIO()
    canvas.convert("RGB").save(output, format="JPEG", quality=91, optimize=True)
    return output.getvalue()
