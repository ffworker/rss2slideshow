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


def _file_url(folder, filename, prefix="/branding"):
    path = Path(folder) / filename
    if path.is_file():
        # browser will fetch a replacement asset even if the filename stays the same
        return prefix + "/" + filename + "?v=" + str(path.stat().st_mtime_ns)
    return ""


def read_brand(root, fallback=None, profile=None):
    """Reload branding/brand.yaml at request time; fall back to old config during upgrades."""
    root = Path(root)
    legacy = fallback or {}
    settings = {
        "brand_name": str(legacy.get("brand_name") or "rss2slideshow")[:60],
        "accent_color": _color(legacy.get("accent_color", "#8b3932"), "#8b3932"),
        "background_color": "#f8f7f3",
        "text_color": "#242424",
        "header_color": "",
        "footer_color": "",
        "logo_mode": "normal",
        "layout": "standard",
        "tagline": "",
        "show_group_logo": True,
        "source_in_header": False,
        "font_family": "news",
        "logo_url": "",
        "group_logo_url": "",
        "footer_banner_url": "",
        "footer_names": [],
        "font_url": "",
    }
    if profile is not None and not re.fullmatch(r"[a-z0-9-]{1,40}", profile):
        raise ValueError("invalid demo profile")
    folder = root / "branding" / "examples" / profile if profile else root / "branding"
    prefix = "/branding/examples/" + profile if profile else "/branding"
    path = folder / "brand.yaml"
    if path.is_file():
        try:
            custom = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(custom, dict):
                raise ValueError("brand.yaml needs key: value pairs")
            if custom.get("brand_name"):
                settings["brand_name"] = str(custom["brand_name"]).strip()[:60]
            for field in ("accent_color", "background_color", "text_color", "header_color", "footer_color"):
                if field in custom:
                    chosen = _color(custom[field], settings[field])
                    if chosen == settings[field] and str(custom[field]).strip().lower() != chosen:
                        LOG.warning("invalid %s in branding/brand.yaml", field)
                    settings[field] = chosen
            settings["logo_mode"] = "wide" if custom.get("logo_mode") == "wide" else "normal"
            settings["layout"] = "bistro" if custom.get("layout") == "bistro" else "standard"
            settings["tagline"] = str(custom.get("tagline") or "")[:80]
            settings["show_group_logo"] = custom.get("show_group_logo", True) is not False
            settings["source_in_header"] = custom.get("source_in_header", False) is True
            # text, not a microscopic banner picture: reads well on HD and full HD
            names = custom.get("footer_names", [])
            if isinstance(names, list):
                settings["footer_names"] = [
                    str(name).strip()[:48] for name in names[:6]
                    if isinstance(name, str) and name.strip()
                ]
            elif names:
                LOG.warning("footer_names should be a YAML list")
            chosen_font = str(custom.get("font_family", "news")).strip()
            if FONT_NAME.fullmatch(chosen_font):
                settings["font_family"] = chosen_font
            else:
                LOG.warning("invalid font_family in branding/brand.yaml; using news")
        except (OSError, ValueError, yaml.YAMLError):
            LOG.exception("could not read branding/brand.yaml, keeping default look")

    settings["logo_url"] = _file_url(folder, "logo.png", prefix)
    settings["group_logo_url"] = (_file_url(folder, "claim-logo.png", prefix)
                                   or _file_url(folder, "group-logo.png", prefix))
    settings["footer_banner_url"] = _file_url(folder, "footer-banner.png", prefix)
    settings["font_url"] = _file_url(folder, "font.woff2", prefix)
    if not settings["logo_url"] and not profile:
        # old installations may still have their logo in assets/logo.png
        old_logo = root / "assets" / "logo.png"
        if old_logo.is_file():
            settings["logo_url"] = "/assets/logo.png?v=" + str(old_logo.stat().st_mtime_ns)
    return settings
