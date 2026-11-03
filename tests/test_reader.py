import unittest
from unittest.mock import Mock, patch

import feedparser

from app import main


def xml(title, name):
    return ("""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>""" + name + """</title>
<item><title>""" + title + """</title><description><![CDATA[
<b>Short story</b> and more.]]></description>
<link>https://example.org/article</link>
<enclosure url="https://example.org/photo.jpg" type="image/jpeg" length="0"/>
<pubDate>Tue, 22 Sep 2026 09:00:00 GMT</pubDate>
</item></channel></rss>""").encode()


class ReaderTests(unittest.TestCase):
    def test_rss_turns_into_normal_article_data(self):
        feed = feedparser.parse(xml("Some news", "Local paper"))
        with patch.dict(main.CFG, {"news_images": True}):
            source, stories = main.parse_articles(feed, "", "https://example.org/rss")
        self.assertEqual(source, "Local paper")
        self.assertEqual(stories[0]["title"], "Some news")
        self.assertEqual(stories[0]["summary"], "Short story and more.")
        self.assertEqual(stories[0]["image"], "https://example.org/photo.jpg")
        self.assertIn("2026-09-22", stories[0]["published"])

    def test_named_feeds_get_mixed_instead_of_one_big_block(self):
        def fake_get(url, **kwargs):
            answer = Mock()
            answer.content = xml("A", "first") if "one" in url else xml("B", "second")
            answer.raise_for_status.return_value = None
            return answer

        sources = [("First", "https://example.org/one"), ("Second", "https://example.org/two")]
        with patch.object(main, "get_feeds", return_value=sources), patch.object(main.requests, "get", side_effect=fake_get):
            main.refresh()
        with main.app.test_client() as client:
            result = client.get("/api/articles")
            self.assertEqual(result.status_code, 200)
            stories = result.get_json()["articles"]
            self.assertEqual([story["source"] for story in stories], ["First", "Second"])
            self.assertEqual(client.get("/kiosk").status_code, 200)
            self.assertEqual(client.get("/inventory.txt").status_code, 404)

    def test_legacy_config_feed_is_not_loaded(self):
        sources = [("File feed", "https://example.org/one")]
        response = Mock()
        response.content = xml("From file", "File feed")
        response.raise_for_status.return_value = None
        with patch.dict(main.CFG, {
            "rss_url": "https://example.org/OLD",
            "news_source_label": "OLD source"
        }), patch.object(main, "get_feeds", return_value=sources) as reader, \
             patch.object(main.requests, "get", return_value=response) as fetch:
            main.refresh()
        reader.assert_called_once_with(main.FEED_FILE)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], "https://example.org/one")

    def test_kiosk_renders_per_slide_qr_without_external_service(self):
        with main.app.test_client() as client:
            page = client.get('/kiosk').data.decode()
        self.assertIn('id="article-qr"', page)
        self.assertIn('story.qr_url', page)
        self.assertIn('<strong>HIER</strong> zum ganzen Artikel', page)
        self.assertIn('function placeArticleQr(withPicture)', page)
        self.assertIn('placeArticleQr(true)', page)
        self.assertIn('placeArticleQr(false)', page)
        self.assertIn('.visual .article-qr', page)
        self.assertIn('.copy .article-qr', page)
        self.assertNotIn('api.qrserver.com', page)

    def test_only_safe_article_links(self):
        self.assertEqual(main.http_url("javascript:alert(1)"), "")
        self.assertEqual(main.http_url("https://example.org/news"), "https://example.org/news")

    def test_article_qr_is_local_and_encodes_original_link(self):
        feed = feedparser.parse(xml("Some news", "Local paper"))
        _, stories = main.parse_articles(feed, "", "https://example.org/rss")
        with patch.dict(main.snapshot, {"articles": stories}):
            with main.app.test_client() as client:
                article = client.get("/api/articles").get_json()["articles"][0]
                self.assertTrue(article["qr_url"].startswith(f'/qr/{article["id"]}/'))
                self.assertTrue(article["qr_url"].endswith('.png'))
                with patch.object(main, "make_qr_png", return_value=b"png") as qr:
                    image = client.get(article["qr_url"])
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image.mimetype, "image/png")
                self.assertEqual(image.data, b"png")
                qr.assert_called_once_with("https://example.org/article")

    def test_qr_changes_with_article_url_and_old_image_stops_serving(self):
        feed = feedparser.parse(xml("Some news", "Local paper"))
        _, stories = main.parse_articles(feed, "", "https://example.org/rss")
        with patch.dict(main.snapshot, {"articles": stories}):
            with main.app.test_client() as client:
                first = client.get('/api/articles').get_json()['articles'][0]['qr_url']
                stories[0]['url'] = 'https://example.org/second-article'
                second = client.get('/api/articles').get_json()['articles'][0]['qr_url']
                self.assertNotEqual(first, second)
                self.assertEqual(client.get(first).status_code, 404)
                self.assertEqual(client.get(second).status_code, 200)

    def test_no_qr_for_missing_or_invalid_article_link(self):
        feed = feedparser.parse(xml("Some news", "Local paper"))
        _, stories = main.parse_articles(feed, "", "https://example.org/rss")
        stories[0]["url"] = "javascript:alert(1)"
        with patch.dict(main.snapshot, {"articles": stories}):
            with main.app.test_client() as client:
                article = client.get("/api/articles").get_json()["articles"][0]
                self.assertEqual(article["qr_url"], "")
                self.assertEqual(client.get(f'/qr/{article["id"]}.png').status_code, 404)
                self.assertEqual(client.get('/qr/missing.png').status_code, 404)


if __name__ == "__main__":
    unittest.main()
