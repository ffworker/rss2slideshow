import base64
import io
from html.parser import HTMLParser
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from app import main


def auth_header(user="admin", password="secret"):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": "Basic " + token}


class AdminStructureParser(HTMLParser):
    """Collect the rendered form structure without a browser dependency."""

    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class AdminTests(unittest.TestCase):
    def test_admin_is_closed_until_credentials_are_configured(self):
        with patch.dict(os.environ, {"ADMIN_USER": "", "ADMIN_PASSWORD": ""}):
            with main.app.test_client() as client:
                self.assertEqual(client.get("/admin").status_code, 503)

    def test_admin_requires_basic_auth(self):
        with patch.dict(os.environ, {"ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret"}):
            with main.app.test_client() as client:
                self.assertEqual(client.get("/admin").status_code, 401)
                response = client.get("/admin", headers=auth_header())
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"RSS2Slideshow", response.data)
                self.assertIn(b"RSS-Feeds", response.data)
                self.assertIn(b"Grobe Vorschau", response.data)
                self.assertIn("nicht maßstabsgetreu", response.get_data(as_text=True))
                self.assertIn(b"design_overlay_headline_color", response.data)
                self.assertIn(b"design_font_family", response.data)

    def test_authenticated_admin_shows_failed_feed_names(self):
        with patch.dict(os.environ, {"ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret"}), \
             patch.dict(main.snapshot, {"failed_sources": ["Regional"]}):
            with main.app.test_client() as client:
                response = client.get("/admin", headers=auth_header())
        self.assertEqual(response.status_code, 200)
        self.assertIn("Abruf fehlgeschlagen: Regional", response.get_data(as_text=True))

    def test_design_studio_full_width_preview_and_compact_content_sections(self):
        with patch.dict(os.environ, {"ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret"}):
            with main.app.test_client() as client:
                response = client.get("/admin", headers=auth_header())
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        dom = AdminStructureParser()
        dom.feed(html)
        elements = dom.elements
        ids = [attrs["id"] for _, attrs in elements if attrs.get("id")]
        self.assertEqual(len(ids), len(set(ids)), "All rendered control IDs must be unique")
        self.assertLess(ids.index("design-editor"), ids.index("rss-feeds"))
        self.assertLess(ids.index("design-preview"), ids.index("display-settings"))
        self.assertLess(ids.index("rss-feeds"), ids.index("rss-status"))

        tabs = [attrs for _, attrs in elements if attrs.get("role") == "tab"]
        panels = [attrs for _, attrs in elements if attrs.get("role") == "tabpanel"]
        self.assertEqual(len(tabs), 5)
        self.assertEqual(len(panels), 5)
        for tab in tabs:
            self.assertIn(tab["aria-controls"], ids)
            self.assertIn(tab["id"], [p["aria-labelledby"] for p in panels])
        self.assertEqual([p for p in panels if "hidden" not in p], [panels[0]])

        for required_id in (
            "design_font_family", "design_headline_size", "design_summary_size",
            "design_show_clock", "design_show_source", "design_show_footer_names",
            "design_footer_names", "design_logo", "feeds", "slide_seconds",
            "max_articles", "refresh_minutes", "design-draft-status",
        ):
            self.assertIn(required_id, ids)
        actions = [attrs.get("value") for tag, attrs in elements
                   if tag == "button" and attrs.get("name") == "action"]
        for action in ("save_design", "reset_design", "save_feeds",
                       "test_feeds", "save_settings", "refresh"):
            self.assertIn(action, actions)
        self.assertIn("Grobe Vorschau", html)
        self.assertIn("nicht maßstabsgetreu", html)
        self.assertIn("activateDesignTab", html)
        self.assertIn("markDesignDirty", html)
        self.assertIn("aspect-ratio:16/9", html)
        self.assertNotIn(".design-layout{display:grid;grid-template-columns:minmax(320px,420px)", html)

    def test_customer_can_save_feeds_and_get_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret"}
        ):
            content_dir = Path(tmp)
            feed_file = content_dir / "feeds.txt"
            feed_file.write_text("Old | https://example.org/old.xml\n", encoding="utf-8")
            admin_file = content_dir / "admin-settings.yaml"
            with patch.object(main, "FEED_FILE", feed_file), patch.object(main, "ADMIN_SETTINGS_FILE", admin_file):
                with main.app.test_client() as client:
                    response = client.post(
                        "/admin",
                        headers=auth_header(),
                        data={
                            "csrf": main.admin_form_token(),
                            "action": "save_feeds",
                            "feed_label": ["Südhessen", "Hessen"],
                            "feed_url": ["https://example.org/south.xml", "https://example.org/hessen.xml"],
                        },
                    )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                feed_file.read_text(encoding="utf-8"),
                "Südhessen | https://example.org/south.xml\nHessen | https://example.org/hessen.xml\n",
            )
            self.assertEqual(
                (content_dir / "feeds.txt.bak").read_text(encoding="utf-8"),
                "Old | https://example.org/old.xml\n",
            )

    def test_customer_can_save_small_display_overrides(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret"}
        ):
            content_dir = Path(tmp)
            feed_file = content_dir / "feeds.txt"
            feed_file.write_text("", encoding="utf-8")
            admin_file = content_dir / "admin-settings.yaml"
            with patch.object(main, "FEED_FILE", feed_file), patch.object(main, "ADMIN_SETTINGS_FILE", admin_file):
                with main.app.test_client() as client:
                    response = client.post(
                        "/admin",
                        headers=auth_header(),
                        data={
                            "csrf": main.admin_form_token(),
                            "action": "save_settings",
                            "slide_seconds": "35",
                            "max_articles": "9",
                            "refresh_minutes": "7",
                            "news_images": "on",
                        },
                    )
                saved = yaml.safe_load(admin_file.read_text(encoding="utf-8"))
                active = main.runtime_settings()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(saved["slide_seconds"], 35)
            self.assertEqual(saved["max_articles"], 9)
            self.assertEqual(saved["refresh_minutes"], 7)
            self.assertTrue(saved["news_images"])
            self.assertEqual(active["slide_seconds"], 35)
            self.assertEqual(active["max_articles"], 9)
            self.assertTrue(active["news_images"])

    def test_design_editor_saves_logo_and_can_reset_to_profile_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret", "ADMIN_KIOSK_PATH": "/"}
        ):
            root = Path(tmp)
            content = root / "content"
            content.mkdir()
            feed_file = content / "feeds.txt"
            feed_file.write_text("", encoding="utf-8")
            admin_file = content / "admin-settings.yaml"
            design_file = content / "ui-settings.yaml"
            with patch.object(main, "ROOT", root), \
                 patch.object(main, "FEED_FILE", feed_file), \
                 patch.object(main, "ADMIN_SETTINGS_FILE", admin_file), \
                 patch.object(main, "DESIGN_SETTINGS_FILE", design_file):
                with main.app.test_client() as client:
                    response = client.post(
                        "/admin",
                        headers=auth_header(),
                        content_type="multipart/form-data",
                        data={
                            "csrf": main.admin_form_token(),
                            "action": "save_design",
                            "design_brand_name": "Example News",
                            "design_accent_color": "#2563eb",
                            "design_background_color": "#f8fafc",
                            "design_text_color": "#202020",
                            "design_header_color": "#ffffff",
                            "design_footer_color": "#eef2f7",
                            "design_font_family": "Verdana",
                            "design_headline_color": "#2563eb",
                            "design_summary_color": "#203040",
                            "design_overlay_headline_color": "#2563eb",
                            "design_overlay_summary_color": "#ffffff",
                            "design_header_height": "160",
                            "design_footer_height": "88",
                            "design_logo_size": "120",
                            "design_image_width": "60",
                            "design_headline_size": "98",
                            "design_summary_size": "48",
                            "design_image_fit": "cover",
                            "design_story_layout": "overlay",
                            "design_show_clock": "on",
                            "design_show_source": "on",
                            "design_show_footer_names": "on",
                            "design_footer_names": "Example A\nExample B\nExample C",
                            "design_logo": (io.BytesIO(b"\x89PNG\r\n\x1a\nnot-a-real-png-but-valid-signature"), "logo.png"),
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("Design gespeichert", response.get_data(as_text=True))
                    saved = yaml.safe_load(design_file.read_text(encoding="utf-8"))
                    self.assertEqual(saved["brand_name"], "Example News")
                    self.assertEqual(saved["image_width"], 60)
                    self.assertEqual(saved["image_fit"], "cover")
                    self.assertEqual(saved["story_layout"], "overlay")
                    self.assertEqual(saved["font_family"], "Verdana")
                    self.assertEqual(saved["headline_size"], 98)
                    self.assertEqual(saved["summary_size"], 48)
                    self.assertEqual(saved["overlay_headline_color"], "#2563eb")
                    self.assertEqual(saved["overlay_summary_color"], "#ffffff")
                    self.assertEqual(saved["summary_color"], "#203040")
                    self.assertTrue(saved["show_clock"])
                    self.assertEqual(saved["footer_names"], ["Example A", "Example B", "Example C"])
                    self.assertTrue((content / "design-logo.png").is_file())

                    api = client.get("/api/articles").get_json()
                    self.assertTrue(api["design_enabled"])
                    self.assertEqual(api["brand_name"], "Example News")
                    self.assertEqual(api["headline_size"], 98)
                    self.assertEqual(api["summary_size"], 48)
                    self.assertEqual(api["font_family"], "Verdana")
                    self.assertEqual(api["overlay_headline_color"], "#2563eb")
                    self.assertTrue(api["logo_url"].startswith("/design-logo?v="))
                    logo = client.get("/design-logo")
                    self.assertEqual(logo.status_code, 200)
                    self.assertEqual(logo.mimetype, "image/png")

                    reset = client.post(
                        "/admin",
                        headers=auth_header(),
                        data={"csrf": main.admin_form_token(), "action": "reset_design"},
                    )
                    self.assertEqual(reset.status_code, 200)
                    self.assertFalse(design_file.exists())
                    self.assertFalse((content / "design-logo.png").exists())
                    after = client.get("/api/articles").get_json()
                    self.assertFalse(after["design_enabled"])

    def test_new_typography_controls_validate_inputs_and_old_design_files_get_safe_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret"}
        ):
            root = Path(tmp)
            content = root / "content"
            content.mkdir()
            design_file = content / "ui-settings.yaml"
            # An existing installation's old override file must still load safely.
            design_file.write_text("brand_name: Example old\nheadline_size: 55\n", encoding="utf-8")
            with patch.object(main, "ROOT", root), patch.object(main, "DESIGN_SETTINGS_FILE", design_file):
                design = main.read_design_settings()
                self.assertEqual(design["font_family"], "sans")
                self.assertEqual(design["headline_size"], 55)
                self.assertEqual(design["overlay_headline_color"], design["accent_color"])
                self.assertEqual(design["overlay_summary_color"], "#ffffff")
                previous = design_file.read_text(encoding="utf-8")
                with main.app.test_client() as client:
                    for field, value, error in (
                        ("design_font_family", "Injected; font:invalid", "Schriftart"),
                        ("design_overlay_headline_color", "url(evil)", "Farben"),
                    ):
                        form = {
                            "csrf": main.admin_form_token(), "action": "save_design",
                            "design_brand_name": "Example",
                            "design_accent_color": "#2563eb",
                            "design_background_color": "#f8fafc",
                            "design_text_color": "#202020",
                            "design_header_color": "#ffffff",
                            "design_footer_color": "#eef2f7",
                            "design_font_family": "Calibri",
                        }
                        form[field] = value
                        result = client.post("/admin", headers=auth_header(), data=form)
                        self.assertEqual(result.status_code, 200)
                        self.assertIn(error, result.get_data(as_text=True))
                        self.assertEqual(design_file.read_text(encoding="utf-8"), previous)

    def test_admin_rejects_bad_feed_urls_and_csrf(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret"}
        ):
            feed_file = Path(tmp) / "feeds.txt"
            feed_file.write_text("", encoding="utf-8")
            admin_file = Path(tmp) / "admin-settings.yaml"
            with patch.object(main, "FEED_FILE", feed_file), patch.object(main, "ADMIN_SETTINGS_FILE", admin_file):
                with main.app.test_client() as client:
                    bad_token = client.post(
                        "/admin", headers=auth_header(),
                        data={"csrf": "wrong", "action": "save_feeds"},
                    )
                    bad_url = client.post(
                        "/admin", headers=auth_header(),
                        data={
                            "csrf": main.admin_form_token(),
                            "action": "save_feeds",
                            "feed_label": ["Nope"],
                            "feed_url": ["file:///etc/passwd"],
                        },
                    )
            self.assertEqual(bad_token.status_code, 400)
            self.assertEqual(bad_url.status_code, 200)
            self.assertIn("Feed-URLs", bad_url.get_data(as_text=True))
            self.assertEqual(feed_file.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
