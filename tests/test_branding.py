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

    def test_approved_demo_is_separate_from_live_customer_brand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "branding"
            local.mkdir()
            (local / "brand.yaml").write_text(
                'brand_name: "Live client"\naccent_color: "#123456"\n', encoding="utf-8"
            )
            demo = local / "examples" / "logserv"
            demo.mkdir(parents=True)
            (demo / "brand.yaml").write_text(
                'brand_name: "Bistro Connect"\nheader_color: "#ec6608"\n'
                'footer_color: "#ec6608"\nbackground_color: "#ffdd00"\n'
                'font_family: Calibri\nlogo_mode: wide\n', encoding="utf-8"
            )
            (demo / "logo.png").write_bytes(b"logo")
            with patch.object(main, "ROOT", root):
                with main.app.test_client() as client:
                    live = client.get("/api/articles").get_json()
                    preview = client.get("/api/articles?demo=logserv").get_json()
                    self.assertEqual(client.get("/demo/logserv").status_code, 200)
                    self.assertEqual(client.get("/demo/unknown").status_code, 404)
                    self.assertEqual(client.get("/api/articles?demo=unknown").status_code, 404)
                    self.assertEqual(client.get("/branding/examples/logserv/brand.yaml").status_code, 404)
                    self.assertEqual(client.get("/branding/examples/logserv/logo.png").status_code, 200)
                    self.assertEqual(client.get("/branding/examples/logserv/group-logo.png").status_code, 404)
            self.assertEqual(live["brand_name"], "Live client")
            self.assertEqual(preview["brand_name"], "Bistro Connect")
            self.assertEqual(preview["background_color"], "#ffdd00")
            self.assertEqual(preview["header_color"], "#ec6608")
            self.assertEqual(preview["font_family"], "Calibri")
            self.assertEqual(preview["logo_mode"], "wide")
            self.assertTrue(preview["logo_url"].startswith("/branding/examples/logserv/logo.png?v="))

    def test_shipped_bistro_demo_uses_primary_logo_and_soft_colors(self):
        root = Path(__file__).resolve().parents[1]
        demo = root / "branding" / "examples" / "logserv"
        self.assertTrue((demo / "brand.yaml").is_file())
        logo = demo / "logo.png"
        group = demo / "group-logo.png"
        claim = demo / "claim-logo.png"
        footer_banner = demo / "footer-banner.png"
        self.assertEqual(logo.read_bytes()[:8], bytes((137, 80, 78, 71, 13, 10, 26, 10)))
        self.assertEqual(group.read_bytes()[:8], bytes((137, 80, 78, 71, 13, 10, 26, 10)))
        self.assertEqual(claim.read_bytes()[:8], bytes((137, 80, 78, 71, 13, 10, 26, 10)))
        self.assertEqual(footer_banner.read_bytes()[:8], bytes((137, 80, 78, 71, 13, 10, 26, 10)))
        brand = read_brand(root, profile="logserv")
        self.assertEqual(brand["brand_name"], "Bistro Connect")
        self.assertEqual(brand["layout"], "bistro")
        self.assertTrue(brand["source_in_header"])
        self.assertFalse(brand["show_group_logo"])
        self.assertEqual(brand["tagline"], "")
        self.assertEqual(brand["header_color"], "#ffef85")
        self.assertEqual(brand["footer_color"], "#ffdd00")
        self.assertEqual(brand["background_color"], "#fff8cf")
        self.assertEqual(brand["font_family"], "Calibri")
        self.assertEqual(brand["footer_names"], ["Logserv", "Friedrich Friedrich", "Höhne-Grass", "J. & G. Adrian", "KS Büromöbel"])
        self.assertTrue(brand["logo_url"].startswith("/branding/examples/logserv/logo.png?v="))
        self.assertTrue(brand["group_logo_url"].startswith("/branding/examples/logserv/claim-logo.png?v="))
        self.assertTrue(brand["footer_banner_url"].startswith("/branding/examples/logserv/footer-banner.png?v="))
        with main.app.test_client() as client:
            self.assertEqual(client.get("/branding/examples/logserv/group-logo.png").status_code, 200)
            self.assertEqual(client.get("/branding/examples/logserv/claim-logo.png").status_code, 200)
            self.assertEqual(client.get("/branding/examples/logserv/footer-banner.png").status_code, 200)
            player = client.get("/demo/logserv").get_data(as_text=True)
            self.assertIn('id="group-logo"', player)
            self.assertIn('id="footer-banner"', player)
            self.assertIn('id="footer-names"', player)
            self.assertIn('id="header-source"', player)
            self.assertIn("body.bistro-layout h1", player)
            self.assertIn("body.hide-group-logo #group-logo", player)
            self.assertIn("Aktuelle Nachrichten aus ", player)
            self.assertIn('span.textContent = name', player)
            self.assertIn('min-width:1600px', player)
            self.assertIn('clamp(84px,12vh,130px)', player)
            self.assertIn('grid-template-columns:minmax(0,56%) minmax(0,1fr)', player)
            self.assertIn('object-fit:contain', player)
            self.assertIn('min-width:901px', player)
            self.assertIn('h1.long-title', player)

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
