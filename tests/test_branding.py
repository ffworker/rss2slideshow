import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.branding import read_brand
from app import main


class CustomerBrandTests(unittest.TestCase):
    def test_customer_can_swap_name_colors_and_font_while_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "branding"
            folder.mkdir()
            cfg = folder / "brand.yaml"
            cfg.write_text(
                'brand_name: "Customer One"\n'
                'accent_color: "#c04"\n'
                'font_family: "Verdana"\n',
                encoding="utf-8",
            )
            first = read_brand(root)
            self.assertEqual(first["brand_name"], "Customer One")
            self.assertEqual(first["accent_color"], "#cc0044")
            self.assertEqual(first["font_family"], "Verdana")

            cfg.write_text(
                'brand_name: "Customer Two"\n'
                'accent_color: "#123456"\n'
                'font_family: "news"\n',
                encoding="utf-8",
            )
            second = read_brand(root)
            self.assertEqual(second["brand_name"], "Customer Two")
            self.assertEqual(second["accent_color"], "#123456")
            self.assertEqual(second["font_family"], "news")

    def test_optional_logo_and_webfont_stay_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "branding"
            folder.mkdir()
            self.assertEqual(read_brand(tmp)["logo_url"], "")
            self.assertEqual(read_brand(tmp)["font_url"], "")
            (folder / "logo.png").write_bytes(b"fake logo")
            (folder / "font.woff2").write_bytes(b"fake font")
            settings = read_brand(tmp)
            self.assertTrue(settings["logo_url"].startswith("/branding/logo.png?v="))
            self.assertTrue(settings["font_url"].startswith("/branding/font.woff2?v="))

            with patch.object(main, "ROOT", Path(tmp)):
                with main.app.test_client() as client:
                    self.assertEqual(client.get("/branding/logo.png").status_code, 200)
                    self.assertEqual(client.get("/branding/font.woff2").status_code, 200)
                    self.assertEqual(client.get("/branding/brand.yaml").status_code, 404)
                    data = client.get("/api/articles").get_json()
                    self.assertEqual(data["logo_url"], settings["logo_url"])
                    self.assertEqual(data["font_url"], settings["font_url"])

    def test_invalid_brand_values_use_safe_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "branding"
            folder.mkdir()
            (folder / "brand.yaml").write_text(
                'accent_color: "not-a-color"\n'
                'font_family: "bad;font:url(fake)"\n',
                encoding="utf-8",
            )
            settings = read_brand(tmp, {"brand_name": "Previous setup"})
            self.assertEqual(settings["brand_name"], "Previous setup")
            self.assertEqual(settings["accent_color"], "#8b3932")
            self.assertEqual(settings["font_family"], "news")


if __name__ == "__main__":
    unittest.main()
