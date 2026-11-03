"""RSS2Slideshow neutral branding with optional site-local overrides."""
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


def read_brand(root, fallback=None):
    """Load neutral defaults, then optional host-local branding/brand.yaml."""
    root = Path(root)
    legacy = fallback or {}
    settings = {
        "brand_name": str(legacy.get("brand_name") or "RSS2Slideshow")[:60],
        "accent_color": _color(legacy.get("accent_color", "#2563eb"), "#2563eb"),
        "background_color": "#f8fafc",
        "text_color": "#1f2937",
        "header_color": "#ffffff",
        "footer_color": "#eef2f7",
        "logo_mode": "normal",
        "layout": "standard",
        "tagline": "by Bytegeist",
        "show_group_logo": False,
        "source_in_header": False,
        "font_family": "sans",
        "logo_url": "",
        "group_logo_url": "",
        "footer_banner_url": "",
        "footer_names": [],
        "font_url": "",
    }
    for folder, prefix in ((root / "branding", "/branding"),):
        path = folder / "brand.yaml"
        if not path.is_file():
            continue
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
            if "logo_mode" in custom:
                settings["logo_mode"] = "wide" if custom["logo_mode"] == "wide" else "normal"
            if "layout" in custom:
                # Keep saved legacy layout identifiers unchanged for existing installs.
                settings["layout"] = (custom["layout"] if custom["layout"] in ("featured", "bistro") else "standard")
            if "tagline" in custom:
                settings["tagline"] = str(custom["tagline"] or "")[:80]
            if "show_group_logo" in custom:
                settings["show_group_logo"] = custom["show_group_logo"] is not False
            if "source_in_header" in custom:
                settings["source_in_header"] = custom["source_in_header"] is True
            # Optional footer labels are plain text.
            names = custom.get("footer_names")
            if isinstance(names, list):
                settings["footer_names"] = [
                    str(name).strip()[:48] for name in names[:6]
                    if isinstance(name, str) and name.strip()
                ]
            elif names:
                LOG.warning("footer_names should be a YAML list")
            chosen_font = str(custom.get("font_family", settings["font_family"])).strip()
            if FONT_NAME.fullmatch(chosen_font):
                settings["font_family"] = chosen_font
            else:
                LOG.warning("invalid font_family in %s; keeping previous font", path)
        except (OSError, ValueError, yaml.YAMLError):
            LOG.exception("could not read %s, keeping previous look", path)

    # Prefer optional site-local vector branding, with PNG fallback.
    folders = ((root / "branding", "/branding"),)
    def asset(*names):
        return next((url for folder, prefix in folders for name in names
                     if (url := _file_url(folder, name, prefix))), "")
    settings["logo_url"] = asset("logo.svg", "logo.svgz", "logo.png")
    settings["group_logo_url"] = asset("claim-logo.png", "group-logo.png")
    settings["footer_banner_url"] = asset("footer-banner.png")
    settings["font_url"] = asset("font.woff2")
    if not settings["logo_url"]:
        # old installations may still have their logo in assets/logo.png
        old_logo = root / "assets" / "logo.png"
        if old_logo.is_file():
            settings["logo_url"] = "/assets/logo.png?v=" + str(old_logo.stat().st_mtime_ns)
    return settings
