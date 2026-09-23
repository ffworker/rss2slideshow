"""One customer look per kiosk installation. Local files, no customer stuff in git."""
import logging
import re
from pathlib import Path

import yaml

LOG = logging.getLogger(__name__)
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
FONT_NAME = re.compile(r"^[\w \-]{1,80}$", re.UNICODE)


def _color(value, fallback):
    value = str(value or "").strip()
    if not HEX.fullmatch(value):
        return fallback
    if len(value) == 4:
        value = "#" + "".join(character * 2 for character in value[1:])
    return value.lower()


def _file_url(folder, filename):
    path = Path(folder) / filename
    if path.is_file():
        # browser will fetch a replacement asset even if the filename stays the same
        return "/branding/" + filename + "?v=" + str(path.stat().st_mtime_ns)
    return ""


def read_brand(root, fallback=None):
    """Reload branding/brand.yaml at request time; fall back to old config during upgrades."""
    root = Path(root)
    legacy = fallback or {}
    settings = {
        "brand_name": str(legacy.get("brand_name") or "rss2slideshow")[:60],
        "accent_color": _color(legacy.get("accent_color", "#8b3932"), "#8b3932"),
        "background_color": "#f8f7f3",
        "text_color": "#242424",
        "font_family": "news",
        "logo_url": "",
        "font_url": "",
    }
    folder = root / "branding"
    path = folder / "brand.yaml"
    if path.is_file():
        try:
            custom = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(custom, dict):
                raise ValueError("brand.yaml needs key: value pairs")
            if custom.get("brand_name"):
                settings["brand_name"] = str(custom["brand_name"]).strip()[:60]
            for field in ("accent_color", "background_color", "text_color"):
                if field in custom:
                    chosen = _color(custom[field], settings[field])
                    if chosen == settings[field] and str(custom[field]).strip().lower() != chosen:
                        LOG.warning("invalid %s in branding/brand.yaml", field)
                    settings[field] = chosen
            chosen_font = str(custom.get("font_family", "news")).strip()
            if FONT_NAME.fullmatch(chosen_font):
                settings["font_family"] = chosen_font
            else:
                LOG.warning("invalid font_family in branding/brand.yaml; using news")
        except (OSError, ValueError, yaml.YAMLError):
            LOG.exception("could not read branding/brand.yaml, keeping default look")

    settings["logo_url"] = _file_url(folder, "logo.png")
    settings["font_url"] = _file_url(folder, "font.woff2")
    if not settings["logo_url"]:
        # old installations may still have their logo in assets/logo.png
        old_logo = root / "assets" / "logo.png"
        if old_logo.is_file():
            settings["logo_url"] = "/assets/logo.png?v=" + str(old_logo.stat().st_mtime_ns)
    return settings
