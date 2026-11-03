import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.branding import read_brand
from app import main


class BrandingTests(unittest.TestCase):
    def test_neutral_default_and_removed_customer_assets(self):
        root = Path(__file__).resolve().parents[1]
        brand = read_brand(root)
        self.assertEqual(brand["brand_name"], "RSS2Slideshow")
        self.assertEqual(brand["tagline"], "by Bytegeist")
        self.assertEqual(brand["layout"], "standard")
        self.assertEqual(brand["accent_color"], "#2563eb")
        self.assertEqual(brand["logo_url"], "")
        self.assertEqual(brand["footer_names"], [])
        self.assertFalse(brand["show_group_logo"])
        with patch.object(main, "ROOT", root):
            with main.app.test_client() as client:
                self.assertEqual(client.get("/").status_code, 200)
                self.assertEqual(client.get("/kiosk").status_code, 200)
                result = client.get("/api/articles").get_json()
                self.assertEqual(result["brand_name"], "RSS2Slideshow")
                player = client.get("/").get_data(as_text=True)
                self.assertIn('id="footer-names"', player)
                self.assertIn("kiosk-design-preview", player)
                self.assertIn("event.origin !== location.origin", player)
                self.assertIn("--accent:#2563eb", player)
                self.assertNotIn("--accent:#8b3932", player)

    def test_site_local_brand_and_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "branding"
            folder.mkdir()
            (folder / "brand.yaml").write_text(
                'brand_name: "Example"\nlayout: featured\naccent_color: "#123456"\n'
                'footer_names: ["Example A", "Example B"]\n', encoding="utf-8")
            (folder / "logo.png").write_bytes(b"local-logo")
            brand = read_brand(root)
            self.assertEqual(brand["brand_name"], "Example")
            self.assertEqual(brand["layout"], "featured")
            self.assertEqual(brand["accent_color"], "#123456")
            self.assertEqual(brand["footer_names"], ["Example A", "Example B"])
            self.assertTrue(brand["logo_url"].startswith("/branding/logo.png?v="))
            with patch.object(main, "ROOT", root):
                with main.app.test_client() as client:
                    self.assertEqual(client.get("/api/articles").get_json()["brand_name"], "Example")
                    self.assertEqual(client.get("/branding/brand.yaml").status_code, 404)
                    self.assertEqual(client.get("/branding/logo.png").data, b"local-logo")

    def test_saved_legacy_layout_keeps_effective_configuration(self):
        # Preserve the existing API setting and rendered layout after an update.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "branding"
            folder.mkdir()
            (folder / "brand.yaml").write_text("layout: bistro\n", encoding="utf-8")
            self.assertEqual(read_brand(root)["layout"], "bistro")
            player = (Path(__file__).resolve().parents[1] / "app" / "player.html").read_text()
            self.assertIn('data.layout === "bistro"', player)
            with patch.object(main, "ROOT", root):
                with main.app.test_client() as client:
                    self.assertEqual(client.get("/api/articles").get_json()["layout"], "bistro")

    def test_invalid_override_keeps_neutral_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "branding"
            folder.mkdir()
            (folder / "brand.yaml").write_text(
                'accent_color: invalid\nfont_family: "bad;url(fake)"\n', encoding="utf-8")
            brand = read_brand(tmp)
            self.assertEqual(brand["brand_name"], "RSS2Slideshow")
            self.assertEqual(brand["accent_color"], "#2563eb")
            self.assertEqual(brand["font_family"], "sans")


if __name__ == "__main__":
    unittest.main()
