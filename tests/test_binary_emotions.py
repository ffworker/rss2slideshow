import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from app import main
from addons.binary_emotions import inventory_text, render_slide_jpeg


class BinaryEmotionsAddonTests(unittest.TestCase):
    def setUp(self):
        with main.lock:
            self.old_snapshot = {
                "articles": list(main.snapshot["articles"]),
                "updated_at": main.snapshot["updated_at"],
                "sources": list(main.snapshot["sources"]),
            }

    def tearDown(self):
        with main.lock:
            main.snapshot.clear()
            main.snapshot.update(self.old_snapshot)

    def sample_articles(self):
        return [
            {
                "id": "a" * 20,
                "source": "Südhessen",
                "title": "Erste Testmeldung für den alten Slideshow Player",
                "summary": "Das ist nur ein Testtext für die gerenderte JPEG-Ausgabe.",
                "image": "",
                "published": None,
                "url": "",
            },
            {
                "id": "b" * 20,
                "source": "Hessen",
                "title": "Zweite Meldung",
                "summary": "Noch etwas Text.",
                "image": "",
                "published": None,
                "url": "",
            },
        ]

    def test_inventory_helper_returns_plain_jpeg_urls(self):
        text = inventory_text(self.sample_articles(), "http://reader.example.test", limit=1)
        self.assertEqual(
            text,
            "http://reader.example.test/addons/binary-emotions/slides/" + ("a" * 20) + ".jpg\n",
        )

    def test_renderer_returns_real_1920x1080_jpeg(self):
        jpeg = render_slide_jpeg(
            self.sample_articles()[0],
            {
                "brand_name": "RSS2Slideshow",
                "accent_color": "#2563eb",
                "background_color": "#f8fafc",
                "text_color": "#202020",
                "header_color": "#ffffff",
                "footer_color": "#eef2f7",
                "footer_names": ["Example Organization", "Example Team"],
                "show_footer_names": True,
            },
        )
        self.assertTrue(jpeg.startswith(b"\xff\xd8\xff"))
        with Image.open(BytesIO(jpeg)) as image:
            self.assertEqual(image.size, (1920, 1080))
            self.assertEqual(image.format, "JPEG")

    def test_http_addon_is_hidden_until_enabled(self):
        with patch.object(main, "BINARY_EMOTIONS_ADDON", False):
            with main.app.test_client() as client:
                self.assertEqual(client.get("/addons/binary-emotions/inventory.txt").status_code, 404)

    def test_http_inventory_and_slide_work_when_enabled(self):
        articles = self.sample_articles()
        with main.lock:
            main.snapshot["articles"] = articles
            main.snapshot["sources"] = ["Südhessen", "Hessen"]
            main.snapshot["updated_at"] = "2026-09-28T10:00:00+00:00"

        with patch.object(main, "BINARY_EMOTIONS_ADDON", True), \
             patch.object(main, "BINARY_EMOTIONS_LIMIT", 2):
            with main.app.test_client() as client:
                inventory = client.get(
                    "/addons/binary-emotions/inventory.txt",
                    base_url="http://reader.example.test",
                )
                self.assertEqual(inventory.status_code, 200)
                self.assertEqual(inventory.mimetype, "text/plain")
                self.assertIn(
                    "http://reader.example.test/addons/binary-emotions/slides/" + ("a" * 20) + ".jpg",
                    inventory.get_data(as_text=True),
                )

                slide = client.get("/addons/binary-emotions/slides/" + ("a" * 20) + ".jpg")
                self.assertEqual(slide.status_code, 200)
                self.assertEqual(slide.mimetype, "image/jpeg")
                self.assertTrue(slide.data.startswith(b"\xff\xd8\xff"))

                self.assertEqual(
                    client.get("/addons/binary-emotions/slides/not-an-id.jpg").status_code,
                    404,
                )


if __name__ == "__main__":
    unittest.main()
